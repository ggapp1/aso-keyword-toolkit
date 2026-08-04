"""Command line interface.

  asokit init                          write a starter config
  asokit storefronts [--check cc]      list / verify storefronts
  asokit research --market de          expand + score, write a report
  asokit metadata check <file>         validate limits and duplication
  asokit metadata status               what App Store Connect will accept
  asokit metadata push <file> [--apply]  sync (dry run unless --apply)
"""

import argparse
import json
import os
import sys
from pathlib import Path

from . import asc, metadata as meta, report, research, sources, storefronts, suggest

DEFAULT_CONFIG = "asokit.json"

STARTER_CONFIG = {
    "app": {"name": "Your App", "appId": 0, "outputDir": "aso"},
    "markets": {
        "de": {
            "seeds": [
                "your english keyword",
                "another english keyword",
                "dein deutsches keyword",
            ],
            "notes": "Include native AND English seeds — in many stores users search in English.",
        }
    },
}


def load_config(path):
    config_path = Path(path)
    if not config_path.exists():
        sys.exit(f"no config at {config_path}. Run `asokit init` to create one.")
    return json.loads(config_path.read_text())


def market_config(config, market):
    if market not in config["markets"]:
        sys.exit(
            f"market '{market}' is not in the config. "
            f"Configured: {', '.join(config['markets']) or '(none)'}"
        )
    entry = dict(config["markets"][market])
    entry.setdefault("country", market)
    return entry


def cmd_init(args):
    path = Path(args.config)
    existing = None
    if path.exists():
        if args.add:
            existing = json.loads(path.read_text())
        elif not args.force:
            sys.exit(
                f"{path} already exists.\n"
                "  --add    keep it and add the requested markets\n"
                "  --force  overwrite it"
            )

    if not args.app_id and not existing:
        path.write_text(json.dumps(STARTER_CONFIG, indent=2) + "\n")
        print(f"wrote {path}")
        print("\nAdd your appId and seeds, then run: asokit research --market de")
        print("Tip: `asokit init --app-id 1234567890 --force` fills both in for you")
        print("by reading your live listing. Your appId is the number in your")
        print("App Store URL, e.g. apps.apple.com/app/id1234567890")
        return

    markets = [m.strip().lower() for m in args.markets.split(",") if m.strip()]
    unknown = [m for m in markets if m not in storefronts.STOREFRONTS]
    if unknown:
        sys.exit(f"unknown market(s): {', '.join(unknown)}. See `asokit storefronts`.")

    app_id = args.app_id or (existing or {}).get("app", {}).get("appId")
    if not app_id:
        sys.exit("need --app-id (or an existing config with app.appId) to derive seeds")

    home = args.home
    print(f"reading your listing in the {home.upper()} store...")
    app = sources.lookup(app_id, home)
    if not app:
        sys.exit(
            f"app {app_id} not found in the {home} store.\n"
            "Check the ID, or pass --home with the country where it's published."
        )
    print(f"  {app.get('trackName')} — {app.get('primaryGenreName')}")

    print("looking at apps that rank alongside it (this takes a moment)...")
    seeds, context = suggest.from_app(app_id, home)
    print(f"  read {context['competitorsRead']} competitor listings")

    config = existing or {
        "app": {"name": app.get("trackName"), "appId": int(app_id), "outputDir": "aso"},
        "markets": {},
    }
    config.setdefault("markets", {})
    config["app"].setdefault("genre", app.get("primaryGenreName"))

    added, skipped = [], []
    for market in markets:
        if market in config["markets"] and existing:
            skipped.append(market)
            continue
        config["markets"][market] = {
            "country": market,
            "notes": f"Seeds derived from the {home.upper()} listing. "
            "Add native-language terms for this market before your real run.",
            "seeds": seeds,
        }
        added.append(market)

    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")

    if added:
        print(f"\nwrote {path} — added {', '.join(added)} with {len(seeds)} seeds")
    if skipped:
        print(f"kept existing config for: {', '.join(skipped)} (already present)")
    print("\nSuggested seeds:")
    for seed in seeds:
        print(f"  {seed}")
    print(
        "\nThese come from English-language listings. For non-English markets,\n"
        "add native terms too — that is where the openings usually are.\n"
    )
    if added:
        print(f"Next: asokit research --market {added[0]}")


def cmd_doctor(args):
    """Check that everything needed is present, before a long run fails."""
    ok = True

    config_path = Path(args.config)
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            app = config.get("app", {})
            markets = config.get("markets", {})
            print(f"config      {config_path} — {len(markets)} market(s)")
            if not app.get("appId"):
                print("            no appId set — you'll get keyword data but no rank column")
            for name, market in markets.items():
                if not market.get("seeds"):
                    print(f"            market '{name}' has no seeds")
                    ok = False
        except json.JSONDecodeError as error:
            print(f"config      {config_path} is not valid JSON — {error}")
            ok = False
    else:
        print(f"config      missing ({config_path}) — run `asokit init`")
        ok = False

    try:
        hints = sources.autocomplete("budget", "us")
        if hints:
            print(f"apple api   reachable — {len(hints)} suggestions for a test query")
        else:
            print("apple api   reachable but returned nothing; may be rate limited")
    except SystemExit:
        print("apple api   rate limited right now — wait a few minutes")
        ok = False
    except Exception as error:  # noqa: BLE001 - diagnostics should never crash
        print(f"apple api   unreachable — {error}")
        ok = False

    creds = [os.environ.get(name) for name in ("ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_PRIVATE_KEY_PATH")]
    if all(creds):
        key_path = Path(creds[2]).expanduser()
        if key_path.exists():
            print("connect     credentials set, key file found")
        else:
            print(f"connect     credentials set but key file missing at {key_path}")
            ok = False
        try:
            import jwt  # noqa: F401
        except ImportError:
            print("connect     needs: pip install 'aso-keyword-toolkit[connect]'")
            ok = False
    else:
        print("connect     not configured (only needed to push metadata)")

    print("\nready" if ok else "\nsome checks failed — see above")
    sys.exit(0 if ok else 1)


def cmd_storefronts(args):
    if args.check:
        country = args.check.lower()
        header = storefronts.header(country)
        hints = sources.autocomplete(args.term, country)
        print(f"{storefronts.name(country)} ({country}) header={header}")
        print(f"  suggestions for {args.term!r}: {', '.join(hints[:6]) or '(none)'}")
        print("\nIf these look like the wrong country or language, the storefront ID is wrong.")
        return
    for code, (identifier, label, locale) in sorted(
        storefronts.STOREFRONTS.items(), key=lambda item: item[1][1]
    ):
        print(f"  {code}  {identifier}  {label:<24} {locale}")
    print(f"\n{len(storefronts.STOREFRONTS)} storefronts. Verify one: asokit storefronts --check de")


def run_market(config, market_name, args):
    market = market_config(config, market_name)
    country = market["country"]
    app = config.get("app", {})
    app_id = app.get("appId") or None

    output = Path(args.out or Path(app.get("outputDir", "aso")) / market_name)
    output.mkdir(parents=True, exist_ok=True)
    cache = None if args.no_cache else sources.Cache(output / ".cache.json")

    our_genre = app.get("genre")
    if app_id and not our_genre:
        listing = sources.lookup(app_id, country, cache)
        our_genre = listing.get("primaryGenreName") if listing else None

    seeds = market["seeds"]
    seeds_lower = {seed.lower() for seed in seeds}
    print(f"\n{storefronts.name(country)} — expanding {len(seeds)} seeds")

    evidence = research.expand(
        seeds,
        country,
        cache,
        progress=lambda seed, count: print(f"  {seed} -> {count} suggestions"),
    )
    (output / "expansion.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False))

    candidates = research.rank_candidates(evidence, args.limit, seeds_lower)
    minutes = len(candidates) * sources.SEARCH_DELAY / 60
    print(f"scoring {len(candidates)} candidates (~{minutes:.0f} min if not cached)")

    scores = []
    for index, term in enumerate(candidates, start=1):
        print(f"  [{index}/{len(candidates)}] {term}")
        scores.append(
            research.score(
                term, evidence[term], country, app_id, cache, seeds_lower, our_genre
            )
        )

    (output / "scores.json").write_text(json.dumps(scores, indent=2, ensure_ascii=False))
    label = app.get("name", "unknown") + (f" ({app_id})" if app_id else " — no appId set")
    (output / "report.md").write_text(
        report.render(storefronts.name(country), country, label, scores)
    )
    return output, scores, app_id


def summarize(scores, app_id):
    """The three things worth reading first, so the table isn't a wall."""
    targetable = [
        s for s in scores if not s["looksLikeAppName"] and not s.get("offCategory")
    ]
    openings = sorted(
        (s for s in targetable if s["competitionTier"] <= 2 and s["popularity"] > 0),
        key=lambda s: -s["opportunity"],
    )[:3]
    ranked = sorted(
        (s for s in targetable if s["ourRank"]), key=lambda s: s["ourRank"]
    )[:3]
    gaps = [s for s in openings if not s["ourRank"]][:3]

    lines = []
    if openings:
        lines.append("  least contested:  " + ", ".join(s["term"] for s in openings))
    if app_id and ranked:
        lines.append(
            "  you already rank: "
            + ", ".join(f"{s['term']} (#{s['ourRank']})" for s in ranked)
        )
        # Only worth calling out once some ranks exist; otherwise every opening
        # is trivially a gap and this line just repeats the one above.
        if gaps:
            lines.append("  winnable gaps:    " + ", ".join(s["term"] for s in gaps))
    elif app_id:
        lines.append("  not ranking yet for any scored term")
    return lines


def cmd_research(args):
    config = load_config(args.config)
    if args.all:
        markets = list(config["markets"])
    elif args.market:
        markets = [args.market]
    else:
        sys.exit("pass --market <code> or --all")

    if args.all and args.out:
        sys.exit("--out sets a single directory; it cannot be combined with --all")

    for name in markets:
        output, scores, app_id = run_market(config, name, args)
        print(f"\n{output / 'report.md'}")
        for line in summarize(scores, app_id):
            print(line)

    print("\nRead the report, then draft metadata and validate it:")
    print("  asokit metadata check my-metadata.json")


def cmd_metadata_check(args):
    data = json.loads(Path(args.file).read_text())
    problems = meta.check(data)
    for locale, fields in sorted(data.items()):
        print(f"\n{'=' * 58}\n{locale}\n{'=' * 58}")
        for field in ("name", "subtitle", "keywords", "promotionalText", "description"):
            if field in fields:
                limit = meta.LIMITS.get(field)
                used = len(fields[field])
                gauge = f"{used}/{limit}" if limit else str(used)
                print(f"\n--- {field} ({gauge}) ---\n{fields[field]}")
    if problems:
        print(f"\n{'!' * 58}\n{len(problems)} problem(s)\n{'!' * 58}")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)
    print("\nAll fields within limits. No repetition across name, subtitle and keywords.")


def _app_id(args, config):
    return args.app_id or config.get("app", {}).get("appId")


def cmd_metadata_status(args):
    config = load_config(args.config) if Path(args.config).exists() else {}
    app_id = _app_id(args, config)
    if not app_id:
        sys.exit("need an appId — pass --app-id or set app.appId in the config")
    info = asc.status(app_id, asc.token())
    print(f"{info['app']} ({info['bundleId']})")
    if info["editableVersion"]:
        version = info["editableVersion"]
        print(f"editable version {version['version']} — {version['state']}")
    else:
        print("NO EDITABLE VERSION — create one in App Store Connect before pushing.")
        print(f"  recent: {', '.join(info.get('recentStates', []))}")
    print(f"name/subtitle locales ({len(info['infoLocales'])}): {', '.join(info['infoLocales'])}")
    print(
        f"keyword/description locales ({len(info['versionLocales'])}): "
        f"{', '.join(info['versionLocales'])}"
    )


def cmd_metadata_push(args):
    config = load_config(args.config) if Path(args.config).exists() else {}
    app_id = _app_id(args, config)
    if not app_id:
        sys.exit("need an appId — pass --app-id or set app.appId in the config")

    data = json.loads(Path(args.file).read_text())
    problems = meta.check(data)
    if problems:
        print("validation failed — nothing sent:")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)

    actions = asc.push(app_id, data, asc.token(), apply=args.apply)
    for action in actions:
        print(
            f"  {action['locale']:<8} {action['resource']:<28} "
            f"{action['operation']:<6} {', '.join(action['fields'])}"
        )
    if args.apply:
        print("\napplied — verify in App Store Connect before submitting.")
    else:
        print("\nDRY RUN — nothing written. Re-run with --apply to push.")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="asokit",
        description="Free App Store keyword research and metadata sync.",
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG, help=f"default: {DEFAULT_CONFIG}")
    subcommands = parser.add_subparsers(dest="command", required=True)

    initialize = subcommands.add_parser(
        "init", help="write a config, optionally derived from your live listing"
    )
    initialize.add_argument(
        "--app-id", help="your App Store id — reads your listing and suggests seeds"
    )
    initialize.add_argument(
        "--markets", default="de", help="comma-separated country codes (default: de)"
    )
    initialize.add_argument(
        "--home", default="us", help="store to read your listing from (default: us)"
    )
    initialize.add_argument(
        "--add", action="store_true", help="add markets to an existing config"
    )
    initialize.add_argument("--force", action="store_true", help="overwrite an existing config")
    initialize.set_defaults(func=cmd_init)

    doctor = subcommands.add_parser("doctor", help="check config, connectivity, credentials")
    doctor.set_defaults(func=cmd_doctor)

    storefront = subcommands.add_parser("storefronts", help="list or verify storefronts")
    storefront.add_argument("--check", metavar="CC", help="verify one country code live")
    storefront.add_argument("--term", default="budget", help="probe term for --check")
    storefront.set_defaults(func=cmd_storefronts)

    research_command = subcommands.add_parser("research", help="expand and score keywords")
    research_command.add_argument("--market", help="country code from your config")
    research_command.add_argument(
        "--all", action="store_true", help="run every market in the config"
    )
    research_command.add_argument("--limit", type=int, default=45, help="candidates to score")
    research_command.add_argument("--out", help="output directory")
    research_command.add_argument("--no-cache", action="store_true")
    research_command.set_defaults(func=cmd_research)

    metadata_command = subcommands.add_parser("metadata", help="validate and sync metadata")
    metadata_sub = metadata_command.add_subparsers(dest="metadata_command", required=True)

    check = metadata_sub.add_parser("check", help="validate limits and duplication")
    check.add_argument("file")
    check.set_defaults(func=cmd_metadata_check)

    status = metadata_sub.add_parser("status", help="what App Store Connect will accept")
    status.add_argument("--app-id")
    status.set_defaults(func=cmd_metadata_status)

    push = metadata_sub.add_parser("push", help="sync metadata (dry run unless --apply)")
    push.add_argument("file")
    push.add_argument("--app-id")
    push.add_argument("--apply", action="store_true")
    push.set_defaults(func=cmd_metadata_push)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (asc.ASCError, storefronts.UnknownStorefront) as error:
        sys.exit(str(error))
    except KeyboardInterrupt:
        sys.exit("\ninterrupted — cached results were kept")


if __name__ == "__main__":
    main()
