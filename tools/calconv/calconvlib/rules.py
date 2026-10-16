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
"""Rule files (TOML): rules/common.toml for every conversion, and one file
per direction (e.g. rules/BUE2D-BUEYD.toml). See docs/calibration-converter.md,
"Rule files"."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

RULES_DIR = Path(__file__).resolve().parents[1] / "rules"


class RuleError(Exception):
    """A rule file is missing or malformed."""


@dataclass(frozen=True)
class CommonRules:
    exclude_page0: bool = True
    identification: tuple[str, ...] = ()
    per_unit: tuple[str, ...] = ()
    model_guard: tuple[str, ...] = ()
    private: tuple[str, ...] = ()


def _str_list(doc: dict, table: str, key: str, path: Path) -> tuple[str, ...]:
    value = doc.get(table, {}).get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise RuleError(f"{path}: [{table}] {key} must be a list of variable names")
    return tuple(value)


def _read(path: Path) -> dict:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except OSError as e:
        raise RuleError(f"can't read rule file {path}: {e.strerror}") from e
    except tomllib.TOMLDecodeError as e:
        raise RuleError(f"{path}: {e}") from e


def load_common(path: Path | None = None) -> CommonRules:
    path = path or RULES_DIR / "common.toml"
    doc = _read(path)
    page0 = doc.get("exclude", {}).get("page0", True)
    if not isinstance(page0, bool):
        raise RuleError(f"{path}: [exclude] page0 must be true or false")
    return CommonRules(
        exclude_page0=page0,
        identification=_str_list(doc, "exclude", "identification", path),
        per_unit=_str_list(doc, "exclude", "per_unit", path),
        model_guard=_str_list(doc, "model_guard", "vars", path),
        private=_str_list(doc, "privacy", "vars", path),
    )


# --- pair rules ------------------------------------------------------------

PROPOSED, REVIEWED = "proposed", "reviewed"
EXCLUDE, COPY, ALIAS, TRANSFORM = "exclude", "copy", "alias", "transform"
COPY_ELEMENTS, RESAMPLE_PAIRS = "copy_elements", "resample_pairs"

_REF = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?:\[([1-8])\])?$")
_KEYS = {
    EXCLUDE: {"var", "reason"},
    COPY: {"var", "reason"},
    ALIAS: {"from", "to", "evidence"},
    TRANSFORM: {"var", "from", "kind", "count", "source_start", "target_start", "evidence"},
}
_COMMON_KEYS = {"status", "reviewed_by", "note"}


@dataclass(frozen=True)
class Ref:
    """A variable, or one bit of a bitfield (1..8, numbered like the bits table)."""

    name: str
    bit: int | None = None

    def __str__(self) -> str:
        return self.name if self.bit is None else f"{self.name}[{self.bit}]"


@dataclass(frozen=True)
class Rule:
    kind: str  # exclude, copy, alias, transform
    source: Ref  # the source variable (for exclude and copy: the same name as the target)
    targets: tuple[Ref, ...]
    status: str
    why: str = ""  # reason or evidence
    reviewed_by: str = ""
    transform: str = ""  # copy_elements, resample_pairs
    count: int = 0
    source_start: int = 0
    target_start: int = 0
    where: str = ""  # file and entry, for messages

    @property
    def reviewed(self) -> bool:
        return self.status == REVIEWED

    def describe(self) -> str:
        targets = ", ".join(map(str, self.targets))
        if self.kind == ALIAS:
            return f"alias {self.source} → {targets}"
        if self.kind == TRANSFORM:
            src = "" if self.source.name == self.targets[0].name else f" from {self.source}"
            if self.transform == COPY_ELEMENTS:
                s, t = self.source_start, self.target_start
                return (f"copy_elements {targets}{src}: source elements {s + 1}–{s + self.count} "
                        f"→ target elements {t + 1}–{t + self.count}")
            return f"{self.transform} {targets}{src}"
        return f"{self.kind} {targets}"


@dataclass
class PairRules:
    src_id: str
    dst_id: str
    path: Path | None = None
    rules: list[Rule] = field(default_factory=list)

    def by_kind(self, kind: str) -> list[Rule]:
        return [r for r in self.rules if r.kind == kind]


def parse_ref(text, where: str) -> Ref:
    m = _REF.match(text.strip()) if isinstance(text, str) else None
    if not m:
        raise RuleError(f"{where}: {text!r} isn't a variable name or Name[bit] with bit 1..8")
    return Ref(m.group(1), int(m.group(2)) if m.group(2) else None)


def _rule(kind: str, entry: dict, where: str) -> Rule:
    if not isinstance(entry, dict):
        raise RuleError(f"{where}: must be a table")
    unknown = set(entry) - _KEYS[kind] - _COMMON_KEYS
    if unknown:
        raise RuleError(f"{where}: unknown key(s) {', '.join(sorted(unknown))}")
    status = entry.get("status")
    if status not in (PROPOSED, REVIEWED):
        raise RuleError(f'{where}: status must be "{PROPOSED}" or "{REVIEWED}"')
    reviewed_by = entry.get("reviewed_by", "")
    if not isinstance(reviewed_by, str) or (status == REVIEWED and not reviewed_by.strip()):
        raise RuleError(f"{where}: a reviewed entry needs reviewed_by (who reviewed it)")

    def text(key, required=False):
        value = entry.get(key, "")
        if not isinstance(value, str) or (required and not value.strip()):
            raise RuleError(f"{where}: {key} must be {'a non-empty' if required else 'a'} string")
        return value.strip()

    def number(key, default, minimum):
        value = entry.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise RuleError(f"{where}: {key} must be an integer ≥ {minimum}")
        return value

    if kind in (EXCLUDE, COPY):
        ref = parse_ref(entry.get("var"), where)
        if ref.bit is not None:
            raise RuleError(f"{where}: {kind} works on whole variables")
        return Rule(kind, ref, (ref,), status, text("reason", required=True), reviewed_by, where=where)
    if kind == ALIAS:
        src = parse_ref(entry.get("from"), where)
        to = entry.get("to")
        to = [to] if isinstance(to, str) else to
        if not isinstance(to, list) or not to:
            raise RuleError(f"{where}: to must be a variable name or a list of them")
        targets = tuple(parse_ref(t, where) for t in to)
        if any((t.bit is None) != (src.bit is None) for t in targets):
            raise RuleError(f"{where}: map a bit to bits, or a variable to variables")
        if len(set(targets)) != len(targets):
            raise RuleError(f"{where}: a target is listed twice")
        return Rule(kind, src, targets, status, text("evidence", required=True), reviewed_by, where=where)
    # transform
    target = parse_ref(entry.get("var"), where)
    src = parse_ref(entry.get("from", target.name), where)
    if target.bit is not None or src.bit is not None:
        raise RuleError(f"{where}: transforms work on whole variables")
    transform = entry.get("kind")
    if transform == COPY_ELEMENTS:
        count = number("count", None, 1)
        return Rule(kind, src, (target,), status, text("evidence", required=True), reviewed_by,
                    transform, count, number("source_start", 0, 0), number("target_start", 0, 0), where)
    if transform == RESAMPLE_PAIRS:
        extra = {"count", "source_start", "target_start"} & set(entry)
        if extra:
            raise RuleError(f"{where}: {', '.join(sorted(extra))} only apply to {COPY_ELEMENTS}")
        return Rule(kind, src, (target,), status, text("evidence", required=True), reviewed_by,
                    transform, where=where)
    raise RuleError(f'{where}: kind must be "{COPY_ELEMENTS}" or "{RESAMPLE_PAIRS}"')


def load_pair(path: Path) -> PairRules:
    doc = _read(path)
    pair = doc.get("pair")
    if not isinstance(pair, dict) or not isinstance(pair.get("from"), str) or not isinstance(pair.get("to"), str):
        raise RuleError(f'{path}: needs a [pair] table with from = "ID" and to = "ID"')
    unknown = set(doc) - {"pair", EXCLUDE, COPY, ALIAS, TRANSFORM}
    if unknown:
        raise RuleError(f"{path}: unknown table(s) {', '.join(sorted(unknown))}")
    out = PairRules(pair["from"].strip().upper(), pair["to"].strip().upper(), path)
    for kind in (EXCLUDE, COPY, ALIAS, TRANSFORM):
        entries = doc.get(kind, [])
        if not isinstance(entries, list):
            raise RuleError(f"{path}: use [[{kind}]] for each entry")
        for i, entry in enumerate(entries, 1):
            out.rules.append(_rule(kind, entry, f"{path.name}: [[{kind}]] #{i}"))
    return out


def find_pair(src_ids: list[str], dst_ids: list[str], rules_dir: Path | None = None) -> Path | None:
    """The rule file for a direction. The first ID of each list is the one
    asked for; the others share its layout and are tried after it."""
    rules_dir = rules_dir or RULES_DIR
    for s in src_ids:
        for d in dst_ids:
            path = rules_dir / f"{s}-{d}.toml"
            if path.is_file():
                return path
    return None
