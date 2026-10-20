# egotune - narrowband fuel-map tuning for EcmDroid
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

from tests.support import BUE2D_IMAGE, BUE2D_LOG, BUEIB_IMAGE, BUEIB_LOG, log_bytes, ride

from egotunelib.cli import main

NEIGHBOURS = ((3400, 30), (2900, 30), (3400, 25))


def healthy(seconds=6 * 60, ecm_id="BUE2D"):
    """Passes every check; the rear cell at 3400 rpm / load 30 (45) reads 6 % lean."""
    return log_bytes(ride(seconds, NEIGHBOURS, ego=lambda i: 106.0 if i < 600 else 100.0), ecm_id=ecm_id)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.log = self.dir / "ride.bin"
        self.log.write_bytes(healthy())

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([str(a) for a in argv])
        return code, out.getvalue(), err.getvalue()

    def test_analyse_markdown(self):
        code, out, _ = self.call("analyse", "--image", BUE2D_IMAGE, self.log)
        self.assertEqual(code, 0)
        self.assertIn("# Fuel-map corrections: BUE2D", out)
        self.assertIn("## Checks", out)
        self.assertIn("**46** (45)", out)
        self.assertIn("No --baseline given", out)

    def test_analyse_json(self):
        code, out, _ = self.call("analyse", "--format", "json", "--image", BUE2D_IMAGE, self.log)
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertEqual(doc["ecm_id"], "BUE2D")
        self.assertEqual(doc["changes"]["rear"][0]["new"], 46)
        self.assertTrue(all(c["passed"] for c in doc["checks"]))

    def test_apply_writes_image(self):
        result = self.dir / "iter1.xpr"
        code, out, err = self.call("apply", "--image", BUE2D_IMAGE, self.log, "--out", result)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(result.read_bytes()), len(BUE2D_IMAGE.read_bytes()))
        self.assertIn("in testing", err)
        code, _, err = self.call("apply", "--image", BUE2D_IMAGE, self.log, "--out", result)
        self.assertEqual(code, 2)
        self.assertIn("--force", err)

    def test_failed_check_blocks_apply(self):
        self.log.write_bytes(healthy(2 * 60))  # too short
        result = self.dir / "iter1.xpr"
        code, out, err = self.call("apply", "--image", BUE2D_IMAGE, self.log, "--out", result)
        self.assertEqual(code, 1)
        self.assertIn("short-log", err)
        self.assertIn("Not applied", out)
        self.assertFalse(result.exists())
        code, out, err = self.call("analyse", "--image", BUE2D_IMAGE, self.log)
        self.assertEqual(code, 1)  # analyse reports, and says so in its exit code

    def test_accept_overrides_a_check(self):
        self.log.write_bytes(healthy(2 * 60))
        result = self.dir / "iter1.xpr"
        code, out, err = self.call("apply", "--image", BUE2D_IMAGE, self.log, "--out", result,
                                   "--accept", "short-log")
        self.assertEqual(code, 0, err)
        self.assertTrue(result.exists())
        self.assertIn("Overridden with --accept: short-log", out)

    def test_unknown_check_name(self):
        with self.assertRaises(SystemExit):
            self.call("analyse", "--image", BUE2D_IMAGE, self.log, "--accept", "everything")

    def test_apply_refuses_to_overwrite_input(self):
        copy = self.dir / "ecm.xpr"
        copy.write_bytes(BUE2D_IMAGE.read_bytes())
        code, _, err = self.call("apply", "--image", copy, self.log, "--out", copy, "--force")
        self.assertEqual(code, 2)
        self.assertIn("overwrite an input", err)

    def test_apply_without_usable_data(self):
        code, _, err = self.call("apply", "--image", BUE2D_IMAGE, BUE2D_LOG, "--out", self.dir / "x.xpr")
        self.assertEqual(code, 2)
        self.assertIn("no usable data", err)
        self.assertFalse((self.dir / "x.xpr").exists())

    def test_real_ddfi2_ride_with_baseline(self):
        result = self.dir / "iter1.epr"
        code, out, err = self.call("apply", "--image", BUEIB_IMAGE, "--baseline", BUEIB_IMAGE, BUEIB_LOG,
                                   "--out", result)
        self.assertEqual(code, 0, err)
        self.assertNotIn("No --baseline", out)
        self.assertNotIn("FAIL", out)
        self.assertEqual(len(result.read_bytes()), len(BUEIB_IMAGE.read_bytes()))

    def test_unknown_log_id_needs_id(self):
        self.log.write_bytes(healthy(ecm_id="UNKWN"))
        code, _, err = self.call("analyse", "--image", BUE2D_IMAGE, self.log)
        self.assertEqual(code, 2)
        self.assertIn("--id", err)
        code, _, _ = self.call("analyse", "--id", "BUE2D", "--image", BUE2D_IMAGE, self.log)
        self.assertEqual(code, 0)

    def test_layout_mismatch(self):
        self.log.write_bytes(healthy(ecm_id="BUEYD"))
        code, _, err = self.call("analyse", "--image", BUE2D_IMAGE, self.log)
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
