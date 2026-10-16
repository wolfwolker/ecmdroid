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
"""Conversion (phase 3). The repository has no real BUEYD image, so the
target is generated: random bytes, with the model-guard variable set to the
source's value. Real images in xprs/ (git-ignored) are used when present."""

import random
import unittest

from calconvlib.convert import COPIED, EQUAL, EXCLUDED, KEPT, LOST, TARGET_ONLY, ConversionError, convert
from calconvlib.db import REPO_ROOT
from calconvlib.diff import diff_images
from calconvlib.image import image_from_bytes, load_image

from .support import BUE2D_IMAGE, db, rules

XPRS = REPO_ROOT / "xprs"


def random_target(ecm_id, like, seed=1):
    """A random image of ecm_id whose model guard matches `like`."""
    lay = db().layout(ecm_id)
    data = bytearray(random.Random(seed).randbytes(lay.xsize))
    img = image_from_bytes(db(), bytes(data), ecm_id)
    for name in rules().model_guard:
        v, s = img.var(name), like.var(name)
        if v and s:
            data[img.start(v):img.start(v) + v.size] = like.raw(s)
    return image_from_bytes(db(), bytes(data), ecm_id)


class TestBUE2DToBUEYD(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = load_image(db(), BUE2D_IMAGE)
        cls.target = random_target("BUEYD", cls.source)
        cls.c = convert(db(), cls.source, cls.target, rules())

    def test_verified(self):
        self.assertEqual([], self.c.problems)
        self.assertEqual(3272, len(self.c.result.data))
        self.assertEqual("BUEYD", self.c.result.ecm_id)

    def test_counts(self):
        copyable = len(self.c.by_action(COPIED)) + len(self.c.by_action(EQUAL))
        self.assertEqual(491, copyable)  # the plan's 492 minus the model guard (KEng_Ref)
        self.assertEqual(10, len(self.c.by_action(KEPT)))
        self.assertEqual(13, len(self.c.by_action(LOST)))  # 17 minus Cal_ID and KID_* (identification)
        self.assertEqual(6, len(self.c.by_action(TARGET_ONLY)))

    def test_maps_carry_over(self):
        for name in ("Tab_Fuel_Front", "Tab_Spark_Rear", "Tab_Fuel_RPM_Ax", "Tab_Spark_Load_Ax"):
            vs, vt = self.source.var(name), self.c.result.var(name)
            self.assertEqual(self.source.raw(vs), self.c.result.raw(vt), name)

    def test_target_keeps_what_isnt_copied(self):
        t, r = self.target, self.c.result
        for name in ("Tab_Idle_Spark", "Tab_PRF", "KPIF1", "LFuel", "Ride_Counter", "KTPS0", "CSR",
                     "Country_ID", "KEng_Ref", "Tab_Fuel_End_SL", "KTA_F1"):
            self.assertEqual(t.raw(t.var(name)), r.raw(r.var(name)), name)
        lay = t.layout
        self.assertEqual(t.data[lay.size:], r.data[lay.size:], "page 0")

    def test_only_described_bits_are_copied(self):
        var = self.c.result.var("KEng_Ref")  # excluded anyway; check a copied bitfield instead
        self.assertIsNotNone(var)
        for a in self.c.actions.values():
            if a.action in (COPIED, EQUAL) and a.var_t.type == "Bits":
                labels = db().bit_labels(a.name)
                s, r, t = (img.raw(img.var(a.name))[0] for img in (self.source, self.c.result, self.target))
                for bit in range(8):
                    expected = s if labels[bit] and labels[bit].lower() not in ("unknown", "(unknown)", "reserved") else t
                    self.assertEqual((expected >> bit) & 1, (r >> bit) & 1, f"{a.name} bit {bit + 1}")

    def test_identification_isnt_lost(self):
        self.assertEqual(EXCLUDED, self.c.actions["Cal_ID"].action)
        self.assertEqual(LOST, self.c.actions["KNCRPM_Soft_Hi"].action)


class TestRules(unittest.TestCase):
    def setUp(self):
        self.source = load_image(db(), BUE2D_IMAGE)

    def test_model_guard_stops(self):
        target = random_target("BUEYD", self.source)
        data = bytearray(target.data)
        v = target.var("KEng_Ref")
        data[target.start(v)] ^= 0x02
        target = image_from_bytes(db(), bytes(data), "BUEYD")
        with self.assertRaisesRegex(ConversionError, "model guard: KEng_Ref"):
            convert(db(), self.source, target, rules())
        c = convert(db(), self.source, target, rules(), allow_model_mismatch=True)
        self.assertIn("KEng_Ref", c.model_mismatch)
        self.assertEqual([], c.problems)

    def test_different_families(self):
        target = image_from_bytes(db(), bytes(db().layout("BUEIB").xsize), "BUEIB")
        with self.assertRaisesRegex(ConversionError, "families"):
            convert(db(), self.source, target, rules())

    def test_onto_itself_changes_nothing(self):
        c = convert(db(), self.source, self.source, rules())
        self.assertEqual(self.source.data, c.result.data)
        self.assertEqual([], c.by_action(COPIED))

    def test_same_layout_keeps_per_unit_data(self):
        target = random_target("BUE2D", self.source, seed=2)
        c = convert(db(), self.source, target, rules())
        self.assertEqual([], c.problems)
        d = diff_images(self.source, c.result)
        changed = {e.name for e in d.entries if e.status == "changed"}
        self.assertTrue({"KVIN", "LFuel", "CSR"} <= changed)  # kept from the target
        self.assertNotIn("Tab_Fuel_Front", changed)

    def test_round_trip(self):
        # BUE2D -> BUEYD -> BUE2D gives back every copied variable.
        there = convert(db(), self.source, random_target("BUEYD", self.source), rules())
        back = convert(db(), there.result, self.source, rules())
        for a in there.actions.values():
            if a.action in (COPIED, EQUAL) and a.var_t.type != "Bits":
                self.assertEqual(self.source.raw(a.var_s), back.result.raw(back.result.var(a.name)), a.name)
        self.assertEqual(self.source.data[self.source.layout.size:], back.result.data[self.source.layout.size:])


@unittest.skipUnless(XPRS.is_dir() and any(XPRS.glob("BUE2D*.xpr")) and any(XPRS.glob("BUEYD*.xpr")),
                     "no real images in xprs/")
class TestRealImages(unittest.TestCase):
    """Local check with real images (never committed: they contain VINs)."""

    def test_bue2d_onto_bueyd(self):
        source = load_image(db(), sorted(XPRS.glob("BUE2D*.xpr"))[0])
        for path in sorted(XPRS.glob("BUEYD*.xpr")):
            target = load_image(db(), path)
            try:
                c = convert(db(), source, target, rules())
            except ConversionError as e:
                self.skipTest(f"{path.name}: {e}")
            self.assertEqual([], c.problems, path.name)
            self.assertEqual(target.data[target.layout.size:], c.result.data[target.layout.size:], path.name)

    def test_independent_cross_check(self):
        # diff (a separate code path) must agree: every variable copied as raw
        # bytes is equal in the tune and the result, with and without the
        # proposed rules.
        from calconvlib.convert import RAW
        from calconvlib.rules import RULES_DIR, load_pair

        source = load_image(db(), sorted(XPRS.glob("BUE2D*.xpr"))[0])
        target = load_image(db(), sorted(XPRS.glob("BUEYD*.xpr"))[-1])
        pair = load_pair(RULES_DIR / "BUE2D-BUEYD.toml")
        for allow in (False, True):
            try:
                c = convert(db(), source, target, rules(), pair, allow_proposed=allow)
            except ConversionError as e:
                self.skipTest(str(e))
            status = {e.name: e.status for e in diff_images(source, c.result).entries}
            for a in c.actions.values():
                if a.action in (COPIED, EQUAL) and a.how == RAW and a.var_t.type != "Bits":
                    self.assertEqual("equal", status[a.name], f"{a.name} (allow_proposed={allow})")


if __name__ == "__main__":
    unittest.main()
