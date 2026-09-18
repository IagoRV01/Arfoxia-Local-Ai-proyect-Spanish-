"""Keep literal CommonMark code out of prose/link rewriting."""
from __future__ import annotations

import re
import uuid

from markdown_it import MarkdownIt
from markdown_it.rules_inline.backticks import backtick


_blocks = MarkdownIt("commonmark", {"html": False})
_inline = MarkdownIt("commonmark", {"html": False})


def _record_code(state, silent):
    start = state.pos
    before = len(state.tokens)
    found = backtick(state, silent)
    if found and not silent and len(state.tokens) > before and state.tokens[-1].type == "code_inline":
        state.env["code_spans"].append((start, state.pos))
    return found


_inline.inline.ruler.at("backticks", _record_code)


def protect_code(source: str) -> tuple[str, dict[str, str]]:
    """Mask only parsed code; restore it byte-for-byte after filtering prose.

    CommonMark block maps handle fenced, unclosed, indented and quoted code.
    Inline positions are collected within each actual block, never across a
    paragraph boundary. Random placeholders cannot be forged by model output.
    """
    offsets = [0]
    offsets.extend(match.end() for match in re.finditer(r"\r\n|\r|\n", source))
    if offsets[-1] < len(source):
        offsets.append(len(source))
    ranges: list[tuple[int, int]] = []
    for token in _blocks.parse(source):
        if not token.map:
            continue
        start, end = (offsets[index] for index in token.map)
        if token.type in {"fence", "code_block"}:
            ranges.append((start, end))
        elif token.type == "inline" and any(child.type == "code_inline" for child in token.children or []):
            environment: dict = {"code_spans": []}
            _inline.inline.parse(source[start:end], _inline, environment, [])
            ranges.extend((start + left, start + right) for left, right in environment["code_spans"])
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    nonce = uuid.uuid4().hex
    replacements: dict[str, str] = {}
    for index, (start, end) in reversed(list(enumerate(merged))):
        raw = source[start:end]
        key = f"ARFOXIALITERAL{nonce}X{index}END" + "\n" * raw.count("\n")
        replacements[key] = raw
        source = source[:start] + key + source[end:]
    return source, replacements


def restore_code(source: str, replacements: dict[str, str]) -> str:
    for key, raw in replacements.items():
        source = source.replace(key, raw)
    return source
