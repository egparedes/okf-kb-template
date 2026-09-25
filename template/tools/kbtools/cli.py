"""`kb` command line: validate, index, fix links, log, create pages, report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import hooks, indexgen, linkfix, pages, report
from .bundle import Bundle
from .check import Checker, exit_code


def _cmd_check(bundle: Bundle, args: argparse.Namespace) -> int:
    checker = Checker(bundle)
    if args.paths:
        paths = [bundle.path_arg(p) for p in args.paths if p.endswith(".md")]
        for arg, path in zip([p for p in args.paths if p.endswith(".md")], paths):
            if path is None:
                print(f"kb: skipping {arg} (not a file in the bundle)", file=sys.stderr)
        diagnostics = checker.check_files([bundle.document(p) for p in paths if p])
    else:
        diagnostics = checker.check_all()
    shown = [d for d in diagnostics if d.is_error or not args.errors_only]
    for diagnostic in shown:
        print(diagnostic)
    errors = sum(d.is_error for d in diagnostics)
    warnings = len(diagnostics) - errors
    print(f"kb check: {errors} error(s), {warnings} warning(s) in {len(bundle.documents)} file(s)", file=sys.stderr)
    return exit_code(diagnostics, args.strict)


def _cmd_index(bundle: Bundle, args: argparse.Namespace) -> int:
    if args.check:
        stale = indexgen.stale(bundle)
        for path in stale:
            print(f"out of date: {path.relative_to(bundle.repo_root)}")
        return 1 if stale else 0
    for path in indexgen.write(bundle):
        print(f"wrote {path.relative_to(bundle.repo_root)}")
    return 0


def _cmd_fix_links(bundle: Bundle, args: argparse.Namespace) -> int:
    docs = [bundle.document(p) for p in map(bundle.path_arg, args.paths) if p] if args.paths else None
    for doc in linkfix.fix(bundle, docs):
        print(f"fixed links in kb/{doc.rel}")
    return 0


def _cmd_mv(bundle: Bundle, args: argparse.Namespace) -> int:
    for rel in linkfix.move(bundle, args.old, args.new):
        print(f"updated links in kb/{rel}")
    for path in indexgen.write(Bundle(bundle.root, bundle.repo_root)):
        print(f"wrote {path.relative_to(bundle.repo_root)}")
    return 0


def _cmd_log(bundle: Bundle, args: argparse.Namespace) -> int:
    path = pages.add_log_entry(bundle, args.op, " ".join(args.message))
    print(f"logged in {path.relative_to(bundle.repo_root)}")
    return 0


def _cmd_new(bundle: Bundle, args: argparse.Namespace) -> int:
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
    path = pages.new_page(
        bundle, args.type, args.path, args.title, args.description, tags, args.by, args.status, args.resource
    )
    print(path.relative_to(bundle.repo_root))
    return 0


def _cmd_report(bundle: Bundle, args: argparse.Namespace) -> int:
    sys.stdout.write(report.build(bundle))
    return 0


def _cmd_find(bundle: Bundle, args: argparse.Namespace) -> int:
    """Frontmatter filter (retrieval tier 2): print matching concepts as `path<TAB>type<TAB>title`."""
    for doc in bundle.concepts():
        fm = doc.frontmatter
        if doc.frontmatter_error or not doc.type:
            continue
        if args.type and doc.type != args.type:
            continue
        if args.tag and not set(args.tag) <= set(fm.get("tags") or []):
            continue
        if args.status and fm.get("status", "stable") != args.status:
            continue
        if args.folder and not str(doc.rel).startswith(args.folder.strip("/") + "/"):
            continue
        if args.trust and report.trust_tier(doc) != args.trust:
            continue
        print(f"/{doc.rel}\t{doc.type}\t{doc.title}")
    return 0


def _cmd_folders(bundle: Bundle, args: argparse.Namespace) -> int:
    """Print `folder<TAB>description` for every indexed folder (used for search contexts)."""
    for folder in indexgen.folders_to_index(bundle):
        if folder:
            spec = bundle.config.folder_spec(folder) or {}
            print(f"{folder}\t{spec.get('title', folder)}: {spec.get('description', '')}")
    return 0


def _cmd_hook(bundle: Bundle, args: argparse.Namespace) -> int:
    return hooks.post_edit(bundle) if args.event == "post-edit" else hooks.stop(bundle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kb", description=__doc__)
    parser.add_argument("--bundle", help="bundle root (default: <repo>/kb)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check", help="validate OKF conformance and house rules")
    p.add_argument("paths", nargs="*", help="only check these files (skips bundle-level checks)")
    p.add_argument("--strict", action="store_true", help="fail on warnings too")
    p.add_argument("--errors-only", action="store_true", help="print errors only")
    p.set_defaults(func=_cmd_check)

    p = sub.add_parser("index", help="regenerate every index.md from frontmatter")
    p.add_argument("--check", action="store_true", help="only report out-of-date index files")
    p.set_defaults(func=_cmd_index)

    p = sub.add_parser("fix-links", help="rewrite internal links as bundle-absolute /paths")
    p.add_argument("paths", nargs="*")
    p.set_defaults(func=_cmd_fix_links)

    p = sub.add_parser("mv", help="move/rename a page, rewrite inbound links, regenerate indexes")
    p.add_argument("old", help="bundle-relative path of the page")
    p.add_argument("new", help="new bundle-relative path")
    p.set_defaults(func=_cmd_mv)

    p = sub.add_parser("log", help="add an entry to kb/log.md under today's date")
    p.add_argument("op", help=f"operation, e.g. {', '.join(pages.LOG_OPS)}")
    p.add_argument("message", nargs="+", help="entry text; link pages as [Title](/path.md)")
    p.set_defaults(func=_cmd_log)

    p = sub.add_parser("new", help="create a page skeleton with valid frontmatter")
    p.add_argument("type", help="a type from schema/vocabulary.yaml")
    p.add_argument("path", help="bundle-relative path, e.g. systems/networking/dns.md")
    p.add_argument("--title", required=True)
    p.add_argument("--description", required=True, help="one sentence")
    p.add_argument("--tags", help="comma-separated kebab-case tags")
    p.add_argument("--status", default="stable", choices=["draft", "stable", "deprecated"])
    p.add_argument("--resource", help="canonical URL (required for Source pages)")
    p.add_argument("--by", help="actor, e.g. claude-code/<model> (default: $KB_ACTOR)")
    p.set_defaults(func=_cmd_new)

    p = sub.add_parser("report", help="health report: trust, staleness, orphans, gaps")
    p.set_defaults(func=_cmd_report)

    p = sub.add_parser("find", help="list pages by frontmatter (type, tags, status, folder, trust)")
    p.add_argument("--type")
    p.add_argument("--tag", action="append", help="repeatable; all must match")
    p.add_argument("--status", choices=["draft", "stable", "deprecated"])
    p.add_argument("--folder", help="bundle-relative folder prefix, e.g. systems")
    p.add_argument("--trust", choices=["unverified", "machine-confirmed", "human-reviewed"])
    p.set_defaults(func=_cmd_find)

    p = sub.add_parser("folders", help="print folder<TAB>description for every indexed folder")
    p.set_defaults(func=_cmd_folders)

    p = sub.add_parser("hook", help="Claude Code hook entry points")
    p.add_argument("event", choices=["post-edit", "stop"])
    p.set_defaults(func=_cmd_hook)

    args = parser.parse_args(argv)
    bundle = Bundle.discover(args.bundle)
    return args.func(bundle, args)


if __name__ == "__main__":
    raise SystemExit(main())
