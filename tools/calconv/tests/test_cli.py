# calconv - ECM calibration converter for EcmDroid
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 3
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, see <http://www.gnu.org/licenses/>.
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from calconvlib.cli import EXIT_DIFFERENT, EXIT_ERROR, EXIT_OK, main
from calconvlib.rules import RULES_DIR as RULES

from .support import BUE2D_IMAGE, BUEIB_IMAGE


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(map(str, argv)))
    return code, out.getvalue(), err.getvalue()


class TestCommands(unittest.TestCase):
    def test_layouts(self):
        code, out, _ = run("layouts")
        self.assertEqual(EXIT_OK, code)
        self.assertIn("| BUE2D, B3R2D | DDFI-3 | 3796 | 3756 | 40 |", out)
        self.assertIn("1206 bytes:", out)

    def test_plan_json(self):
        code, out, _ = run("plan", "--from", "BUE2D", "--to", "BUEYD", "--format", "json")
        self.assertEqual(EXIT_OK, code)
        data = json.loads(out)
        self.assertEqual(492, data["counts"]["copyable"])
        self.assertEqual(["Tab_Idle_Spark"], list(data["semantic_warnings"]))

    def test_plan_markdown(self):
        code, out, _ = run("plan", "--from", "BUE2D", "--to", "BUEYD")
        self.assertEqual(EXIT_OK, code)
        self.assertIn("# Conversion plan: BUE2D → BUEYD", out)
        self.assertIn("Meaning may depend on the firmware", out)

    def test_info_hides_private_data(self):
        code, out, _ = run("info", BUE2D_IMAGE)
        self.assertEqual(EXIT_OK, code)
        self.assertIn("M39EC322", out)
        self.assertIn("(hidden, use --show-private)", out)
        code, out, _ = run("info", BUE2D_IMAGE, "--show-private", "--format", "json")
        self.assertNotIn("hidden", json.loads(out)["private"]["KVIN"])

    def test_info_ambiguous_size(self):
        code, _, err = run("info", BUEIB_IMAGE)
        self.assertEqual(EXIT_ERROR, code)
        self.assertIn("several layouts", err)
        code, out, _ = run("info", BUEIB_IMAGE, "--id", "BUEIB")
        self.assertEqual(EXIT_OK, code)
        self.assertIn("2006-06-08", out)

    def test_diff_exit_codes(self):
        code, out, _ = run("diff", BUE2D_IMAGE, BUE2D_IMAGE)
        self.assertEqual(EXIT_OK, code)
        self.assertIn("The images are identical", out)
        with tempfile.TemporaryDirectory() as tmp:
            changed = Path(tmp) / "changed.xpr"
            data = bytearray(BUE2D_IMAGE.read_bytes())
            data[100] ^= 0xFF
            changed.write_bytes(data)
            code, out, _ = run("diff", BUE2D_IMAGE, changed)
            self.assertEqual(EXIT_DIFFERENT, code)
            report = Path(tmp) / "report.json"
            code, _, _ = run("diff", BUE2D_IMAGE, changed, "--format", "json", "-o", report)
            self.assertEqual(EXIT_DIFFERENT, code)
            self.assertFalse(json.loads(report.read_text())["identical"])

    def test_plan_shows_the_rule_file(self):
        code, out, _ = run("plan", "--from", "BUE2D", "--to", "BUEYD")
        self.assertIn("## Rule file", out)
        self.assertIn("copy_elements Tab_PRF", out)
        code, out, _ = run("plan", "--from", "BUE2D", "--to", "BUEYD", "--no-pair-rules")
        self.assertNotIn("## Rule file", out)

    def test_convert_with_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target.xpr"
            target.write_bytes(BUE2D_IMAGE.read_bytes())
            out = Path(tmp) / "out.xpr"
            code, text, _ = run("convert", "--source", BUE2D_IMAGE, "--target", target, "--out", out,
                                "--pair-rules", RULES / "BUE2D-BUEYD.toml")
            self.assertEqual(EXIT_ERROR, code)  # BUE2D onto BUE2D: the rules are for BUEYD
            code, text, err = run("convert", "--source", BUE2D_IMAGE, "--target", target, "--out", out,
                                  "--allow-proposed", "--format", "json")
            self.assertEqual(EXIT_OK, code, err)
            self.assertIsNone(json.loads(text)["rule_file"])  # no BUE2D-BUE2D.toml
            self.assertIn("in testing", json.loads(text)["testing_note"])
            self.assertIn("Don't burn the result", err)

    def test_convert_report_hides_private_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target.xpr"
            data = bytearray(BUE2D_IMAGE.read_bytes())
            data[-30] ^= 0x01  # page 0 differs, so the VIN is listed
            target.write_bytes(data)
            out = Path(tmp) / "out.xpr"
            code, text, err = run("convert", "--source", BUE2D_IMAGE, "--target", target, "--out", out,
                                  "--format", "json", "--all")
            self.assertEqual(EXIT_OK, code, err)
            kvin = [a for a in json.loads(text)["actions"] if a["name"] == "KVIN"][0]
            self.assertEqual("(hidden, use --show-private)", kvin["before"])
            code, text, err = run("convert", "--source", BUE2D_IMAGE, "--target", target, "--out", out,
                                  "--force", "--all")
            self.assertEqual(EXIT_OK, code, err)
            self.assertIn("Verified:", text)
            self.assertIn("> **calconv is in testing", text)
            self.assertIn("Don't burn it yet.", text)
            self.assertIn("| KVIN |  | page 0 | (hidden, use --show-private) |", text)

    def test_show(self):
        code, out, _ = run("show", "Tab_PRF", "KVIN", "--id", "BUEYD", "--image", BUE2D_IMAGE)
        self.assertEqual(EXIT_OK, code)
        self.assertIn("- **BUEYD**: Array; offset 450; 4 bytes", out)
        self.assertIn("rich transition (idle, low, mid, high)", out)
        self.assertIn("| BUE2D | 10.0, 1.0, 1.0, 1.0, 1.0 |", out)
        self.assertIn("(hidden, use --show-private)", out)
        code, out, _ = run("show", "KVIN", "--image", f"{BUEIB_IMAGE}@BUEIB")
        self.assertEqual(EXIT_OK, code)
        code, _, err = run("show", "KVIN")
        self.assertEqual(EXIT_ERROR, code)

    def test_draft_rules(self):
        code, out, _ = run("draft-rules", "--from", "BUEIB", "--to", "BUECB")
        self.assertEqual(EXIT_OK, code)
        self.assertIn('[pair]\nfrom = "BUEIB"\nto = "BUECB"', out)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "BUEIB-BUECB.toml"
            path.write_text("keep")
            code, _, err = run("draft-rules", "--from", "BUEIB", "--to", "BUECB", "-o", path)
            self.assertEqual(EXIT_ERROR, code)
            self.assertIn("--force", err)
            self.assertEqual("keep", path.read_text())

    def test_unknown_id(self):
        code, _, err = run("plan", "--from", "BUE2D", "--to", "NOPE")
        self.assertEqual(EXIT_ERROR, code)
        self.assertIn("unknown ECM ID", err)


if __name__ == "__main__":
    unittest.main()
