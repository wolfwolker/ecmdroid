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
"""Command line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, report
from .analysis import make_plan
from .db import DEFAULT_DB, Database, DatabaseError
from .diff import diff_images
from .image import ImageError, load_image
from .rules import RuleError, load_common

EXIT_OK, EXIT_DIFFERENT, EXIT_ERROR = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help="ECM definition database (.db or .db.gz; default: the app's bundled one)")
    common.add_argument("--rules", type=Path, help="common rule file (default: rules/common.toml)")
    common.add_argument("--format", choices=("md", "json"), default="md", help="output format (default: md)")
    common.add_argument("-o", "--output", type=Path, help="write the report to this file instead of stdout")

    parser = argparse.ArgumentParser(
        prog="calconv",
        description="Compare and (later) convert Buell ECM calibration images (.xpr/.epr) "
                    "between firmware layouts. See docs/calibration-converter.md.")
    parser.add_argument("--version", action="version", version=f"calconv {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    sub.add_parser("layouts", parents=[common], help="list the ECM layouts and their file sizes")

    p = sub.add_parser("plan", parents=[common],
                       help="analyse what a conversion between two layouts would copy, lose or flag")
    p.add_argument("--from", dest="src", required=True, metavar="ID", help="source ECM ID, e.g. BUE2D")
    p.add_argument("--to", dest="dst", required=True, metavar="ID", help="target ECM ID, e.g. BUEYD")
    p.add_argument("--all", action="store_true", help="also list the copyable and excluded variables")

    p = sub.add_parser("info", parents=[common], help="identify an image and show its ECM information")
    p.add_argument("file", type=Path)
    p.add_argument("--id", help="ECM ID, needed when the file size fits several layouts")
    p.add_argument("--show-private", action="store_true", help="show VIN and security data")

    p = sub.add_parser("diff", parents=[common],
                       help="compare two images by variable name (exit code 1 if they differ)")
    p.add_argument("file_a", type=Path)
    p.add_argument("file_b", type=Path)
    p.add_argument("--id-a", help="ECM ID of the first file")
    p.add_argument("--id-b", help="ECM ID of the second file")
    p.add_argument("--show-private", action="store_true", help="show VIN and security data")
    p.add_argument("--all", action="store_true", help="also list the equal variables")
    return parser


def run(args: argparse.Namespace) -> tuple[str, int]:
    db = Database(args.db)
    rules = load_common(args.rules)
    if args.command == "layouts":
        return report.layouts(db, args.format), EXIT_OK
    if args.command == "plan":
        p = make_plan(db, args.src, args.dst, rules)
        return report.plan(p, args.format, args.all), EXIT_OK
    if args.command == "info":
        img = load_image(db, args.file, args.id)
        return report.info(db, img, rules, args.show_private, args.format), EXIT_OK
    if args.command == "diff":
        a = load_image(db, args.file_a, args.id_a)
        b = load_image(db, args.file_b, args.id_b)
        d = diff_images(a, b, rules.private)
        text = report.diff(d, args.format, args.show_private, args.all)
        return text, EXIT_OK if d.identical else EXIT_DIFFERENT
    raise AssertionError(args.command)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        text, code = run(args)
    except (DatabaseError, ImageError, RuleError) as e:
        print(f"calconv: error: {e}", file=sys.stderr)
        return EXIT_ERROR
    if args.output:
        try:
            args.output.write_text(text, encoding="utf-8")
        except OSError as e:
            print(f"calconv: error: can't write {args.output}: {e.strerror}", file=sys.stderr)
            return EXIT_ERROR
    else:
        sys.stdout.write(text)
    return code
