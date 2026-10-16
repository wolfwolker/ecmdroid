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
"""Pair rule files (phase 4): parsing, aliases, transforms and drafts."""

import tempfile
import unittest
from pathlib import Path

from calconvlib.analysis import make_plan
from calconvlib.convert import (BIT, COPIED, ELEMENTS, EQUAL, EXCLUDED, KEPT, LOST, RAW, RESAMPLED, SCALED,
                                check_rules, convert)
from calconvlib.draft import draft_rules
from calconvlib.image import element_ints, encode_element, image_from_bytes, load_image
from calconvlib.rules import RULES_DIR, RuleError, find_pair, load_pair

from .support import BUE2D_IMAGE, BUEIB_IMAGE, db, rules
from .test_convert import random_target

REVIEWED = 'status = "reviewed"\nreviewed_by = "test"\n'


def pair_file(text: str, src="BUE2D", dst="BUEYD"):
    tmp = Path(tempfile.mkdtemp()) / f"{src}-{dst}.toml"
    tmp.write_text(f'[pair]\nfrom = "{src}"\nto = "{dst}"\n\n' + text)
    return load_pair(tmp)


def with_bytes(img, name, raw):
    data = bytearray(img.data)
    v = img.var(name)
    data[img.start(v):img.start(v) + len(raw)] = raw
    return image_from_bytes(db(), bytes(data), img.ecm_id)


class TestParsing(unittest.TestCase):
    def test_shipped_rule_files_are_valid(self):
        files = [p for p in RULES_DIR.glob("*.toml") if p.name != "common.toml"]
        self.assertIn("BUE2D-BUEYD.toml", [p.name for p in files])
        for path in files:
            pair = load_pair(path)
            self.assertEqual(path.stem, f"{pair.src_id}-{pair.dst_id}")
            check_rules(db(), pair, make_plan(db(), pair.src_id, pair.dst_id, rules()), rules())

    def test_errors(self):
        cases = {
            '[[exclude]]\nvar = "Tab_PRF"\nreason = "x"\nstatus = "ok"\n': "status must be",
            '[[exclude]]\nvar = "Tab_PRF"\nreason = "x"\nstatus = "reviewed"\n': "needs reviewed_by",
            '[[exclude]]\nvar = "Tab_PRF"\nreason = "x"\nstauts = "proposed"\n': "unknown key",
            '[[alias]]\nfrom = "A[9]"\nto = "B"\nevidence = "x"\nstatus = "proposed"\n': "isn't a variable name",
            '[[alias]]\nfrom = "A[1]"\nto = "B"\nevidence = "x"\nstatus = "proposed"\n': "map a bit to bits",
            '[[alias]]\nfrom = "A"\nto = "B"\nstatus = "proposed"\n': "evidence must be",
            '[[transform]]\nvar = "A"\nkind = "magic"\nevidence = "x"\nstatus = "proposed"\n': "kind must be",
            '[[transform]]\nvar = "A"\nkind = "copy_elements"\nevidence = "x"\nstatus = "proposed"\n': "count",
            '[[transform]]\nvar = "A"\nkind = "resample_pairs"\ncount = 2\nevidence = "x"\nstatus = "proposed"\n':
                "only apply to copy_elements",
            '[exclude]\nvar = "A"\n': "use \\[\\[exclude\\]\\]",
        }
        for text, message in cases.items():
            with self.subTest(text=text):
                with self.assertRaisesRegex(RuleError, message):
                    pair_file(text)

    def test_pair_table_required(self):
        tmp = Path(tempfile.mkdtemp()) / "x.toml"
        tmp.write_text('[[exclude]]\nvar = "A"\nreason = "x"\nstatus = "proposed"\n')
        with self.assertRaisesRegex(RuleError, r"\[pair\]"):
            load_pair(tmp)

    def test_find_pair_uses_layout_siblings(self):
        # B3R2D shares BUE2D's layout, so a B3R2D tune finds BUE2D-BUEYD.toml.
        found = find_pair(["B3R2D"] + db().layout("B3R2D").ids, ["BUEYD"] + db().layout("BUEYD").ids)
        self.assertEqual("BUE2D-BUEYD.toml", found.name)
        self.assertIsNone(find_pair(["BUEYD"], ["BUE2D"]))

    def test_checks_against_the_layouts(self):
        plan = make_plan(db(), "BUE2D", "BUEYD", rules())
        cases = {
            '[[exclude]]\nvar = "Nope"\nreason = "x"\nstatus = "proposed"\n': "in neither",
            '[[alias]]\nfrom = "KNCRPM_Soft_Hi"\nto = "LFuel"\nevidence = "x"\nstatus = "proposed"\n':
                r"never written \(per unit\)",
            '[[alias]]\nfrom = "KNCRPM_Soft_Hi"\nto = "KVIN"\nevidence = "x"\nstatus = "proposed"\n':
                r"never written \(page 0\)",
            '[[copy]]\nvar = "Tab_PRF"\nreason = "x"\nstatus = "proposed"\n': "copy needs an identical one",
            '[[transform]]\nvar = "Tab_PRF"\nkind = "copy_elements"\ncount = 5\nevidence = "x"\nstatus = "proposed"\n':
                "don't fit",
            '[[transform]]\nvar = "Tab_PRF"\nkind = "resample_pairs"\nevidence = "x"\nstatus = "proposed"\n':
                "self-contained tables",
            '[[alias]]\nfrom = "KSpark_Config[2]"\nto = "Tab_PRF[1]"\nevidence = "x"\nstatus = "proposed"\n':
                "isn't a bitfield",
        }
        for text, message in cases.items():
            with self.subTest(text=text):
                with self.assertRaisesRegex(RuleError, message):
                    check_rules(db(), pair_file(text), plan, rules())
        with self.assertRaisesRegex(RuleError, "the rules are for BUE2D → BUEYD"):
            check_rules(db(), pair_file(""), make_plan(db(), "BUEYD", "BUE2D", rules()), rules())


class TestBUE2DToBUEYDRules(unittest.TestCase):
    """The shipped rule file. Its entries are proposed until someone reviews them."""

    @classmethod
    def setUpClass(cls):
        cls.source = load_image(db(), BUE2D_IMAGE)
        cls.target = random_target("BUEYD", cls.source)
        cls.pair = load_pair(RULES_DIR / "BUE2D-BUEYD.toml")

    def test_proposed_rules_arent_applied(self):
        c = convert(db(), self.source, self.target, rules(), self.pair)
        self.assertEqual([], c.problems)
        self.assertEqual([], c.applied)
        self.assertEqual(len(self.pair.rules), len(c.pending))
        self.assertEqual(10, len(c.by_action(KEPT)))

    def test_allow_proposed(self):
        c = convert(db(), self.source, self.target, rules(), self.pair, allow_proposed=True)
        self.assertEqual([], c.problems)
        self.assertEqual([], c.by_action(KEPT))
        for name in ("Tab_Idle_Spark", "KPIF1"):
            self.assertEqual(EXCLUDED, c.actions[name].action)
            self.assertEqual(self.target.raw(self.target.var(name)), c.result.raw(c.result.var(name)))
        for name in ("Tab_PRF", "Tab_ILR"):
            a = c.actions[name]
            self.assertEqual(ELEMENTS, a.how)
            src = element_ints(a.var_s, self.source.raw(a.var_s))
            self.assertEqual(src[1:5], element_ints(a.var_t, c.result.raw(a.var_t)))


class TestTransforms(unittest.TestCase):
    def setUp(self):
        self.source = load_image(db(), BUE2D_IMAGE)
        self.target = random_target("BUEYD", self.source)

    def test_resample_pairs(self):
        # BUE2D test image: 0 °C → 13°, 18 → 5, 70 → 4, 120 → 0, 160 → 0, 215 → 0.
        # Target axis 0, 22, 60, 160 °C (raw axis = °C + 40).
        target = with_bytes(self.target, "Tab_Idle_Spark", bytes([40, 0, 62, 0, 100, 0, 200, 0]))
        pair = pair_file('[[transform]]\nvar = "Tab_Idle_Spark"\nkind = "resample_pairs"\nevidence = "test"\n'
                         + REVIEWED)
        c = convert(db(), self.source, target, rules(), pair)
        self.assertEqual([], c.problems)
        a = c.actions["Tab_Idle_Spark"]
        self.assertEqual((COPIED, RESAMPLED), (a.action, a.how))
        # 22 °C: 5 + (4 - 5) × 4/52 = 4.92 → 5.0; 60 °C: 5 - 42/52 = 4.19 → 4.25 (0.25° steps)
        self.assertEqual([0, 13.0, 22, 5.0, 60, 4.25, 160, 0.0], a.after)

    def test_exclusion_wins(self):
        pair = pair_file('[[transform]]\nvar = "Tab_Idle_Spark"\nkind = "resample_pairs"\nevidence = "test"\n'
                         + REVIEWED + '\n[[exclude]]\nvar = "Tab_Idle_Spark"\nreason = "test"\n' + REVIEWED)
        c = convert(db(), self.source, self.target, rules(), pair)
        self.assertEqual(EXCLUDED, c.actions["Tab_Idle_Spark"].action)
        self.assertEqual(1, len(c.skipped))

    def test_bit_alias_into_undescribed_bit(self):
        # KConfig is copied with its described bits; bit 7 is undescribed, so a rule may set it.
        pair = pair_file('[[alias]]\nfrom = "KSpark_Config[2]"\nto = "KConfig[7]"\nevidence = "test"\n' + REVIEWED)
        target = with_bytes(self.target, "KConfig", bytes([self.source.raw(self.source.var("KConfig"))[0] ^ 0xFF]))
        c = convert(db(), self.source, target, rules(), pair)
        self.assertEqual([], c.problems)
        a = c.actions["KConfig[7]"]
        self.assertEqual(BIT, a.how)
        s = self.source.raw(self.source.var("KSpark_Config"))[0] >> 1 & 1
        r = c.result.raw(c.result.var("KConfig"))[0]
        self.assertEqual(s, r >> 6 & 1)
        self.assertEqual(self.source.raw(self.source.var("KConfig"))[0] & 0x3F, r & 0x3F)
        self.assertIn("KSpark_Config", [x.name for x in c.by_action(LOST)])  # its other bits are still lost

    def test_bit_alias_onto_a_copied_bit_is_refused(self):
        pair = pair_file('[[alias]]\nfrom = "KSpark_Config[2]"\nto = "KConfig[1]"\nevidence = "test"\n' + REVIEWED)
        with self.assertRaisesRegex(RuleError, "already written by KConfig"):
            convert(db(), self.source, self.target, rules(), pair)

    def test_two_rules_for_one_target(self):
        rule = '[[transform]]\nvar = "Tab_PRF"\nkind = "copy_elements"\ncount = 4\nevidence = "x"\n' + REVIEWED
        with self.assertRaisesRegex(RuleError, "also written by"):
            convert(db(), self.source, self.target, rules(), pair_file(rule + "\n" + rule))

    def test_encode_range(self):
        var = self.source.var("Tab_PRF")  # 1 byte, scale 0.1
        self.assertEqual(25, encode_element(var, 0, 2.5))
        self.assertIsNone(encode_element(var, 0, 25.6))
        self.assertIsNone(encode_element(var, 0, -0.1))


class TestAliases(unittest.TestCase):
    """BUEIB → BUECB (DDFI-2), which has real renames."""

    def setUp(self):
        self.source = load_image(db(), BUEIB_IMAGE, "BUEIB")
        self.target = random_target("BUECB", self.source)

    def test_identical_alias(self):
        pair = pair_file('[[alias]]\nfrom = "K_Fan_Period"\nto = "KFan_Period"\nevidence = "test"\n' + REVIEWED,
                         "BUEIB", "BUECB")
        c = convert(db(), self.source, self.target, rules(), pair)
        self.assertEqual([], c.problems)
        a = c.actions["KFan_Period"]
        self.assertEqual((RAW, "K_Fan_Period"), (a.how, a.source_name))
        self.assertEqual(self.source.raw(a.var_s), c.result.raw(a.var_t))
        self.assertNotIn("K_Fan_Period", c.actions)  # accounted for by its target, not lost

    def test_one_to_many(self):
        pair = pair_file('[[alias]]\nfrom = "Tab_Fan_Duty"\nto = ["Tab_Fan_Duty_Aft", "Tab_Fan_Duty_Fore"]\n'
                         'evidence = "test"\n' + REVIEWED, "BUEIB", "BUECB")
        c = convert(db(), self.source, self.target, rules(), pair)
        self.assertEqual([], c.problems)
        for name in ("Tab_Fan_Duty_Aft", "Tab_Fan_Duty_Fore"):
            self.assertIn(c.actions[name].action, (COPIED, EQUAL))
            self.assertEqual(self.source.raw(self.source.var("Tab_Fan_Duty")), c.result.raw(c.result.var(name)))

    def test_scaled_alias(self):
        pair = pair_file('[[alias]]\nfrom = "KAIC_Period"\nto = "KFan_Period"\nevidence = "test"\n' + REVIEWED,
                         "BUEIB", "BUECB")
        c = convert(db(), self.source, self.target, rules(), pair)
        self.assertEqual([], c.problems)
        a = c.actions["KFan_Period"]
        self.assertEqual(SCALED, a.how)
        self.assertAlmostEqual(a.source[0], a.after[0], delta=0.5)

    def test_copy_rule_for_a_flagged_variable(self):
        # Tab_Idle_Spark has the same definition on BUEIB and BUECB, but its
        # description names firmware versions, so it's kept unless a rule says otherwise.
        c = convert(db(), self.source, self.target, rules())
        self.assertEqual(KEPT, c.actions["Tab_Idle_Spark"].action)
        pair = pair_file('[[copy]]\nvar = "Tab_Idle_Spark"\nreason = "test"\n' + REVIEWED, "BUEIB", "BUECB")
        c = convert(db(), self.source, self.target, rules(), pair)
        self.assertIn(c.actions["Tab_Idle_Spark"].action, (COPIED, EQUAL))


class TestDraft(unittest.TestCase):
    def test_every_same_family_pair_drafts_a_valid_file(self):
        ids = [lay.ids[0] for lay in db().layouts()]
        for a in ids:
            for b in ids:
                if a == b or db().layout(a).family != db().layout(b).family:
                    continue
                plan = make_plan(db(), a, b, rules())
                pair = pair_file(draft_rules(plan, rules()).split("\n", 9)[-1], a, b)  # drop header and [pair]
                self.assertTrue(all(not r.reviewed for r in pair.rules), f"{a}-{b}")
                check_rules(db(), pair, plan, rules())

    def test_bueib_to_buecb(self):
        text = draft_rules(make_plan(db(), "BUEIB", "BUECB", rules()), rules())
        self.assertIn('from = "K_Fan_Period"\nto = "KFan_Period"', text)
        self.assertIn("# Not proposed: K_Fan_Period is a better match for KFan_Period", text)


if __name__ == "__main__":
    unittest.main()
