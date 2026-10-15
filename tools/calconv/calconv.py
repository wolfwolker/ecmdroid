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
"""calconv: compare and convert Buell ECM calibration images (.xpr/.epr).

Run it directly (needs pkgx, which provides Python 3.11 and uv), or with any
Python 3.11+: `python3 calconv.py --help`. See README.md next to this file.
"""

import sys

from calconvlib.cli import main

if __name__ == "__main__":
    sys.exit(main())
