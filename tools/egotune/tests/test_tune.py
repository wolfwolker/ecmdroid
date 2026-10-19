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

from tests.support import BUE2D_LOG, COL_3400, ROW_30, defs, frame, image, make_log, steady

from egotunelib.analysis import Settings, analyse
from egotunelib.runtime import parse_log
from egotunelib.tune import BELOW_RESOLUTION, CAPPED, CHANGED, FEW_DATA, INACTIVE, build_image, propose_all


def wobble(seconds, mean, **values):
    """Closed-loop data whose front EGO correction moves around `mean`."""
    frames = []
    for i in range(round(seconds / 0.2)):
        frames.append(frame(FBFuel=mean, FBFuel1=mean + (-2, -1, 1, 2)[i % 4], **values))
    return frames


class TuneTest(unittest.TestCase):
    def run_tune(self, frames, settings=None):
        a = analyse(image(), defs(), [make_log(frames)], settings)
        return a, propose_all(a)

    def cell(self, fmap):
        return fmap.index(ROW_30, COL_3400)

    def test_lean_cell_gets_richer(self):
        a, ch = self.run_tune(wobble(20, 106))
        rear = a.cylinders["rear"]
        i = self.cell(rear.fuel_map)
        self.assertAlmostEqual(rear.cells[i].mean, 106.0)
        c = ch["rear"].cells[i]
        # 45 x (1 + 1/3 x 1.0 x 0.06) = 45.9
        self.assertEqual((c.old, c.new, c.state), (45, 46, CHANGED))
        self.assertEqual(len(ch["rear"].changed), 1)
        self.assertTrue(a.cylinders["front"].active)

    def test_lean_change_capped(self):
        a, ch = self.run_tune(wobble(20, 80))
        c = ch["rear"].cells[self.cell(a.cylinders["rear"].fuel_map)]
        # -6.7 % wanted, capped at -3 %: 45 x 0.97 = 43.65
        self.assertEqual((c.new, c.state), (44, CAPPED))

    def test_small_correction_below_resolution(self):
        a, ch = self.run_tune(wobble(20, 102))
        c = ch["rear"].cells[self.cell(a.cylinders["rear"].fuel_map)]
        self.assertEqual((c.new, c.state), (45, BELOW_RESOLUTION))

    def test_too_little_data(self):
        s = Settings(settle=0.0)
        a, ch = self.run_tune(wobble(1, 110), s)
        c = ch["rear"].cells[self.cell(a.cylinders["rear"].fuel_map)]
        self.assertEqual((c.new, c.state), (45, FEW_DATA))

    def test_confidence_scales_the_change(self):
        s = Settings(settle=0.0, min_seconds=1.0, full_seconds=10.0, max_rich=50)
        a, ch = self.run_tune(wobble(5, 130), s)  # 5 s: half the gain
        c = ch["rear"].cells[self.cell(a.cylinders["rear"].fuel_map)]
        # 45 x (1 + 1/3 x 0.5 x 0.30) = 47.25
        self.assertEqual(c.new, 47)

    def test_filters(self):
        frames = (steady(5, FBFuel=130, TE=50.0)  # cold
                  + steady(5, FBFuel=130, CrTE=104.0)  # warm-up enrichment
                  + steady(5, FBFuel=130, Flags2=0)  # open loop
                  + steady(5, FBFuel=130, Flags1=0b1001)  # deceleration
                  + wobble(20, 106))
        a, ch = self.run_tune(frames)
        for reason in ("cold engine", "warm-up enrichment", "open loop", "accel/decel enrichment", "transient"):
            self.assertGreater(a.excluded[reason], 0, reason)
        rear = a.cylinders["rear"]
        self.assertAlmostEqual(rear.cells[self.cell(rear.fuel_map)].mean, 106.0)

    def test_settle_after_transient(self):
        s = Settings(settle=1.0)
        frames = wobble(10, 106) + [frame(RPM=5000)] + wobble(10, 106)
        a, _ = self.run_tune(frames, s)
        self.assertEqual(a.excluded["transient"], 5 + 1 + 5)  # first second, the jump, and back

    def test_afv_is_part_of_the_correction(self):
        a, _ = self.run_tune([frame(FBFuel=100, LFuel_LD=105, FBFuel1=100 + i % 5) for i in range(100)])
        rear = a.cylinders["rear"]
        self.assertAlmostEqual(rear.cells[self.cell(rear.fuel_map)].mean, 105.0)
        self.assertTrue(any("AFV wasn't locked" in w for w in a.warnings))

    def test_front_without_feedback_unchanged(self):
        a, ch = self.run_tune(steady(20, FBFuel=110, FBFuel1=100))
        self.assertFalse(a.cylinders["front"].active)
        self.assertEqual(ch["front"].changed, [])
        self.assertTrue(all(c.state == INACTIVE for c in ch["front"].cells.values()))
        self.assertTrue(ch["rear"].changed)

    def test_front_copying_rear_unchanged(self):
        frames = [frame(FBFuel=100 + i % 7, FBFuel1=100 + i % 7) for i in range(100)]
        a, _ = self.run_tune(frames)
        self.assertFalse(a.cylinders["front"].active)
        self.assertIn("copy of the rear", a.cylinders["front"].inactive_reason)

    def test_saturation_flagged(self):
        a, ch = self.run_tune(wobble(20, 200))  # KFBFuel_Max in the test image
        rear = a.cylinders["rear"]
        i = self.cell(rear.fuel_map)
        self.assertEqual(rear.cells[i].saturation(0.2), "rich")
        self.assertEqual(ch["rear"].cells[i].saturated, "rich")

    def test_build_image_changes_only_the_maps(self):
        img = image()
        a, ch = self.run_tune(wobble(20, 106))
        out = build_image(img, ch)
        self.assertEqual(len(out), len(img.data))
        diffs = [i for i, (x, y) in enumerate(zip(img.data, out)) if x != y]
        cell = self.cell(a.cylinders["rear"].fuel_map)
        front, rear = img.start(img.var("Tab_Fuel_Front")), img.start(img.var("Tab_Fuel_Rear"))
        self.assertEqual(diffs, [front + cell, rear + cell])  # front EGO averages 106 % too
        self.assertEqual(out[rear + cell], 46)

    def test_cold_fixture_log_has_no_usable_data(self):
        log = parse_log(BUE2D_LOG.read_bytes(), defs().frame_len)
        a = analyse(image(), defs(), [log])
        self.assertEqual(a.used, 0)
        self.assertEqual(a.records, 2153)
        self.assertTrue(any("No record passed" in w for w in a.warnings))
        # This image wasn't in the ECM when the log was recorded: the stored AFV differs.
        self.assertTrue(any("Was this image in the ECM" in w for w in a.warnings))


if __name__ == "__main__":
    unittest.main()
