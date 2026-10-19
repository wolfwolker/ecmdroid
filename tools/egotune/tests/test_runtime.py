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

import unittest

from tests.support import BUE2D_LOG, defs, frame, log_bytes

from egotunelib.runtime import LogError, log_id, parse_log


class RuntimeTest(unittest.TestCase):
    def test_definitions(self):
        d = defs()
        self.assertEqual(d.frame_len, 135)
        self.assertEqual(d.channels["RPM"].offset, 11)
        self.assertEqual(d.channels["FBFuel1"].offset, 130)

    def test_parse_fixture_log(self):
        data = BUE2D_LOG.read_bytes()
        log = parse_log(data, defs().frame_len)
        self.assertEqual(log.ecm_id, "BUE2D")
        self.assertEqual(len(log.records), 2153)
        self.assertEqual(log.bad_checksum, 0)
        self.assertEqual(log.trailing_bytes, 0)
        self.assertAlmostEqual(log.records[0].time, 0.24)
        self.assertGreater(log.duration, 460)

    def test_bad_checksum_dropped(self):
        data = bytearray(log_bytes([frame(), frame(), frame()]))
        data[5 + 4 + 139 + 20] ^= 0xFF  # a byte inside the second frame
        log = parse_log(bytes(data), defs().frame_len)
        self.assertEqual(len(log.records), 2)
        self.assertEqual(log.bad_checksum, 1)

    def test_values(self):
        f = frame(RPM=2900, RLoad=42, FBFuel=104.5, TE=88.3)
        d = defs()
        self.assertEqual(d.value(f, "RPM"), 2900)
        self.assertEqual(d.value(f, "RLoad"), 42)
        self.assertAlmostEqual(d.value(f, "FBFuel"), 104.5)
        self.assertAlmostEqual(d.value(f, "TE"), 88.3)
        self.assertTrue(d.bit(f, "Flags2", 7))

    def test_short_file(self):
        with self.assertRaises(LogError):
            log_id(b"BUE")


if __name__ == "__main__":
    unittest.main()
