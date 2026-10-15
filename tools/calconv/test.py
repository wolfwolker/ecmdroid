#!/usr/bin/env -S pkgx +python@3.11 uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
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
"""Run the calconv test suite: ./test.py [-v] (or python3 test.py)."""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent

if __name__ == "__main__":
    sys.dont_write_bytecode = True
    verbosity = 2 if "-v" in sys.argv[1:] else 1
    suite = unittest.defaultTestLoader.discover(str(HERE / "tests"), top_level_dir=str(HERE))
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
