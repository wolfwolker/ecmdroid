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
import unittest

from calconvlib.db import Database, DatabaseError

from .support import db


class TestDatabase(unittest.TestCase):
    def test_resolve_id_accepts_version_strings(self):
        self.assertEqual("BUEIB", db().resolve_id("BUEIB310 10-11-03"))
        self.assertEqual("BUE2D", db().resolve_id("bue2d"))
        with self.assertRaises(DatabaseError):
            db().resolve_id("XXXXX")

    def test_bueib_pages(self):
        # Same expectations as TestEEPROM in the app.
        lay = db().layout("BUEIB")
        self.assertEqual("DDFI-2", lay.family)
        self.assertEqual((1206, 1210), (lay.size, lay.xsize))
        starts = {p.nr: p.start for p in lay.pages}
        self.assertEqual({0: 1206, 1: 0, 2: 0x100, 3: 0x200, 4: 0x29E, 5: 0x39E, 6: 0x49E}, starts)
        self.assertEqual([], lay.warnings)

    def test_layout_sizes(self):
        cases = {"BUEYD": (3232, 3272), "BUE2D": (3756, 3796), "BUEIA": (1056, 1056), "BUE3D": (3884, 3924)}
        for ecm_id, sizes in cases.items():
            lay = db().layout(ecm_id)
            self.assertEqual(sizes, (lay.size, lay.xsize), ecm_id)
            self.assertEqual(lay.xsize, sum(p.size for p in lay.pages), ecm_id)

    def test_shared_layouts_list_stock_ids_first(self):
        self.assertEqual(["BUE2D", "B3R2D"], db().layout("B3R2D").ids)
        self.assertIs(db().layout("BUE2D"), db().layout("B3R2D"))

    def test_ids_for_size(self):
        found = {(m.ecm_id, m.kind) for m in db().ids_for_size(1206)}
        self.assertEqual({("BUEIB", ".epr"), ("BUEIC", ".epr"), ("B2RIB", ".epr")}, found)
        self.assertEqual([], db().ids_for_size(1234))

    def test_variable_definition(self):
        var = db().layout("BUEIB").vars["KMFG_Serial"]
        self.assertEqual(("Value", 2, 2, 1), (var.type, var.size, var.width, var.count))
        axis = db().layout("BUEIB").vars["Tab_Fuel_RPM_Ax"]
        self.assertEqual(("Axis", 26, 2, 13), (axis.type, axis.size, axis.width, axis.count))

    def test_duplicate_definitions_are_reported(self):
        warnings = db().layout("BUEOD").warnings
        self.assertTrue(any("KVS_RPM_Revs is defined twice" in w for w in warnings), warnings)

    def test_bad_database_path(self):
        with self.assertRaises(DatabaseError):
            Database("/does/not/exist.db")


if __name__ == "__main__":
    unittest.main()
