"""Command line interface.

  asokit init                          write a starter config
  asokit storefronts [--check cc]      list / verify storefronts
  asokit research --market de          expand + score, write a report
  asokit metadata suggest --market de  pack research into a keyword field
  asokit metadata pull                 capture the live listing as JSON
  asokit metadata check <file>         validate limits and duplication
  asokit metadata status               what App Store Connect will accept
  asokit metadata push <file> [--apply]  sync (dry run unless --apply)
  asokit products status               list IAPs/subscriptions and their locales
  asokit products check <file>         validate product text limits
  asokit products push <file> [--apply]  sync product text (dry run unless --apply)
  asokit products apply <file> [--apply]  provision products, prices, availability
  asokit assets render [--variant V]   render header/search creatives from assets.json
  asokit assets status [--catalog]     library, asset states, placements
  asokit assets push DIR --target default [--apply]   place creatives
  asokit assets submit DIR [--apply]   standalone review of creatives
  asokit cpp check [--offline]         validate cpp.json (keywords, limits, files)
  asokit cpp status [--ads-export P]   live custom product pages
  asokit cpp push [--apply]            converge pages to cpp.json (created hidden)
  asokit cpp submit --pages N [--apply]   send page versions to App Review
  asokit cpp publish --pages N [--apply]  make approved pages visible (routing goes live)
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from . import (
    asc,
    cpp,
    cpp_apply,
    creative,
    ledger as ledger_module,
    library,
    metadata as meta,
    packing,
    products as prod,
    report,
    research,
    review,
    sources,
    storefronts,
    suggest,
    screenshots as shots,
)

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

    if all(creds):
        _report_territories(config_path, args)

    print("\nready" if ok else "\nsome checks failed — see above")


def _report_territories(config_path, args):
    """Say which configured markets the app is not actually sold in.

    Only called when App Store Connect credentials are configured — without
    them there is nothing to ask, and a failure line would just be noise.

    An hour of scoring for a storefront nobody can buy in is pure waste, and
    the reverse mistake is worse: dropping a market on the assumption the app
    is not sold there when it is. Advisory, not a failure — researching ahead
    of a launch is legitimate.
    """
    if not config_path.exists():
        return
    try:
        config = json.loads(config_path.read_text())
    except json.JSONDecodeError:
        return
    app_id = args.app_id or config.get("app", {}).get("appId")
    markets = config.get("markets", {})
    if not app_id or not markets:
        return

    try:
        available = asc.available_territories(app_id, asc.token())
    except Exception as error:  # noqa: BLE001 - diagnostics should never crash
        print(f"territories could not be read — {error}".split("\n")[0])
        return
    if available is None:
        print("territories no availability record on this app yet")
        return

    print(f"territories on sale in {len(available)} territory(ies)")
    unknown, unavailable = [], []
    for market in sorted(markets):
        code = storefronts.TERRITORIES.get(market.lower())
        if not code:
            unknown.append(market)
        elif code not in available:
            unavailable.append(market)
    if unavailable:
        print(
            f"            NOT on sale in: {', '.join(unavailable)} — "
            "researching those storefronts scores keywords nobody can act on"
        )
    if unknown:
        print(f"            no territory mapping for: {', '.join(unknown)}")
    if not unavailable and not unknown:
        print(f"            all {len(markets)} configured market(s) are on sale")
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


def output_dir(config, market_name, args):
    """Where one market's output goes.

    With --all, --out is read as the PARENT of the per-market directories
    rather than rejected: output is per-market anyway (`aso/<market>/`), so
    that is the reading the flag invites.
    """
    if args.out:
        return Path(args.out) / market_name if args.all else Path(args.out)
    return Path(config.get("app", {}).get("outputDir", "aso")) / market_name


def run_market(config, market_name, args):
    market = market_config(config, market_name)
    country = market["country"]
    app = config.get("app", {})
    app_id = app.get("appId") or None

    output = output_dir(config, market_name, args)
    output.mkdir(parents=True, exist_ok=True)
    cache = None if args.no_cache else sources.Cache(output / ".cache.json")

    our_genre = app.get("genre")
    if app_id and not our_genre:
        listing = sources.lookup(app_id, country, cache)
        our_genre = listing.get("primaryGenreName") if listing else None

    seeds = market["seeds"]
    seeds_lower = {seed.lower() for seed in seeds}
    print(f"\n{storefronts.name(country)} — expanding {len(seeds)} seeds", flush=True)

    evidence = research.expand(
        seeds,
        country,
        cache,
        progress=lambda seed, count: print(f"  {seed} -> {count} suggestions", flush=True),
    )
    (output / "expansion.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False))

    candidates = research.rank_candidates(evidence, args.limit, seeds_lower)
    minutes = len(candidates) * sources.SEARCH_DELAY / 60
    print(
        f"scoring {len(candidates)} candidates (~{minutes:.0f} min if not cached)", flush=True
    )

    scores = []
    for index, term in enumerate(candidates, start=1):
        print(f"  [{index}/{len(candidates)}] {term}", flush=True)
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

    done = []
    for name in markets:
        if args.resume and (output_dir(config, name, args) / "scores.json").exists():
            # A failure at market 30 of 37 otherwise loses the whole loop: the
            # response cache keeps the data, but every market is re-driven.
            print(f"\n{name}: already scored, skipping (--resume)", flush=True)
            continue
        output, scores, app_id = run_market(config, name, args)
        done.append(name)
        print(f"\n{output / 'report.md'}", flush=True)
        for line in summarize(scores, app_id):
            print(line, flush=True)

    if not done and args.resume:
        print("\nEvery configured market already has scores. Drop --resume to redo them.")
        return
    print("\nRead the report, then draft the keyword field and validate it:")
    print("  asokit metadata suggest --all --baseline baseline.json --json --out draft.json")
    print("  asokit metadata check draft.json")


def cmd_metadata_check(args):
    data = json.loads(Path(args.file).read_text())
    problems = meta.check(data, strict=args.strict, allow_partial=args.allow_partial)
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
        _print_stemming_note(data)
        sys.exit(1)
    print("\nAll fields within limits. No repetition across name, subtitle and keywords.")
    _print_stemming_note(data)


def _print_stemming_note(data):
    """Say where the duplication check could only compare exact words.

    Apple matches on stems, but morphology is per-language and we only have
    rules for some. Staying quiet would let a clean run read as a verdict on
    locales we never really checked.
    """
    unstemmed = meta.unstemmed_locales(data)
    if not unstemmed:
        return
    shown = ", ".join(unstemmed[:8]) + (f" +{len(unstemmed) - 8} more" if len(unstemmed) > 8 else "")
    print(
        f"\nnote: no stemming rules for {shown} — those locales were compared as exact "
        "words only, so repetition between a stem and its inflected form is not reported."
    )


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
    problems = meta.check(data, allow_partial=args.allow_partial)
    if problems:
        print("validation failed — nothing sent:")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)

    def show(action):
        # flush: a 37-locale push is long enough that people redirect it to a
        # file, and Python block-buffers stdout off a TTY. Without this the log
        # stays empty until the process exits — which is exactly when a failed
        # run has nothing to say.
        print(
            f"  {action['locale']:<8} {action['resource']:<28} "
            f"{action['operation']:<8} {', '.join(action['fields'])}",
            flush=True,
        )

    try:
        actions = asc.push(app_id, data, asc.token(), apply=args.apply, progress=show)
    except asc.ASCError as error:
        # The lines above are the record of what already landed. Say so plainly
        # rather than leaving the user to query the API to find out, and point
        # at the re-run, which converges because push adopts what it finds.
        print(f"\naborted — {error}", flush=True)
        print(
            "\nThe locales listed above were already written; the rest were not. "
            "Re-running is safe: push adopts localizations that already exist and "
            "patches them, so a second pass finishes the job.",
            flush=True,
        )
        sys.exit(1)

    if args.apply:
        tally = {}
        for action in actions:
            tally[action["operation"]] = tally.get(action["operation"], 0) + 1
        summary = ", ".join(f"{count} {name}" for name, count in sorted(tally.items()))
        print(f"\napplied ({summary}) — verify in App Store Connect before submitting.")
    else:
        print("\nDRY RUN — nothing written. Re-run with --apply to push.")


def _market_locale(config, market):
    entry = market_config(config, market)
    return entry.get("locale") or storefronts.default_locale(entry["country"])


def cmd_metadata_suggest(args):
    """Pack researched candidates into a keyword field — the missing middle step.

    `research` produces scored candidates and `check` validates a finished
    field; drafting the field between them is the hard part, and leaving it to
    the caller means everyone reimplements the same four defects.
    """
    config = load_config(args.config)
    app = config.get("app", {})
    if not args.all and not args.market:
        sys.exit("pass --market <code> or --all")
    markets = list(config["markets"]) if args.all else [args.market]

    baseline = json.loads(Path(args.baseline).read_text()) if args.baseline else {}
    blocked = {word.strip().lower() for word in (args.block or "").split(",") if word.strip()}
    root = Path(args.dir or app.get("outputDir", "aso"))

    drafted = {}
    for market in markets:
        locale = _market_locale(config, market)
        scores_path = root / market / "scores.json"
        if not scores_path.exists():
            message = f"no scores at {scores_path} — run `asokit research --market {market}` first"
            if args.all:
                print(f"  {market:<4} skipped: {message}", file=sys.stderr)
                continue
            sys.exit(message)

        live = baseline.get(locale, {})
        name = args.name if args.name is not None else live.get("name", "")
        subtitle = args.subtitle if args.subtitle is not None else live.get("subtitle", "")

        candidates = json.loads(scores_path.read_text())
        # Live terms join the pool last so researched ones win the early slots.
        # Without this, a hand-picked term that is already ranking is silently
        # discarded just because autocomplete never proposed it.
        candidates += packing.incumbent_candidates(live.get("keywords", ""))

        field = packing.select_keywords(
            candidates, name, subtitle, limit=args.limit, blocked=blocked, locale=locale
        )
        # With a baseline, emit the whole localization with only the keyword
        # field swapped, so the draft is something `check` passes and `push`
        # can send. A keywords-only fragment would trip the submission rule on
        # every locale, since a file carrying keywords and no description is
        # exactly the unsubmittable shape that rule exists to catch.
        drafted[locale] = {**live, "keywords": field}

        if not args.json:
            print(f"\n{market} -> {locale}  ({len(field)}/{args.limit} characters)")
            if not name and not subtitle:
                print(
                    "  no name or subtitle known, so words they already cover were not "
                    "excluded — pass --name/--subtitle or --baseline"
                )
            print(f"  {field}")
            kept = set(packing.words(field.replace(",", " ")))
            dropped = _dropped_reasons(candidates, kept, blocked, locale)
            if dropped:
                print("  dropped: " + "; ".join(dropped))

    if args.json:
        rendered = json.dumps(drafted, indent=2, ensure_ascii=False)
        if args.out:
            Path(args.out).write_text(rendered + "\n")
            note = "" if baseline else " (keywords only — no --baseline given)"
            print(f"{args.out} — {len(drafted)} locale(s){note}", file=sys.stderr)
        else:
            print(rendered)
    else:
        print("\nMerge these into your metadata file, then: asokit metadata check <file>")


def _dropped_reasons(candidates, kept, blocked, locale):
    """A short account of what the packer threw away, so it shows its work."""
    brands = packing.brand_words(candidates)
    filler = packing.language_filler(locale)
    # Brand words are taken from the set directly: most of them reach the pool
    # only through `topApps` names and never appear in a candidate term, so
    # walking the terms alone would report none of them.
    seen = {"brand": brands - kept, "filler": set(), "blocked": set()}
    for item in candidates:
        if item.get("looksLikeAppName") or item.get("offCategory"):
            continue
        for word in packing.words(item.get("term")):
            if word in kept or word in seen["brand"]:
                continue
            if word in blocked:
                seen["blocked"].add(word)
            elif packing.is_latin(word) and (
                word in filler or meta.stem(word, locale) in filler
            ):
                seen["filler"].add(word)
    labels = {
        "brand": "competitor app-name fragments",
        "filler": "stopwords",
        "blocked": "blocked",
    }
    return [
        f"{labels[key]} ({', '.join(sorted(found)[:6])})"
        for key, found in seen.items()
        if found
    ]


def cmd_metadata_pull(args):
    """Capture the live listing, so a bad push has somewhere to roll back to."""
    config = load_config(args.config) if Path(args.config).exists() else {}
    app_id = _app_id(args, config)
    if not app_id:
        sys.exit("need an appId — pass --app-id or set app.appId in the config")

    listing = asc.pull(app_id, asc.token())
    rendered = json.dumps(listing, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(rendered + "\n")
        fields = sum(len(v) for v in listing.values())
        print(f"{args.out} — {len(listing)} locale(s), {fields} field(s)", file=sys.stderr)
    else:
        print(rendered)


def _locale_rows(label, localizations):
    """(label, locale, field, value) for one {locale: {field: value}} map.

    Anything malformed is skipped rather than raised on: `check()` has already
    collected a problem for it, and a validator that dies with a traceback
    instead of listing the problems is the one failure mode that helps nobody.
    """
    if not isinstance(localizations, dict):
        return
    for locale, fields in sorted(localizations.items()):
        if not isinstance(fields, dict):
            continue
        for field, value in fields.items():
            yield label, locale, field, value


def _gauge_rows(data):
    """(label, locale, field, value) rows for either file format."""
    if not prod.is_declarative(data):
        for product_id, localizations in sorted(data.items()):
            for row in _locale_rows(product_id, localizations):
                yield row
        return
    groups = data.get("groups")
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, dict):
            continue
        label = f"group:{group.get('referenceName')}"
        for row in _locale_rows(label, group.get("localizations")):
            yield row
        subscriptions = group.get("subscriptions")
        for subscription in subscriptions if isinstance(subscriptions, list) else []:
            if not isinstance(subscription, dict):
                continue
            for row in _locale_rows(
                subscription.get("productId"), subscription.get("localizations")
            ):
                yield row


def cmd_products_check(args):
    data = json.loads(Path(args.file).read_text())
    problems = prod.check(data)
    current = None
    for label, locale, field, value in _gauge_rows(data):
        if label != current:
            print(f"\n{'=' * 58}\n{label}\n{'=' * 58}")
            current = label
        limit = prod.LIMITS.get(field)
        gauge = f"{len(value)}/{limit}" if isinstance(value, str) and limit else "?"
        print(f"  {locale:<8} {field:<14} ({gauge})  {value}")
    if problems:
        print(f"\n{'!' * 58}\n{len(problems)} problem(s)\n{'!' * 58}")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)
    print("\nAll fields within limits.")


def cmd_products_status(args):
    config = load_config(args.config) if Path(args.config).exists() else {}
    app_id = _app_id(args, config)
    if not app_id:
        sys.exit("need an appId — pass --app-id or set app.appId in the config")
    inventory = asc.products_status(app_id, asc.token())
    for group in inventory["subscriptionGroups"]:
        print(f"subscription group '{group['referenceName']}' (key: group:{group['referenceName']})")
        print(f"  locales: {', '.join(sorted(group['localizations'])) or '(none)'}")
        for subscription in group["subscriptions"]:
            print(f"  {subscription['productId']} — {subscription['state']}")
            for locale, item in sorted(subscription["localizations"].items()):
                print(f"    {locale:<8} {item.get('name')!r} / {item.get('description')!r} [{item.get('state')}]")
    for iap in inventory["inAppPurchases"]:
        print(f"in-app purchase {iap['productId']} — {iap['state']}")
        for locale, item in sorted(iap["localizations"].items()):
            print(f"    {locale:<8} {item.get('name')!r} / {item.get('description')!r} [{item.get('state')}]")
    if args.json:
        print(json.dumps(inventory, indent=2, ensure_ascii=False))


def cmd_products_push(args):
    config = load_config(args.config) if Path(args.config).exists() else {}
    app_id = _app_id(args, config)
    if not app_id:
        sys.exit("need an appId — pass --app-id or set app.appId in the config")

    data = json.loads(Path(args.file).read_text())
    problems = prod.check(data)
    if problems:
        print("validation failed — nothing sent:")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)

    actions = asc.push_products(app_id, data, asc.token(), apply=args.apply)
    for action in actions:
        print(
            f"  {action['product']:<32} {action['locale']:<8} "
            f"{action['operation']:<18} {', '.join(action['fields'])}"
        )
    if args.apply:
        print(
            "\napplied — verify in App Store Connect. Text changes to approved"
            "\nproducts go back through review with your next submission."
        )
    else:
        print("\nDRY RUN — nothing written. Re-run with --apply to push.")


def cmd_products_apply(args):
    config = load_config(args.config) if Path(args.config).exists() else {}
    app_id = _app_id(args, config)
    if not app_id:
        sys.exit("need an appId — pass --app-id or set app.appId in the config")

    data = json.loads(Path(args.file).read_text())
    if not prod.is_declarative(data):
        sys.exit(
            "this file is the flat localization format — use `asokit products push`.\n"
            "`apply` expects a declarative file with a top-level 'groups' key."
        )
    problems = prod.check(data)
    if problems:
        print("validation failed — nothing sent:")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)

    # Resolved before the try: a credentials failure is not a half-finished
    # run, and must not be reported as one.
    bearer = asc.token()
    try:
        actions = asc.apply_products(app_id, data, bearer, apply=args.apply)
    except asc.ASCError as error:
        if not args.apply:
            raise
        # A write failed and the run stopped there by design — 5xx is not
        # retried on writes. `apply_products` drops its executed list when the
        # exception propagates, so this genuinely cannot say which actions
        # landed. Re-reading live state is the only honest answer.
        sys.exit(
            f"{error}\n\n"
            "The run stopped at that write. Actions before it may already have\n"
            "been applied, and this cannot tell you which. Re-run without --apply:\n"
            "the dry run re-reads App Store Connect and shows what is still left."
        )

    for action in actions:
        kind = action["kind"]
        if kind == "skip":
            print(f"  skip               {action['what']}")
        elif kind == "setPrices":
            territories = action.get("territories")
            if territories is None:
                print(
                    f"  prices             {action['productId']} — "
                    f"{action['baseTerritory']} {action['customerPrice']} "
                    "(territories resolve after creation)"
                )
            elif not territories:
                print(f"  skip               {action['productId']} prices (unchanged)")
            else:
                print(
                    f"  prices             {action['productId']} — "
                    f"{len(territories)} territories at "
                    f"{action['baseTerritory']} {action['customerPrice']}"
                )
                if args.verbose:
                    for territory in territories:
                        print(f"      {territory}")
        elif kind in ("createLocalization", "updateLocalization"):
            operation = "create" if kind == "createLocalization" else "update"
            print(
                f"  {operation + ' localization':<18} "
                f"{action['parentKey']} {action['locale']} "
                f"({', '.join(sorted(action['fields']))})"
            )
        elif kind == "createGroup":
            print(f"  create group       {action['referenceName']}")
        elif kind == "createSubscription":
            print(f"  create             {action['productId']}")
        elif kind == "patchSubscription":
            print(
                f"  patch              {action['productId']} "
                f"({', '.join(sorted(action['attributes']))})"
            )
        elif kind == "setAvailability":
            # The executor counts the territories it would write; say the
            # number out loud, because this action puts the product on sale.
            count = action.get("territoryCount")
            scope = f" — on sale in {count} territories" if count else ""
            print(f"  availability       {action['productId']}{scope}")

    if args.apply:
        print(
            "\napplied. Subscriptions will sit in MISSING_METADATA until each one has"
            "\na review screenshot — add those in App Store Connect, then submit them"
            "\nalongside your next app version."
        )
    else:
        print("\nDRY RUN — nothing written. Re-run with --apply to provision.")


def cmd_screenshots_status(args):
    config = load_config(args.config) if Path(args.config).exists() else {}
    app_id = _app_id(args, config)
    if not app_id:
        sys.exit("need an appId — pass --app-id or set app.appId in the config")
    version, report = asc.screenshots_status(app_id, asc.token())
    print(f"editable version: {version}")
    for locale, families in report.items():
        line = ", ".join(f"{d} ×{n}" for d, n in sorted(families.items())) or "(inherits primary locale)"
        print(f"  {locale:<8} {line}")


def cmd_screenshots_push(args):
    config = load_config(args.config) if Path(args.config).exists() else {}
    app_id = _app_id(args, config)
    if not app_id:
        sys.exit("need an appId — pass --app-id or set app.appId in the config")
    plan = shots.plan_from_directory(args.directory, args.display)
    if args.locales:
        wanted = set(args.locales.split(","))
        plan = {k: v for k, v in plan.items() if k in wanted}
    problems = shots.check(plan)
    if problems:
        print("validation failed — nothing sent:")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)
    bearer = asc.token()
    if args.mirror:
        displays = args.mirror.split(",")
        sources = asc.mirror_sources(app_id, args.mirror_from, displays, bearer)
        for locale, families in plan.items():
            if locale == args.mirror_from:
                continue
            for display, images in sources.items():
                families[display] = images
        print(f"mirroring {', '.join(f'{d} ×{len(i)}' for d, i in sources.items())} from {args.mirror_from} into every other locale")

    def show(action):
        print(f"  {action['locale']:<8} {action['display']:<24} set:{action['set']:<7} "
              f"delete {action['delete']:>2}  upload {action['upload']:>2}", flush=True)

    try:
        actions = asc.push_screenshots(app_id, plan, bearer, apply=args.apply, progress=show)
    except asc.ASCError as error:
        print(f"\naborted — {error}", flush=True)
        print("\nSets listed above were already replaced; the rest were not. Re-running is safe: "
              "each set is replaced whole, so a second pass converges.", flush=True)
        sys.exit(1)
    if args.apply:
        ids = [sid for a in actions for sid in a["ids"]]
        print(f"\nuploaded {len(ids)} screenshots across {len(actions)} sets; waiting for Apple to process…", flush=True)
        import time as _time
        for _ in range(60):
            bearer = asc.token()   # the upload itself can outlive the 20-minute JWT
            states = asc.screenshot_states(ids, bearer)
            pending = [s for s in states.values() if s not in asc.SCREENSHOT_DONE and s != "FAILED"]
            if not pending:
                break
            _time.sleep(10)
        states = asc.screenshot_states(ids, asc.token())
        failed = [sid for sid, s in states.items() if s == "FAILED"]
        print(f"processed: {sum(1 for s in states.values() if s in asc.SCREENSHOT_DONE)} complete, "
              f"{len(failed)} failed, {len(states) - len(failed) - sum(1 for s in states.values() if s in asc.SCREENSHOT_DONE)} still pending")
        if failed:
            sys.exit(1)
        print("applied — verify in App Store Connect before submitting.")
    else:
        print("\nDRY RUN — nothing written. Re-run with --apply to push.")


def _bearer():
    return asc.Bearer()


def _config_path(args):
    return Path(args.config)


def _require_app_id(args):
    config = load_config(args.config) if Path(args.config).exists() else {}
    app_id = _app_id(args, config)
    if not app_id:
        sys.exit("need an appId — pass --app-id or set app.appId in the config")
    return config, app_id


def _locales_filter(plan, locales):
    if not locales:
        return plan
    wanted = set(locales.split(","))
    return {k: v for k, v in plan.items() if k in wanted}


def _print_actions(actions):
    for a in actions:
        print(f"  {a.get('locale', ''):<8} {a['type']:<32} {str(a.get('group')):<28} {a['mode']:<14} "
              f"+{a.get('place', 0)} -{a.get('unplace', 0)}", flush=True)


def cmd_assets_render(args):
    from . import render
    cfg_path = Path(args.assets) if args.assets else _config_path(args).resolve().parent / "assets.json"
    try:
        cfg = render.load_config(cfg_path)
        variants = args.variant or sorted(cfg.get("variants", {}))
        failed_any = False
        out_dir = Path(args.out) if args.out else cfg["_root"] / "assets-out"
        for name in variants:
            result = render.render_variant(cfg, name, out_dir, locales=args.locales.split(",") if args.locales else None,
                                           lint=not args.no_lint, strict_lint=args.strict_lint)
            print(f"{name}: {len(result['written'])} written → {out_dir / name}")
            for row in result["report"]:
                flags = [f for f, on in (("TIGHT", row["tight"]), ("fallback-headline", row["fallback"])) if on]
                if flags:
                    print(f"  {row['locale']:<8} verb {row['verb_px']}px×{row['verb_lines']}  desc {row['descriptor_px']}px×"
                          f"{row['descriptor_lines']}  device {row['device_width_pct']}%  {' '.join(flags)}")
            for locale, reason in sorted(result["failed"].items()):
                print(f"  FAILED {locale}: {reason}")
                failed_any = True
            if result["unlinted"]:
                print(f"  unlinted (needs native review): {', '.join(result['unlinted'])}")
    except render.RenderError as error:
        sys.exit(str(error))
    if failed_any:
        sys.exit(1)


_SURFACE_LABELS = {library.HEADER: "header", library.SEARCH: "search"}


def cmd_assets_status(args):
    _, app_id = _require_app_id(args)
    bearer = _bearer()
    catalog = library.Catalog.fetch(bearer)
    if args.catalog:
        print("\n".join(catalog.summary()))
        return
    lib = library.library_id(app_id, bearer)
    images = asc.call_all("GET", f"/appAssetLibraries/{lib}/images?limit=200", bearer)
    counts = {}
    for row in images:
        key = (row["attributes"].get("category"), row["attributes"].get("state"))
        counts[key] = counts.get(key, 0) + 1
    print(f"asset library {lib}: {len(images)} images")
    for (category, state), n in sorted(counts.items()):
        print(f"  {category:<30} {state:<24} {n}")
    version = asc.editable_version(app_id, bearer)
    if not version:
        print("no editable App Store version")
    else:
        print(f"editable version {version['attributes']['versionString']} ({version['attributes']['appStoreState']}):")
        for locale, loc_id in sorted(asc._localizations(version["id"], bearer).items()):
            rows = [p for p in library.surface_placements("appStoreVersionLocalization", loc_id, bearer)
                    if p["type"] in (library.HEADER, library.SEARCH)]
            print(f"  {locale:<8} {_placement_line(rows)}")
    for row in cpp_apply.list_pages(app_id, bearer):
        snap = cpp_apply.snapshot_page(row, bearer)
        page_version = snap["version"] or {}
        print(f"custom product page '{snap['name']}' ({page_version.get('state', 'no version')}):")
        for locale, loc in sorted((page_version.get("localizations") or {}).items()):
            rows = [p for p in loc["placements"] if p["type"] in (library.HEADER, library.SEARCH)]
            print(f"  {locale:<8} {_placement_line(rows)}")


def _placement_line(rows):
    return ", ".join(f"{_SURFACE_LABELS[p['type']]}:{p['state']}" for p in rows) or "(no header/search assets)"


def _default_target(app_id, bearer):
    version = asc.editable_version(app_id, bearer)
    if not version or version["attributes"]["appStoreState"] not in library.VERSION_PLACEABLE:
        sys.exit("no App Store version in Prepare for Submission — create the next version in App Store Connect first; "
                 "default-page creatives ride with it")
    running = library.active_experiment(app_id, bearer)
    if running:
        sys.exit(f"product page optimization test '{running}' is in review or running — placements on the default page "
                 "are blocked while it runs; stop it or wait")
    return "appStoreVersionLocalization", asc._localizations(version["id"], bearer), "APP_STORE_VERSIONS"


def _creative_plan(args):
    plan = _locales_filter(creative.plan_from_directory(args.directory), args.locales)
    problems = creative.check(plan)
    if problems:
        print("validation failed — nothing sent:")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)
    if not plan:
        sys.exit(f"no <locale>.png files in {args.directory}")
    return plan


def _resolve_target(args, app_id, bearer):
    if args.target == "default":
        return _default_target(app_id, bearer)
    if args.target.startswith("cpp:"):
        name = args.target[4:]
        row = next((r for r in cpp_apply.list_pages(app_id, bearer) if (r.get("attributes") or {}).get("name") == name), None)
        if row is None:
            sys.exit(f"no custom product page named '{name}' — run `asokit cpp push` first")
        snap = cpp_apply.snapshot_page(row, bearer, with_media=False)
        version = snap["version"]
        if version is None or version["state"] not in cpp.EDITABLE:
            sys.exit(f"'{name}' has no editable version ({version and version['state']}) — run `asokit cpp push` first; "
                     "assets push never creates page versions")
        parents = {locale: loc["id"] for locale, loc in version["localizations"].items()}
        return "appCustomProductPageLocalization", parents, cpp_apply.FEATURE
    sys.exit(f"unknown target '{args.target}' — use 'default' or 'cpp:<page name>'")


def cmd_assets_push(args):
    _, app_id = _require_app_id(args)
    plan = _creative_plan(args)
    bearer = _bearer()
    parent_kind, parents, feature = _resolve_target(args, app_id, bearer)
    missing = sorted(set(plan) - set(parents))
    if missing:
        sys.exit(f"no localization on the target for: {', '.join(missing)} — nothing sent")
    catalog = library.Catalog.fetch(bearer)
    lib = library.library_id(app_id, bearer)
    requests = [{"locale": locale, "parent_kind": parent_kind, "parent_id": parents[locale],
                 "placement_types": [library.HEADER, library.SEARCH], "category": library.CREATIVE,
                 "files": [(path.name, path.read_bytes())]} for locale, path in sorted(plan.items())]
    book = ledger_module.for_config(_config_path(args), args.apply)
    try:
        actions = library.sync_groups(requests, catalog, feature, lib, bearer, args.apply, ledger=book,
                                      command="assets push", progress=lambda a: _print_actions([a]))
    except asc.ASCError as error:
        print(f"\naborted — {error}\nRe-running is safe: uploads are reused and unchanged groups are skipped.", flush=True)
        sys.exit(1)
    unsupported = [a for a in actions if a["mode"] == "unsupported"]
    if unsupported:
        print(f"note: {len(unsupported)} placement(s) skipped — the catalog has no such type under {feature}")
    print("\napplied — verify in App Store Connect." if args.apply else "\nDRY RUN — nothing written. Re-run with --apply to push.")


def cmd_assets_submit(args):
    _, app_id = _require_app_id(args)
    plan = _creative_plan(args)
    bearer = _bearer()
    # Read-only guard before any upload (and the up-to-15-minute wait):
    # submit() re-checks item by item, but a doomed run should cost nothing.
    try:
        review.preflight(app_id, bearer, {"appAssetLibraryImage"})
    except review.SubmissionBlocked as error:
        sys.exit(str(error))
    lib = library.library_id(app_id, bearer)
    uploader = library.Uploader(lib, bearer, args.apply)
    assets = {locale: uploader.ensure(path.name, path.read_bytes(), library.CREATIVE) for locale, path in sorted(plan.items())}
    # Every asset without a specId — fresh uploads and reused UPLOAD_COMPLETE
    # rows alike — must finish processing first (mirrors library.sync_groups).
    unprocessed = sorted({a["asset"] for a in assets.values() if not a.get("specId")})
    if args.apply and unprocessed:
        states = library.wait_processed(lib, unprocessed, bearer)
        bad = {i: s for i, s in states.items() if s.get("state") not in library.PROCESSED}
        if bad:
            details = ", ".join(f"{i}: {s.get('state')}" for i, s in sorted(bad.items()))
            sys.exit(f"Apple did not accept {len(bad)} upload(s): {details} — nothing submitted")
        for a in assets.values():
            if a["asset"] in states:
                a["state"] = states[a["asset"]]["state"]
    items = []
    for locale, a in assets.items():
        if a.get("state") in library.IN_OR_PAST_REVIEW:
            print(f"  {locale:<8} {a['name']:<24} skipped — already {a['state']}")
            continue
        print(f"  {locale:<8} {a['name']:<24} {a['status']}")
        items.append(("appAssetLibraryImage", "appAssetLibraryImages", a["asset"]))
    items = list(dict.fromkeys(items))
    if not items:
        print("nothing to submit — every creative is already in or past review.")
        return
    book = ledger_module.for_config(_config_path(args), args.apply)
    try:
        result = review.submit(app_id, items, bearer, args.apply, ledger=book, command="assets submit")
    except review.SubmissionBlocked as error:
        sys.exit(str(error))
    print(f"submission {result['submission']}: +{len(result['add'])} item(s)")
    print("submitted for review." if result["submitted"] else "\nDRY RUN — nothing written. Re-run with --apply to submit.")


ADS_FIELDS = ["page_name", "page_id", "page_url", "visible", "latest_state", "locale", "keywords", "deep_link"]


def _cpp_path(args):
    return Path(args.file) if args.file else _config_path(args).resolve().parent / "cpp.json"


def _cpp_doc(args):
    path = _cpp_path(args)
    if not path.exists():
        sys.exit(f"no {path} — see the README for the cpp.json format")
    try:
        return cpp.load(path)
    except ValueError as error:  # malformed JSON (CppError is a ValueError too)
        sys.exit(f"{path}: {error}")


def _expand(doc):
    try:
        return cpp.expand(doc)
    except cpp.CppError as error:
        sys.exit(f"cpp.json: {error}")


def _write_ads(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ADS_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"ads export → {path} ({len(rows)} rows)")


def _pages_arg(args, required):
    names = [n.strip() for n in (args.pages or "").split(",") if n.strip()]
    if required and not names:
        sys.exit("--pages is required (comma-separated page names) — this command never acts on every page at once")
    return names or None


def _csv_list(value):
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _report(problems, warnings):
    for warning in warnings:
        print(f"  warning: {warning}")
    if problems:
        print("validation failed — nothing sent:")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)


def cmd_cpp_check(args):
    doc = _cpp_doc(args)
    online = None
    if not args.offline:
        _, app_id = _require_app_id(args)
        bearer = _bearer()
        online = cpp_apply.online_context(app_id, doc, bearer, library.Catalog.fetch(bearer))
    problems, warnings = cpp.check(doc, args.creative_root, _csv_list(args.allow_protected), not args.no_lint, online=online)
    _report(problems, warnings)
    print(f"ok — {len(_expand(doc))} page(s) valid{' (offline: keyword pools not checked)' if args.offline else ''}")


def cmd_cpp_status(args):
    _, app_id = _require_app_id(args)
    bearer = _bearer()
    book = ledger_module.for_config(_config_path(args), True)
    snapshots = {}
    for row in cpp_apply.list_pages(app_id, bearer):
        snap = cpp_apply.snapshot_page(row, bearer, with_media=False)
        snapshots[snap["name"]] = snap
        version = snap["version"] or {}
        print(f"{snap['name']}  id {snap['id']}  {'visible' if snap['visible'] else 'hidden'}  {version.get('state', '(no version)')}"
              f"  published {book.last('publish', page_id=snap['id']) or '-'}")
        for locale, loc in sorted((version.get("localizations") or {}).items()):
            print(f"  {locale:<8} {', '.join(sorted(loc['keywords'])) or '(no keywords)'}")
    if not snapshots:
        print("no custom product pages")
    if args.ads_export:
        pages = _expand(_cpp_doc(args)) if _cpp_path(args).exists() else []
        _write_ads(args.ads_export, cpp.ads_rows(pages, snapshots))


def cmd_cpp_push(args):
    doc = _cpp_doc(args)
    _, app_id = _require_app_id(args)
    bearer = _bearer()
    book = ledger_module.for_config(_config_path(args), args.apply)
    try:
        result = cpp_apply.push(app_id, doc, bearer, args.apply, creative_root=args.creative_root,
                                pages=_pages_arg(args, required=False), locales=_csv_list(args.locales) or None,
                                prune=args.prune, allow_protected=_csv_list(args.allow_protected),
                                lint=not args.no_lint, ledger=book, out=print)
    except asc.ASCError as error:
        print(f"\naborted — {error}\nRe-running is safe: every step re-diffs against live state.", flush=True)
        sys.exit(1)
    _report(result["problems"], result["warnings"])
    if args.ads_export:
        _write_ads(args.ads_export, cpp.ads_rows(_expand(doc), result["context"]["snapshots"]))
    if not result["actions"]:
        print("no changes — App Store Connect already matches cpp.json")
    print("\napplied — pages stay hidden until `asokit cpp publish`." if args.apply
          else "\nDRY RUN — nothing written. Re-run with --apply to push.")


def cmd_cpp_publish(args):
    names = _pages_arg(args, required=True)
    _, app_id = _require_app_id(args)
    book = ledger_module.for_config(_config_path(args), args.apply)
    try:
        cpp_apply.publish(app_id, names, _bearer(), args.apply, hide=args.hide, ledger=book)
    except asc.ASCError as error:
        sys.exit(str(error))
    print("applied." if args.apply else "\nDRY RUN — nothing written. Re-run with --apply.")


def cmd_cpp_submit(args):
    names = _pages_arg(args, required=True)
    doc = _cpp_doc(args)
    _, app_id = _require_app_id(args)
    book = ledger_module.for_config(_config_path(args), args.apply)
    try:
        result = cpp_apply.submit(app_id, doc, names, _bearer(), args.apply, ledger=book)
    except asc.ASCError as error:
        sys.exit(str(error))
    print(f"submission {result['submission']}: +{len(result['add'])} item(s), {len(result['existing'])} already in it")
    print("submitted for review." if result["submitted"] else "\nDRY RUN — nothing written. Re-run with --apply to submit.")


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
    doctor.add_argument("--app-id", help="override the configured appId for the territory check")
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
    research_command.add_argument(
        "--out", help="output directory; with --all, the parent of the per-market directories"
    )
    research_command.add_argument(
        "--resume",
        action="store_true",
        help="skip markets that already have scores, to continue an interrupted --all run",
    )
    research_command.add_argument("--no-cache", action="store_true")
    research_command.set_defaults(func=cmd_research)

    metadata_command = subcommands.add_parser("metadata", help="validate and sync metadata")
    metadata_sub = metadata_command.add_subparsers(dest="metadata_command", required=True)

    check = metadata_sub.add_parser("check", help="validate limits and duplication")
    check.add_argument("file")
    check.add_argument(
        "--strict", action="store_true", help="also require release notes on every locale"
    )
    check.add_argument(
        "--allow-partial",
        action="store_true",
        help="skip submission-completeness rules, for updating a subset of fields",
    )
    check.set_defaults(func=cmd_metadata_check)

    status = metadata_sub.add_parser("status", help="what App Store Connect will accept")
    status.add_argument("--app-id")
    status.set_defaults(func=cmd_metadata_status)

    suggest_field = metadata_sub.add_parser(
        "suggest", help="pack researched candidates into a keyword field"
    )
    suggest_field.add_argument("--market", help="country code from your config")
    suggest_field.add_argument("--all", action="store_true", help="every configured market")
    suggest_field.add_argument(
        "--baseline", help="metadata pull output: supplies name, subtitle and live keywords"
    )
    suggest_field.add_argument("--name", help="override the name used for deduplication")
    suggest_field.add_argument("--subtitle", help="override the subtitle used for deduplication")
    suggest_field.add_argument(
        "--block", help="comma-separated words to drop that no rule catches"
    )
    suggest_field.add_argument("--limit", type=int, default=meta.LIMITS["keywords"])
    suggest_field.add_argument("--dir", help="where research wrote its output")
    suggest_field.add_argument(
        "--json", action="store_true", help="emit {locale: {keywords}} instead of a report"
    )
    suggest_field.add_argument("--out", help="with --json, write here instead of stdout")
    suggest_field.set_defaults(func=cmd_metadata_suggest)

    pull = metadata_sub.add_parser(
        "pull", help="write the live listing as JSON (the baseline to roll back to)"
    )
    pull.add_argument("--app-id")
    pull.add_argument("--out", help="write here instead of stdout")
    pull.set_defaults(func=cmd_metadata_pull)

    push = metadata_sub.add_parser("push", help="sync metadata (dry run unless --apply)")
    push.add_argument("file")
    push.add_argument("--app-id")
    push.add_argument("--apply", action="store_true")
    push.add_argument(
        "--allow-partial",
        action="store_true",
        help="push locales whose description is already live and absent from the file",
    )
    push.set_defaults(func=cmd_metadata_push)

    products_command = subcommands.add_parser(
        "products", help="validate and sync IAP/subscription text"
    )
    products_sub = products_command.add_subparsers(dest="products_command", required=True)

    products_check = products_sub.add_parser("check", help="validate product text limits")
    products_check.add_argument("file")
    products_check.set_defaults(func=cmd_products_check)

    products_status = products_sub.add_parser(
        "status", help="list products and existing localizations"
    )
    products_status.add_argument("--app-id")
    products_status.add_argument("--json", action="store_true", help="also dump raw JSON")
    products_status.set_defaults(func=cmd_products_status)

    products_push = products_sub.add_parser(
        "push", help="sync product text (dry run unless --apply)"
    )
    products_push.add_argument("file")
    products_push.add_argument("--app-id")
    products_push.add_argument("--apply", action="store_true")
    products_push.set_defaults(func=cmd_products_push)

    products_apply = products_sub.add_parser(
        "apply", help="provision groups, subscriptions, prices (dry run unless --apply)"
    )
    products_apply.add_argument("file")
    products_apply.add_argument("--app-id")
    products_apply.add_argument("--apply", action="store_true")
    products_apply.add_argument(
        "--verbose", action="store_true", help="list every territory instead of a count"
    )
    products_apply.set_defaults(func=cmd_products_apply)

    screenshots_command = subcommands.add_parser("screenshots", help="inspect and replace App Store screenshots")
    screenshots_sub = screenshots_command.add_subparsers(dest="screenshots_command", required=True)
    screenshots_status = screenshots_sub.add_parser("status", help="screenshot sets per locale on the editable version")
    screenshots_status.add_argument("--app-id")
    screenshots_status.set_defaults(func=cmd_screenshots_status)
    screenshots_push = screenshots_sub.add_parser("push", help="replace screenshot sets from DIR/<locale>/*.png (dry run unless --apply)")
    screenshots_push.add_argument("directory")
    screenshots_push.add_argument("--display", default="APP_IPHONE_67", help="display family for DIR's PNGs (default APP_IPHONE_67)")
    screenshots_push.add_argument("--locales", help="comma-separated subset of locale folders")
    screenshots_push.add_argument("--mirror", help="comma-separated display types to copy from --mirror-from into every other locale (e.g. iPad + Watch sets)")
    screenshots_push.add_argument("--mirror-from", default="en-US")
    screenshots_push.add_argument("--app-id")
    screenshots_push.add_argument("--apply", action="store_true")
    screenshots_push.set_defaults(func=cmd_screenshots_push)

    assets_command = subcommands.add_parser("assets", help="App Store creatives: header and search results assets")
    assets_sub = assets_command.add_subparsers(dest="assets_command", required=True)
    assets_render = assets_sub.add_parser("render", help="render creatives from assets.json (needs the 'render' extra)")
    assets_render.add_argument("--assets", help="path to assets.json (default: next to the config)")
    assets_render.add_argument("--variant", action="append", help="variant to render (repeatable; default: all)")
    assets_render.add_argument("--locales", help="comma-separated subset")
    assets_render.add_argument("--out", help="output directory (default: assets-out next to assets.json)")
    assets_render.add_argument("--no-lint", action="store_true", help="skip the App Store rejection lint")
    assets_render.add_argument("--strict-lint", action="store_true", help="fail locales whose language has no lint list")
    assets_render.set_defaults(func=cmd_assets_render)
    assets_status = assets_sub.add_parser("status", help="library, asset states and header/search placements")
    assets_status.add_argument("--app-id")
    assets_status.add_argument("--catalog", action="store_true", help="dump Apple's placement/spec catalog instead")
    assets_status.set_defaults(func=cmd_assets_status)
    assets_push = assets_sub.add_parser("push", help="place DIR/<locale>.png as header + search asset (dry run unless --apply)")
    assets_push.add_argument("directory")
    assets_push.add_argument("--target", required=True, help="'default' or 'cpp:<page name>'")
    assets_push.add_argument("--locales")
    assets_push.add_argument("--app-id")
    assets_push.add_argument("--apply", action="store_true")
    assets_push.set_defaults(func=cmd_assets_push)
    assets_submit = assets_sub.add_parser("submit", help="send DIR/<locale>.png to App Review on their own, placing nothing")
    assets_submit.add_argument("directory")
    assets_submit.add_argument("--locales")
    assets_submit.add_argument("--app-id")
    assets_submit.add_argument("--apply", action="store_true")
    assets_submit.set_defaults(func=cmd_assets_submit)

    cpp_command = subcommands.add_parser("cpp", help="custom product pages from cpp.json")
    cpp_sub = cpp_command.add_subparsers(dest="cpp_command", required=True)

    def cpp_common(sub, apply=False):
        sub.add_argument("--file", help="path to cpp.json (default: next to the config)")
        sub.add_argument("--app-id")
        if apply:
            sub.add_argument("--apply", action="store_true")

    cpp_check = cpp_sub.add_parser("check", help="validate cpp.json (online unless --offline)")
    cpp_common(cpp_check)
    cpp_check.add_argument("--offline", action="store_true")
    cpp_check.add_argument("--allow-protected", help="comma-separated protected keywords to allow")
    cpp_check.add_argument("--creative-root", default="assets-out")
    cpp_check.add_argument("--no-lint", action="store_true")
    cpp_check.set_defaults(func=cmd_cpp_check)

    cpp_status = cpp_sub.add_parser("status", help="live pages, versions, visibility and keywords")
    cpp_common(cpp_status)
    cpp_status.add_argument("--ads-export", help="write page/keyword CSV for Apple Ads ad groups")
    cpp_status.set_defaults(func=cmd_cpp_status)

    cpp_push = cpp_sub.add_parser("push", help="converge App Store Connect to cpp.json (dry run unless --apply)")
    cpp_common(cpp_push, apply=True)
    cpp_push.add_argument("--pages", help="comma-separated page names (default: all in the file)")
    cpp_push.add_argument("--locales", help="comma-separated locales; never deletes outside them")
    cpp_push.add_argument("--prune", action="store_true", help="delete page localizations missing from the file")
    cpp_push.add_argument("--allow-protected")
    cpp_push.add_argument("--creative-root", default="assets-out")
    cpp_push.add_argument("--no-lint", action="store_true")
    cpp_push.add_argument("--ads-export")
    cpp_push.set_defaults(func=cmd_cpp_push)

    cpp_publish = cpp_sub.add_parser("publish", help="make approved pages visible — organic routing goes live")
    cpp_common(cpp_publish, apply=True)
    cpp_publish.add_argument("--pages", help="comma-separated page names (required)")
    cpp_publish.add_argument("--hide", action="store_true", help="hide instead of publish")
    cpp_publish.set_defaults(func=cmd_cpp_publish)

    cpp_submit = cpp_sub.add_parser("submit", help="send page versions to App Review")
    cpp_common(cpp_submit, apply=True)
    cpp_submit.add_argument("--pages", help="comma-separated page names (required)")
    cpp_submit.set_defaults(func=cmd_cpp_submit)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (asc.ASCError, prod.PlanError, storefronts.UnknownStorefront) as error:
        sys.exit(str(error))
    except KeyboardInterrupt:
        sys.exit("\ninterrupted — cached results were kept")


if __name__ == "__main__":
    main()
