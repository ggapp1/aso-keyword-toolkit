import unittest
from pathlib import Path

from asokit import cli


class Args:
    def __init__(self, out=None, all=False):
        self.out = out
        self.all = all


class OutputDirectory(unittest.TestCase):
    CONFIG = {"app": {"outputDir": "aso"}}

    def test_defaults_to_a_per_market_directory_under_the_configured_root(self):
        self.assertEqual(cli.output_dir(self.CONFIG, "de", Args()), Path("aso/de"))

    def test_falls_back_to_aso_when_no_output_dir_is_configured(self):
        self.assertEqual(cli.output_dir({}, "de", Args()), Path("aso/de"))

    def test_out_is_the_directory_itself_for_a_single_market(self):
        self.assertEqual(
            cli.output_dir(self.CONFIG, "de", Args(out="somewhere")), Path("somewhere")
        )

    def test_out_is_the_parent_with_all(self):
        """--out used to be rejected outright, which was a surprise mid-plan."""
        self.assertEqual(
            cli.output_dir(self.CONFIG, "de", Args(out="somewhere", all=True)),
            Path("somewhere/de"),
        )

    def test_each_market_gets_its_own_directory_under_the_parent(self):
        args = Args(out="/tmp/run", all=True)
        dirs = [cli.output_dir(self.CONFIG, market, args) for market in ("de", "fr")]
        self.assertEqual(dirs, [Path("/tmp/run/de"), Path("/tmp/run/fr")])


if __name__ == "__main__":
    unittest.main()
