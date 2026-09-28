"""Markdown link and footnote extraction that ignores code and comments.

The scanners work on a masked copy of the text (`mask`): code, HTML comments
and backslash escapes are blanked out with the same length, so offsets and
line numbers found in the masked text hold in the original. Line numbers
count `\\n` only (never `str.splitlines`, which also splits on U+2028 or \\f).
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from urllib.parse import quote, unquote

_FENCE = re.compile(r"^([ \t]*)(`{3,}|~{3,})(.*)$")
_LIST_ITEM = re.compile(r"^[ \t]*(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$)")
_FOOTNOTE_DEF_START = re.compile(r"^ {0,3}\[\^[^\]]+\]:")  # its indented continuation is not code
_BLANK_LINE = re.compile(r"(\n[ \t]*\n)")
# A code span: a backtick run, content, the next run of the same length (CommonMark 6.1).
_INLINE_CODE = re.compile(r"(?<![`\\])(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
# Backslash escapes of the characters that open links and footnotes; `\\` is a pair of its own.
_ESCAPE = re.compile(r"\\[\\\[\]!]")
_ESCAPE_MASK = "\x1a"
# Link text: no blank line (a soft line break is fine); one level of nested brackets.
_TEXT_CHAR = r"(?:[^\[\]\n]|\n(?![ \t]*\n))"
# [text](target "optional title") and ![alt](target)
_LINK = re.compile(
    rf"(?P<bang>!?)\[(?P<text>(?:{_TEXT_CHAR}|\[{_TEXT_CHAR}*\])*)\]"
    r"\(\s*(?P<target><[^<>\n]*>|[^()\s]+(?:\([^()\s]*\)[^()\s]*)*)(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^()\n]*\)))?\s*\)"
)
_FOOTNOTE_REF = re.compile(r"\[\^(?P<label>[^\]\s]+)\](?!:)")
_FOOTNOTE_DEF = re.compile(r"^\[\^(?P<label>[^\]\s]+)\]:.*$", re.M)
_REF_DEF = re.compile(r"^ {0,3}\[(?!\^)(?P<label>[^\]\n]+)\]:[ \t]*\n?[ \t]*<?(?P<target>[^\s>]+)>?.*$", re.M)
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def mask_code(text: str) -> str:
    """Blank out fenced and indented code, inline code and HTML comments, preserving offsets.

    Fences may be indented (list items, footnotes); the closing fence uses the
    same character, at least as long, indented less than 4 columns deeper than
    the opening one. A fence opened inside a list ends early at the first line
    indented less than itself (the list item ended). An indented code block
    needs a blank line before it and is not recognised inside a list or a
    footnote definition, where indentation means a continuation paragraph.
    """
    out: list[str] = []
    fence: str | None = None
    fence_indent = 0
    fence_in_list = False  # a fence in a container ends with the container
    in_list = False
    prev_blank = True
    indented_code = False
    for line in _lines(text):
        content = line.rstrip("\r\n")
        indent = 0
        if content[:1] in (" ", "\t"):
            expanded = content.expandtabs(4)
            indent = len(expanded) - len(expanded.lstrip())
        if fence is not None:
            if not (fence_in_list and content.strip() and indent < fence_indent):
                match = _FENCE.match(content) if fence[0] in content else None
                if (
                    match
                    and match.group(2).startswith(fence)
                    and not match.group(3).strip()
                    and indent < fence_indent + 4
                ):
                    fence = None
                out.append(_blank(line))
                continue
            fence = None  # the list item ended: this line is outside the fence
        if not content.strip():
            prev_blank = True
            out.append(line)
            continue
        if (indented_code and indent >= 4) or (indent >= 4 and prev_blank and not in_list):
            indented_code = True
            out.append(_blank(line))
            continue
        indented_code = False
        match = _FENCE.match(content) if ("```" in content or "~~~" in content) else None
        if match and not (match.group(2)[0] == "`" and "`" in match.group(3)):
            fence, fence_indent, fence_in_list = match.group(2), indent, in_list and indent > 0
            prev_blank = False
            out.append(_blank(line))
            continue
        if _LIST_ITEM.match(content) or _FOOTNOTE_DEF_START.match(content):
            in_list = True
        elif indent == 0 and prev_blank:
            in_list = False
        prev_blank = False
        out.append(line)
    masked = "".join(out)
    if "`" in masked:
        # Code spans never cross a blank line. Other paragraph ends (a heading,
        # a list item) are not detected, so a span may still cross those.
        parts = _BLANK_LINE.split(masked)
        masked = "".join(_INLINE_CODE.sub(lambda m: _blank(m.group(0)), part) for part in parts)
    if "<!--" in masked:
        masked = _HTML_COMMENT.sub(lambda m: _blank(m.group(0)), masked)
    return masked


def _lines(text: str) -> list[str]:
    """Lines split on `\\n` only, with their line ends."""
    lines = [line + "\n" for line in text.split("\n")]
    lines[-1] = lines[-1][:-1]
    return lines if lines[-1] else lines[:-1]


def mask(text: str) -> str:
    """`mask_code` plus backslash escapes (`\\[`, `\\]`, `\\!`, `\\\\`): the text the scanners read."""
    masked = mask_code(text)
    if "\\" in masked:
        masked = _ESCAPE.sub(_ESCAPE_MASK * 2, masked)
    return masked


def _blank(s: str) -> str:
    return "".join(c if c == "\n" else " " for c in s)


def line_at(text: str, offset: int) -> int:
    """1-based line number of an offset (lines end at `\\n` only)."""
    return text.count("\n", 0, offset) + 1


class _Target:
    """Shared reading of a link target (`target` as written, angle brackets stripped)."""

    target: str

    @property
    def is_external(self) -> bool:
        return bool(_SCHEME.match(self.target)) or self.target.startswith("//")

    @property
    def is_anchor_only(self) -> bool:
        return self.target.startswith("#")

    @property
    def is_internal(self) -> bool:
        """A link to a file of the bundle (not external, not only an anchor, has a path)."""
        return not self.is_external and not self.is_anchor_only and bool(self.path)

    @property
    def path(self) -> str:
        return unquote(self.target.split("#", 1)[0])

    @property
    def fragment(self) -> str:
        return self.target.split("#", 1)[1] if "#" in self.target else ""


@dataclass
class Link(_Target):
    text: str
    target: str  # raw target as written (angle brackets stripped)
    start: int  # offset of the target in the scanned text
    end: int
    line: int  # 1-based line number within the scanned text
    image: bool


@dataclass
class Relation(_Target):
    """A frontmatter value `[text](target)`, e.g. an item of a relation key."""

    key: str
    text: str
    target: str


@dataclass
class RefDef:
    """A reference-style link definition `[label]: target`."""

    label: str
    target: str
    line: int
    start: int  # span of the whole definition
    end: int


def find_links(text: str, masked: str | None = None) -> list[Link]:
    """Inline links and images, including an image inside a link's text (`[![alt](img)](page)`).

    Text and targets are read from `text`; `masked` (from `mask(text)`) is where they are found.
    """
    if masked is None:
        masked = mask(text)
    links: list[Link] = []
    _scan_links(text, masked, 0, len(masked), links)
    links.sort(key=lambda link: link.start)
    return links


def _scan_links(text: str, masked: str, pos: int, endpos: int, links: list[Link]) -> None:
    for m in _LINK.finditer(masked, pos, endpos):
        start, end = m.start("target"), m.end("target")
        raw = text[start:end]
        if raw.startswith("<") and raw.endswith(">"):
            raw, start, end = raw[1:-1], start + 1, end - 1
        links.append(
            Link(
                text=text[m.start("text") : m.end("text")],
                target=raw,
                start=start,
                end=end,
                line=line_at(masked, m.start()),
                image=bool(m.group("bang")),
            )
        )
        if "](" in m.group("text"):
            _scan_links(text, masked, m.start("text"), m.end("text"), links)


def footnote_refs(text: str, masked: str | None = None) -> list[tuple[str, int]]:
    masked = mask(text) if masked is None else masked
    return [(m.group("label"), line_at(masked, m.start())) for m in _FOOTNOTE_REF.finditer(masked)]


def footnote_defs(text: str, masked: str | None = None) -> set[str]:
    return {m.group("label") for m in _FOOTNOTE_DEF.finditer(mask(text) if masked is None else masked)}


def ref_defs(text: str, masked: str | None = None) -> list[RefDef]:
    """Reference-style link definitions (`[label]: target`), outside code."""
    masked = mask(text) if masked is None else masked
    return [
        RefDef(
            m.group("label"), text[m.start("target") : m.end("target")], line_at(masked, m.start()), m.start(), m.end()
        )
        for m in _REF_DEF.finditer(masked)
    ]


def reference_definitions(text: str) -> list[int]:
    """Line numbers of reference-style link definitions (`[label]: target`)."""
    return [d.line for d in ref_defs(text)]


_RELATION = re.compile(r"^\[(?P<text>[^\]]+)\]\((?P<target><[^<>\n]*>|[^()\s]+)\)$")


def parse_relation(key: str, value: object) -> Relation | None:
    """A frontmatter string `[text](target)` as a Relation, else None."""
    if not isinstance(value, str):
        return None
    m = _RELATION.match(value.strip())
    if not m:
        return None
    target = m.group("target")
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    return Relation(key=key, text=m.group("text"), target=target)


def resolve(link_path: str, source_folder: str) -> str | None:
    """Bundle-relative path a link points to, or None if it escapes the bundle.

    `/x.md` is bundle-root-absolute (OKF §6.1); anything else is relative to the
    folder of the linking file.
    """
    if link_path.startswith("/"):
        joined = link_path.lstrip("/")
    else:
        joined = posixpath.join(source_folder, link_path) if source_folder else link_path
    normalized = posixpath.normpath(joined)
    if normalized == "." or normalized == ".." or normalized.startswith("../"):
        return None if normalized != "." else ""
    return normalized


def encode_path(path: str) -> str:
    return quote(path, safe="/-._~!$&'()*+,;=:@")
