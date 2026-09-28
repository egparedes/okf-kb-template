"""`kb` command line: validate, index, fix links, log, create pages, report."""

from __future__ import annotations

import argparse
import sys

import json
import subprocess
from pathlib import Path

from . import dupes, graph, hooks, importer, indexgen, linkfix, obsidian, pages, rename, report, resources, search, unlinked
from .bundle import Bundle
from .check import Checker, exit_code


def _cmd_check(bundle: Bundle, args: argparse.Namespace) -> int:
    checker = Checker(bundle)
    if args.paths:
        paths = [bundle.path_arg(p) for p in args.paths if p.endswith(".md")]
        missing = [arg for arg, path in zip([p for p in args.paths if p.endswith(".md")], paths, strict=True) if path is None]
        for arg in missing:
            print(f"kb: {arg} is not a file in the bundle", file=sys.stderr)
        if missing and not any(paths):
            return 1
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
        print(f"fixed links in {bundle.show(doc.rel)}")
    return 0


def _cmd_mv(bundle: Bundle, args: argparse.Namespace) -> int:
    for rel in linkfix.move(bundle, args.old, args.new):
        print(f"updated links in {bundle.show(rel)}")
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
        if args.folder and not str(doc.rel).startswith(bundle.rel(args.folder).strip("/") + "/"):
            continue
        if args.trust and report.trust_tier(doc) != args.trust:
            continue
        print(f"/{doc.rel}\t{doc.type}\t{doc.title}")
    return 0


def _cmd_folders(bundle: Bundle, args: argparse.Namespace) -> int:
    """Print `folder<TAB>description` for every indexed folder (used for search contexts)."""
    for folder, description in _folder_contexts(bundle):
        print(f"{folder}\t{description}")
    return 0


def _cmd_graph(bundle: Bundle, args: argparse.Namespace) -> int:
    result = graph.analyze(bundle, scope=args.scope, top=args.top)
    print(json.dumps(result, indent=2) if args.json else graph.to_markdown(result), end="" if not args.json else "\n")
    return 0


def _cmd_dupes(bundle: Bundle, args: argparse.Namespace) -> int:
    found = dupes.find(bundle, min_score=args.min_score, body=args.body, scope=args.scope)
    if args.json:
        print(json.dumps([c.__dict__ for c in found], indent=2))
    for c in [] if args.json else found:
        print(f"{c.score:.2f}  /{c.a}  <->  /{c.b}  [{'; '.join(c.signals)}]")
    if not args.json:
        print(f"kb dupes: {len(found)} candidate pair(s)", file=sys.stderr)
    return 0


def _cmd_unlinked(bundle: Bundle, args: argparse.Namespace) -> int:
    found = unlinked.find(bundle, only=args.pages or None, min_len=args.min_len, include_personal=args.all)
    if args.json:
        print(json.dumps([m.__dict__ for m in found], indent=2))
    else:
        for m in found:
            print(f"{m.page}:{m.line}  \"{m.text}\" -> {m.target}\n    {m.snippet}")
        _, ambiguous = unlinked.vocabulary(bundle, args.min_len)
        for name, owners in [] if args.pages else sorted(ambiguous.items()):
            print(f"ambiguous name \"{name}\": {', '.join('/' + o for o in owners)} (add distinguishing titles or aliases)")
        print(f"kb unlinked: {len(found)} unlinked mention(s)", file=sys.stderr)
    return 0


def _cmd_merge(bundle: Bundle, args: argparse.Namespace) -> int:
    for line in linkfix.merge(bundle, args.old, args.into, pages.resolve_actor(args.by), dry_run=args.dry_run):
        print(line)
    if not args.dry_run:
        indexgen.write(Bundle(bundle.root, bundle.repo_root))
    return 0


def _cmd_zotero(bundle: Bundle, args: argparse.Namespace) -> int:
    settings = resources.Settings.load(bundle)
    zotero = resources.Zotero(settings)
    if args.action == "search":
        for item in zotero.search(" ".join(args.query), limit=args.limit):
            year = (item.get("date") or "")[:4]
            print(f"{item.get('key')}\t{resources._citekey(item) or '-'}\t{year}\t{item.get('title', '')}")
        return 0
    item = zotero.item(args.query[0])
    if args.action == "show":
        print(json.dumps(item, indent=2, ensure_ascii=False))
        return 0
    fm = resources.zotero_source_frontmatter(item, settings)
    slug = args.path or f"sources/{resources.zotero_citekey_slug(item)}.md"
    link = resources.open_target(bundle, f"zotero:{item['key']}")
    path = pages.new_page(
        bundle, "Source", slug, fm.pop("title"), fm.pop("description"),
        [t.strip() for t in (args.tags or "").split(",") if t.strip()], args.by,
        status="draft", resource=fm.pop("resource"), extra=fm,
        body_intro=f"Open in Zotero: [{item['key']}]({link})\n\n",
    )
    print(path.relative_to(bundle.repo_root))
    return 0


def _cmd_karakeep(bundle: Bundle, args: argparse.Namespace) -> int:
    resources.load_env(bundle.repo_root)
    keep = resources.KaraKeep()
    bookmark_id = keep.find(args.url)
    if bookmark_id:
        print(f"already saved: {bookmark_id}")
    else:
        print(f"saved: {keep.save(args.url)} (archiving runs in the background)")
    return 0


def _cmd_fetch(bundle: Bundle, args: argparse.Namespace) -> int:
    out = resources.fetch(bundle, args.ref, bundle.repo_root / ".cache" / "sources")
    print(out.relative_to(bundle.repo_root))
    return 0


def _cmd_open(bundle: Bundle, args: argparse.Namespace) -> int:
    target = resources.open_target(bundle, args.ref)
    if args.print:
        print(target)
        return 0
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=resources.child_env())
    print(target)
    return 0


def _cmd_import(bundle: Bundle, args: argparse.Namespace) -> int:
    mapping = importer.Mapping.load(Path(args.map), args.by)
    redirects = Path(args.redirects) if args.redirects else None
    plan, lines = importer.run(bundle, Path(args.source), args.into, mapping, args.dry_run, redirects)
    print("\n".join(lines))
    if plan.errors:
        return 1
    if args.dry_run:
        print("(dry run: nothing written)")
    else:
        for path in indexgen.write(Bundle(bundle.root, bundle.repo_root)):
            print(f"wrote {path.relative_to(bundle.repo_root)}")
    return 0


def _cmd_obsidian(bundle: Bundle, args: argparse.Namespace) -> int:
    add = [p.strip() for p in (args.add or "").split(",") if p.strip()]
    return obsidian.setup(bundle, add, force=args.force, open_vault=args.open)


def _cmd_setup(bundle: Bundle, args: argparse.Namespace) -> int:
    """First-time setup of a clone: git repository, pre-commit hooks, indexes (uv has synced the tools)."""
    repo = bundle.repo_root
    if subprocess.run(["git", "rev-parse", "--git-dir"], cwd=repo, capture_output=True, check=False).returncode != 0:
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        print("initialized a git repository", flush=True)
    subprocess.run([sys.executable, "-m", "pre_commit", "install"], cwd=repo, check=True)
    for path in indexgen.write(bundle):
        print(f"wrote {path.relative_to(repo)}")
    return 0


def _folder_contexts(bundle: Bundle) -> list[tuple[str, str]]:
    out = []
    for folder in indexgen.folders_to_index(bundle):
        if folder:
            spec = bundle.config.folder_spec(folder) or {}
            out.append((folder, f"{spec.get('title', folder)}: {spec.get('description', '')}"))
    return out


def _cmd_search(bundle: Bundle, args: argparse.Namespace) -> int:
    if (args.setup or args.reindex) and args.query:
        raise SystemExit("kb search: --setup and --reindex take no query")
    if args.setup:
        return search.setup(bundle, _folder_contexts(bundle))
    if args.reindex:
        return search.reindex()
    if not " ".join(args.query).strip():
        raise SystemExit("kb search: give a query (or --setup / --reindex)")
    return search.search(bundle, " ".join(args.query))


def _cmd_rename_bundle(bundle: Bundle, args: argparse.Namespace) -> int:
    return rename.rename(bundle, args.new)


def _cmd_hook(bundle: Bundle, args: argparse.Namespace) -> int:
    return hooks.post_edit(bundle) if args.event == "post-edit" else hooks.stop(bundle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kb", description=__doc__)
    parser.add_argument("--bundle", help="bundle root (default: the folder named in [tool.kb] bundle, else <repo>/kb)")
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

    p = sub.add_parser("log", help="add an entry to the bundle's log.md under today's date")
    p.add_argument("op", help=f"operation, e.g. {', '.join(pages.LOG_OPS)}")
    p.add_argument("message", nargs="+", help="entry text; link pages as [Title](/path.md)")
    p.set_defaults(func=_cmd_log)

    p = sub.add_parser("new", help="create a page skeleton with valid frontmatter")
    p.add_argument("type", help="a type from schema/vocabulary.yaml")
    p.add_argument("path", help="bundle-relative path, e.g. systems/networking/dns.md")
    p.add_argument("--title", required=True)
    p.add_argument("--description", required=True, help="one sentence")
    p.add_argument("--tags", help="comma-separated kebab-case tags")
    p.add_argument("--status", default="draft", choices=["draft", "stable", "deprecated"],
                   help="new pages start as draft; set stable when complete")
    p.add_argument("--resource", help="canonical URL (required for Source pages)")
    p.add_argument("--by", help="actor, e.g. claude-code/<model> (default: $KB_ACTOR)")
    p.set_defaults(func=_cmd_new)

    p = sub.add_parser("report", help="health report: trust, staleness, uncited pages, wanted pages")
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

    p = sub.add_parser("graph", help="link-graph analytics (generated index hubs excluded)")
    p.add_argument("--scope", choices=["knowledge", "all"], default="knowledge",
                   help="all = include personal areas (projects, journal, ...)")
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_graph)

    p = sub.add_parser("dupes", help="near-duplicate page candidates (read-only)")
    p.add_argument("--min-score", type=float, default=0.6)
    p.add_argument("--body", action="store_true", help="also compare page text (slower)")
    p.add_argument("--scope", choices=["knowledge", "all"], default="knowledge")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_dupes)

    p = sub.add_parser("unlinked", help="mentions of other pages that are not linked (read-only)")
    p.add_argument("pages", nargs="*", help="only scan these pages (bundle paths)")
    p.add_argument("--min-len", type=int, default=4, help="ignore shorter names (all-caps aliases excepted)")
    p.add_argument("--all", action="store_true", help="also scan personal areas")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_unlinked)

    p = sub.add_parser("merge", help="fold a duplicate page into another (after merging the text by hand)")
    p.add_argument("old", help="page to remove")
    p.add_argument("into", help="page that absorbs it")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--by", help="actor for generated.by (default: $KB_ACTOR)")
    p.set_defaults(func=_cmd_merge)

    p = sub.add_parser("zotero", help="read-only Zotero access (local API, then web API)")
    p.add_argument("action", choices=["search", "show", "new-source"])
    p.add_argument("query", nargs="+", help="search words, or an item key / citation key")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--path", help="new-source: bundle path (default sources/<slug>.md, the kebab-case citation key)")
    p.add_argument("--tags", help="new-source: comma-separated tags")
    p.add_argument("--by", help="new-source: actor (default: $KB_ACTOR)")
    p.set_defaults(func=_cmd_zotero)

    p = sub.add_parser("karakeep", help="archive a web page in KaraKeep (cloud or self-hosted)")
    p.add_argument("action", choices=["save"])
    p.add_argument("url")
    p.set_defaults(func=_cmd_karakeep)

    p = sub.add_parser("fetch", help="text of an external resource into .cache/sources/")
    p.add_argument("ref", help="zotero:<key|citekey>, file:<root>/<path>, or a web URL (via KaraKeep)")
    p.set_defaults(func=_cmd_fetch)

    p = sub.add_parser("open", help="open an external resource (zotero://, file, URL)")
    p.add_argument("ref")
    p.add_argument("--print", action="store_true", help="only print what would be opened")
    p.set_defaults(func=_cmd_open)

    p = sub.add_parser("import", help="convert an Obsidian vault or Logseq graph into the bundle (see docs/importing.md)")
    p.add_argument("source", help="vault or graph directory (never modified)")
    p.add_argument("--into", required=True, help="bundle folder that relative `to` paths start from")
    p.add_argument("--map", required=True, help="mapping file (YAML): rules for paths, types and properties")
    p.add_argument("--dry-run", action="store_true", help="print the plan and issues, write nothing")
    p.add_argument("--by", help="actor for generated.by (default: `actor` in the mapping)")
    p.add_argument("--redirects", help="where to write the source -> bundle path table (default .cache/import/)")
    p.set_defaults(func=_cmd_import)

    p = sub.add_parser("obsidian", help="install the vault's pinned community plugins (see docs)")
    p.add_argument("action", choices=["setup"])
    p.add_argument("--add", help="comma-separated optional plugin ids to add, e.g. omnisearch,obsidian-linter")
    p.add_argument("--force", action="store_true", help="download again even if the pinned version is installed")
    p.add_argument("--open", action="store_true", help="then open the vault in Obsidian (obsidian:// URI)")
    p.set_defaults(func=_cmd_obsidian)

    p = sub.add_parser("setup", help="first-time setup of a clone: git repository, pre-commit hooks, indexes")
    p.set_defaults(func=_cmd_setup)

    p = sub.add_parser("search", help="search: qmd hybrid search when set up, otherwise a text search")
    p.add_argument("query", nargs="*", help="words to search for")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--setup", action="store_true", help="one-time qmd setup: collection, folder contexts, embeddings")
    mode.add_argument("--reindex", action="store_true", help="refresh the qmd index after changes")
    p.set_defaults(func=_cmd_search)

    p = sub.add_parser("rename-bundle", help="rename the knowledge-base folder (and Obsidian vault); close Obsidian first")
    p.add_argument("new", help="new folder name (kebab-case)")
    p.set_defaults(func=_cmd_rename_bundle)

    p = sub.add_parser("hook", help="Claude Code hook entry points")
    p.add_argument("event", choices=["post-edit", "stop"])
    p.set_defaults(func=_cmd_hook)

    args = parser.parse_args(argv)
    bundle = Bundle.discover(args.bundle)
    resources.load_env(bundle.repo_root)  # .env settings such as KB_ACTOR apply to every command
    return args.func(bundle, args)


if __name__ == "__main__":
    raise SystemExit(main())
