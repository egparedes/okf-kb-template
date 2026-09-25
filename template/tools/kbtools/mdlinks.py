"""Markdown link and footnote extraction that ignores code and comments."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from urllib.parse import quote, unquote

_FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})")
_INLINE_CODE = re.compile(r"(`+)(?:(?!\1).)+?\1", re.S)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
# [text](target "optional title") and ![alt](target); text may hold one level of nested brackets.
_LINK = re.compile(
    r"(?P<bang>!?)\[(?P<text>(?:[^\[\]\n]|\[[^\[\]\n]*\])*)\]"
    r"\(\s*(?P<target><[^<>\n]*>|[^()\s]+(?:\([^()\s]*\)[^()\s]*)*)(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^()\n]*\)))?\s*\)"
)
_FOOTNOTE_REF = re.compile(r"\[\^(?P<label>[^\]\s]+)\](?!:)")
_FOOTNOTE_DEF = re.compile(r"^\[\^(?P<label>[^\]\s]+)\]:", re.M)
_REF_DEF = re.compile(r"^ {0,3}\[(?!\^)[^\]]+\]:\s*\S+", re.M)
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def mask_code(text: str) -> str:
    """Blank out fenced code, inline code and HTML comments, preserving offsets."""
    out: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        match = _FENCE.match(line)
        if fence is None and match:
            fence = match.group(2)[0] * len(match.group(2))
            out.append(_blank(line))
            continue
        if fence is not None:
            if match and match.group(2).startswith(fence) and not line.strip().strip(fence[0]):
                fence = None
            out.append(_blank(line))
            continue
        out.append(line)
    masked = "".join(out)
    masked = _INLINE_CODE.sub(lambda m: _blank(m.group(0)), masked)
    return _HTML_COMMENT.sub(lambda m: _blank(m.group(0)), masked)


def _blank(s: str) -> str:
    return "".join(c if c == "\n" else " " for c in s)


@dataclass
class Link:
    text: str
    target: str  # raw target as written (angle brackets stripped)
    start: int  # offset of the target in the scanned text
    end: int
    line: int  # 1-based line number within the scanned text
    image: bool

    @property
    def is_external(self) -> bool:
        return bool(_SCHEME.match(self.target)) or self.target.startswith("//")

    @property
    def is_anchor_only(self) -> bool:
        return self.target.startswith("#")

    @property
    def path(self) -> str:
        return unquote(self.target.split("#", 1)[0])

    @property
    def fragment(self) -> str:
        return self.target.split("#", 1)[1] if "#" in self.target else ""


def find_links(text: str) -> list[Link]:
    masked = mask_code(text)
    links = []
    for m in _LINK.finditer(masked):
        raw = m.group("target")
        start, end = m.start("target"), m.end("target")
        if raw.startswith("<") and raw.endswith(">"):
            raw, start, end = raw[1:-1], start + 1, end - 1
        links.append(
            Link(
                text=m.group("text"),
                target=raw,
                start=start,
                end=end,
                line=masked.count("\n", 0, m.start()) + 1,
                image=bool(m.group("bang")),
            )
        )
    return links


def footnote_refs(text: str) -> list[tuple[str, int]]:
    masked = mask_code(text)
    return [(m.group("label"), masked.count("\n", 0, m.start()) + 1) for m in _FOOTNOTE_REF.finditer(masked)]


def footnote_defs(text: str) -> set[str]:
    return {m.group("label") for m in _FOOTNOTE_DEF.finditer(mask_code(text))}


def reference_definitions(text: str) -> list[int]:
    """Line numbers of reference-style link definitions (`[label]: target`)."""
    masked = mask_code(text)
    return [masked.count("\n", 0, m.start()) + 1 for m in _REF_DEF.finditer(masked)]


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
