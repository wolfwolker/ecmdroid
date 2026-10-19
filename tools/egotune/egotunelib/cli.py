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
"""Command line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, report
from .analysis import Settings, analyse
from .fuelmap import MapError
from .runtime import LogError, load_runtime_defs, log_id, parse_log, read_log
from .tune import VerifyError, build_image, propose_all

from calconvlib.db import DEFAULT_DB, Database, DatabaseError
from calconvlib.image import ImageError, load_image

EXIT_OK, EXIT_ERROR = 0, 2


class UsageError(Exception):
    pass


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--image", type=Path, required=True,
                        help="the .xpr that was in the ECM while the logs were recorded")
    common.add_argument("logs", type=Path, nargs="+", metavar="LOG.bin", help="EcmDroid binary logs")
    common.add_argument("--id", help="ECM ID, if the logs were recorded without one (UNKWN)")
    common.add_argument("--cylinders", choices=("both", "front", "rear"), default="both",
                        help="which maps to tune (default: both; front is skipped without front feedback)")
    common.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help="ECM definition database (default: the app's bundled one)")
    common.add_argument("--format", choices=("md", "json"), default="md", help="report format (default: md)")
    common.add_argument("-o", "--output", type=Path, help="write the report to this file instead of stdout")
    d = Settings()
    g = common.add_argument_group("filters and limits")
    g.add_argument("--min-te", type=float, default=d.min_te, help=f"warm engine from (°C, default {d.min_te:g})")
    g.add_argument("--max-warmup", type=float, default=d.max_warmup,
                   help=f"accepted warm-up enrichment (%%, default {d.max_warmup:g})")
    g.add_argument("--settle", type=float, default=d.settle,
                   help=f"seconds skipped after a transient (default {d.settle:g})")
    g.add_argument("--min-seconds", type=float, default=d.min_seconds,
                   help=f"data a cell needs before it's changed (s, default {d.min_seconds:g})")
    g.add_argument("--full-seconds", type=float, default=d.full_seconds,
                   help=f"data for the full gain (s, default {d.full_seconds:g})")
    g.add_argument("--gain", type=float, default=d.gain,
                   help="part of each correction applied (default 0.33)")
    g.add_argument("--max-rich", type=float, default=d.max_rich,
                   help=f"most a cell may gain per iteration (%%, default {d.max_rich:g})")
    g.add_argument("--max-lean", type=float, default=d.max_lean,
                   help=f"most a cell may lose per iteration (%%, default {d.max_lean:g})")

    parser = argparse.ArgumentParser(
        prog="egotune",
        description="Narrowband fuel-map tuning for DDFI-3 ECMs: computes per-cell corrections "
                    "from EcmDroid logs and applies them to the fuel maps of an .xpr. "
                    "See docs/tuning.md.")
    parser.add_argument("--version", action="version", version=f"egotune {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    sub.add_parser("analyse", parents=[common], help="report the corrections and the proposed changes")
    p = sub.add_parser("apply", parents=[common], help="write a new .xpr with the corrected fuel maps")
    p.add_argument("--out", type=Path, required=True, help="where to write the new image (.xpr)")
    p.add_argument("--force", action="store_true", help="overwrite --out if it exists")
    return parser


def settings_from(args) -> Settings:
    s = Settings(min_te=args.min_te, max_warmup=args.max_warmup, settle=args.settle,
                 min_seconds=args.min_seconds, full_seconds=args.full_seconds, gain=args.gain,
                 max_rich=args.max_rich, max_lean=args.max_lean)
    if not 0 < s.gain <= 1:
        raise UsageError("--gain must be between 0 and 1")
    if s.max_rich < 0 or s.max_lean < 0 or s.min_seconds < 0 or s.full_seconds <= 0:
        raise UsageError("limits must be positive")
    return s


def run(args: argparse.Namespace) -> tuple[str, int]:
    db = Database(args.db)
    raw_logs = [(path, read_log(path)) for path in args.logs]
    forced = db.resolve_id(args.id) if args.id else None
    ids = set()
    for path, data in raw_logs:
        lid = log_id(data)
        if lid in db.ids():
            ids.add(lid)
        elif not forced:
            raise UsageError(f"{path}: recorded without a known ECM ID ({lid!r}). Give it with --id.")
    ecm_id = forced or sorted(ids)[0]
    if len({db.layout(i).category for i in ids | {ecm_id}}) > 1:
        raise UsageError(f"the logs and --id are from different ECM layouts: {', '.join(sorted(ids | {ecm_id}))}")
    img = load_image(db, args.image, ecm_id)
    defs = load_runtime_defs(db.path, ecm_id)
    logs = [parse_log(data, defs.frame_len, path) for path, data in raw_logs]
    for log in logs:
        if not log.records:
            raise LogError(f"{log.name}: no complete record with a valid checksum")

    cylinders = ("front", "rear") if args.cylinders == "both" else (args.cylinders,)
    a = analyse(img, defs, logs, settings_from(args), cylinders)
    changes = propose_all(a)
    out = None
    if args.command == "apply":
        out = args.out
        for given in [args.image, *args.logs]:
            if out.resolve() == given.resolve():
                raise UsageError(f"--out {out} would overwrite an input file")
        if out.exists() and not args.force:
            raise UsageError(f"{out} exists. Use --force to overwrite it.")
        if not a.used:
            raise UsageError("no usable data in the logs: nothing written (see `egotune analyse`)")
        data = build_image(img, changes)
        try:
            out.write_bytes(data)
        except OSError as e:
            raise UsageError(f"can't write {out}: {e.strerror}") from e
    if args.format == "json":
        return report.as_json(a, changes, args.image, out), EXIT_OK
    return report.markdown(a, changes, args.image, out), EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        text, code = run(args)
    except (DatabaseError, ImageError, LogError, MapError, VerifyError, UsageError, ValueError) as e:
        print(f"egotune: error: {e}", file=sys.stderr)
        return EXIT_ERROR
    if args.output:
        try:
            args.output.write_text(text, encoding="utf-8")
        except OSError as e:
            print(f"egotune: error: can't write {args.output}: {e.strerror}", file=sys.stderr)
            return EXIT_ERROR
    else:
        sys.stdout.write(text)
    if args.command == "apply":
        print(report.TESTING_NOTE, file=sys.stderr)
    return code
