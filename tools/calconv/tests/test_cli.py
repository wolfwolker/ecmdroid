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

    def test_unknown_id(self):
        code, _, err = run("plan", "--from", "BUE2D", "--to", "NOPE")
        self.assertEqual(EXIT_ERROR, code)
        self.assertIn("unknown ECM ID", err)


if __name__ == "__main__":
    unittest.main()
