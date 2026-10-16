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
from .convert import ConversionError, check_rules, convert
from .db import DEFAULT_DB, Database, DatabaseError
from .diff import diff_images
from .draft import draft_rules
from .image import ImageError, load_image
from .rules import RULES_DIR, RuleError, find_pair, load_common, load_pair

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
        description="Compare and convert Buell ECM calibration images (.xpr/.epr) "
                    "between firmware layouts. See docs/calibration-converter.md.")
    parser.add_argument("--version", action="version", version=f"calconv {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    sub.add_parser("layouts", parents=[common], help="list the ECM layouts and their file sizes")

    p = sub.add_parser("plan", parents=[common],
                       help="analyse what a conversion between two layouts would copy, lose or flag")
    p.add_argument("--from", dest="src", required=True, metavar="ID", help="source ECM ID, e.g. BUE2D")
    p.add_argument("--to", dest="dst", required=True, metavar="ID", help="target ECM ID, e.g. BUEYD")
    p.add_argument("--all", action="store_true", help="also list the copyable and excluded variables")
    _pair_options(p)

    p = sub.add_parser("draft-rules", parents=[common],
                       help="draft a rule file for a direction (every entry proposed, for review)")
    p.add_argument("--from", dest="src", required=True, metavar="ID", help="source ECM ID, e.g. BUE2D")
    p.add_argument("--to", dest="dst", required=True, metavar="ID", help="target ECM ID, e.g. BUEYD")
    p.add_argument("--force", action="store_true", help="overwrite -o if it exists")

    p = sub.add_parser("show", parents=[common],
                       help="show variables: definitions and database texts per layout, values per image")
    p.add_argument("names", nargs="+", metavar="VAR", help="variable names, e.g. Tab_Idle_Spark")
    p.add_argument("--id", dest="ids", action="append", default=[], metavar="ID",
                   help="a layout to show (repeatable); the images' IDs are added")
    p.add_argument("--image", dest="images", action="append", default=[], metavar="FILE[@ID]",
                   help="an image to read values from (repeatable); add @ID if the size is ambiguous")
    p.add_argument("--show-private", action="store_true", help="show VIN and security data")

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

    p = sub.add_parser("convert", parents=[common],
                       help="carry a tune onto an image of another layout (writes a new .xpr)")
    p.add_argument("--source", type=Path, required=True, help="the tune to carry over, e.g. a BUE2D .xpr")
    p.add_argument("--target", type=Path, required=True,
                   help="the target ECM's own image, e.g. a BUEYD .xpr read from it")
    p.add_argument("--out", type=Path, required=True, help="where to write the result (.xpr)")
    p.add_argument("--from", dest="src", metavar="ID", help="ECM ID of the source, if its size is ambiguous")
    p.add_argument("--to", dest="dst", metavar="ID", help="ECM ID of the target, if its size is ambiguous")
    p.add_argument("--allow-model-mismatch", action="store_true",
                   help="convert even if engine/harness variables differ (experts only)")
    p.add_argument("--force", action="store_true", help="overwrite --out if it exists")
    p.add_argument("--all", action="store_true", help="also list the equal, excluded and target-only variables")
    _pair_options(p)
    p.add_argument("--allow-proposed", action="store_true",
                   help="also apply rule entries that aren't reviewed yet (the report says so)")
    return parser


def _pair_options(p: argparse.ArgumentParser):
    g = p.add_mutually_exclusive_group()
    g.add_argument("--pair-rules", type=Path, metavar="FILE",
                   help="rule file for this direction (default: rules/<FROM>-<TO>.toml, if it exists)")
    g.add_argument("--no-pair-rules", action="store_true", help="ignore the rule file for this direction")


def _load_pair(args, db: Database, src_id: str, dst_id: str):
    if args.no_pair_rules:
        return None
    if args.pair_rules:
        return load_pair(args.pair_rules)
    src, dst = db.layout(src_id), db.layout(dst_id)
    rules_dir = args.rules.parent if args.rules else RULES_DIR
    path = find_pair([src_id] + src.ids, [dst_id] + dst.ids, rules_dir)
    return load_pair(path) if path else None


def run(args: argparse.Namespace) -> tuple[str, int]:
    db = Database(args.db)
    rules = load_common(args.rules)
    if args.command == "layouts":
        return report.layouts(db, args.format), EXIT_OK
    if args.command == "plan":
        p = make_plan(db, args.src, args.dst, rules)
        pair = _load_pair(args, db, p.src_id, p.dst_id)
        if pair is not None:
            check_rules(db, pair, p, rules)
        return report.plan(p, args.format, args.all, pair), EXIT_OK
    if args.command == "draft-rules":
        if args.output and args.output.exists() and not args.force:
            raise RuleError(f"{args.output} exists. Use --force to overwrite it.")
        return draft_rules(make_plan(db, args.src, args.dst, rules), rules), EXIT_OK
    if args.command == "show":
        images = []
        for spec in args.images:
            path, _, ecm_id = spec.rpartition("@") if "@" in spec else (spec, "", "")
            images.append(load_image(db, Path(path), ecm_id or None))
        ids = [db.resolve_id(i) for i in args.ids]
        ids += [img.ecm_id for img in images if img.ecm_id not in ids]
        if not ids:
            raise DatabaseError("give at least one --id or --image")
        return report.show(db, args.names, ids, images, rules, args.show_private, args.format), EXIT_OK
    if args.command == "info":
        img = load_image(db, args.file, args.id)
        return report.info(db, img, rules, args.show_private, args.format), EXIT_OK
    if args.command == "diff":
        a = load_image(db, args.file_a, args.id_a)
        b = load_image(db, args.file_b, args.id_b)
        d = diff_images(a, b, rules.private)
        text = report.diff(d, args.format, args.show_private, args.all)
        return text, EXIT_OK if d.identical else EXIT_DIFFERENT
    if args.command == "convert":
        out = args.out
        for given in (args.source, args.target):
            if out.resolve() == given.resolve():
                raise ConversionError(f"--out {out} would overwrite an input file")
        if out.exists() and not args.force:
            raise ConversionError(f"{out} exists. Use --force to overwrite it.")
        source = load_image(db, args.source, args.src)
        target = load_image(db, args.target, args.dst)
        pair = _load_pair(args, db, source.ecm_id, target.ecm_id)
        c = convert(db, source, target, rules, pair, args.allow_model_mismatch, args.allow_proposed)
        if c.problems:
            return report.conversion(c, out, args.format, args.all, rules.private), EXIT_ERROR
        try:
            out.write_bytes(c.result.data)
        except OSError as e:
            raise ConversionError(f"can't write {out}: {e.strerror}") from e
        return report.conversion(c, out, args.format, args.all, rules.private), EXIT_OK
    raise AssertionError(args.command)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        text, code = run(args)
    except (DatabaseError, ImageError, RuleError, ConversionError) as e:
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
    if args.command == "convert" and code == EXIT_OK:
        print(report.TESTING_NOTE, file=sys.stderr)
    return code
