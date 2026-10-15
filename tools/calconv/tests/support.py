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
"""Shared test fixtures: the bundled database and the app's test images."""

from functools import lru_cache

from calconvlib.db import REPO_ROOT, Database
from calconvlib.rules import load_common

FIXTURES = REPO_ROOT / "app" / "src" / "androidTest" / "resources"
BUE2D_IMAGE = FIXTURES / "BUE2D.eeprom"  # .xpr, 3796 bytes
BUEIB_IMAGE = FIXTURES / "BUEIB.eeprom"  # .epr, 1206 bytes (no page 0)


@lru_cache(maxsize=None)
def db() -> Database:
    return Database()


@lru_cache(maxsize=None)
def rules():
    return load_common()
