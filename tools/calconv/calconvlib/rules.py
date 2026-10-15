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
"""Rule files (TOML). Phase 1-2 only use rules/common.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

RULES_DIR = Path(__file__).resolve().parents[1] / "rules"


class RuleError(Exception):
    """A rule file is missing or malformed."""


@dataclass(frozen=True)
class CommonRules:
    exclude_page0: bool = True
    identification: tuple[str, ...] = ()
    model_guard: tuple[str, ...] = ()
    private: tuple[str, ...] = ()


def _str_list(doc: dict, table: str, key: str, path: Path) -> tuple[str, ...]:
    value = doc.get(table, {}).get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise RuleError(f"{path}: [{table}] {key} must be a list of variable names")
    return tuple(value)


def load_common(path: Path | None = None) -> CommonRules:
    path = path or RULES_DIR / "common.toml"
    try:
        with open(path, "rb") as f:
            doc = tomllib.load(f)
    except OSError as e:
        raise RuleError(f"can't read rule file {path}: {e.strerror}") from e
    except tomllib.TOMLDecodeError as e:
        raise RuleError(f"{path}: {e}") from e
    page0 = doc.get("exclude", {}).get("page0", True)
    if not isinstance(page0, bool):
        raise RuleError(f"{path}: [exclude] page0 must be true or false")
    return CommonRules(
        exclude_page0=page0,
        identification=_str_list(doc, "exclude", "identification", path),
        model_guard=_str_list(doc, "model_guard", "vars", path),
        private=_str_list(doc, "privacy", "vars", path),
    )
