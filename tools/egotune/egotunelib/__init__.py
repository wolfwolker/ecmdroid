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
"""Library behind the egotune command (see docs/tuning.md).

It reuses calconv's database and image modules (tools/calconv/calconvlib),
so the ECM definitions and the .xpr handling are the same in both tools.
"""

import sys
from pathlib import Path

__version__ = "0.1.0"

_CALCONV = Path(__file__).resolve().parents[2] / "calconv"
if str(_CALCONV) not in sys.path:
    sys.path.insert(0, str(_CALCONV))
