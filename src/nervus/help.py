"""Help text for blocks, generated from their docstrings and parameter declarations.

The same Markdown is used for the generated block reference (``docs/blocks``) and for the in-app help.
"""

from __future__ import annotations

import inspect
import math
import re

from nervus.blocks.registry import categories
from nervus.core.block import Block
from nervus.core.params import Param, ParamKind


def _fmt_default(p: Param) -> str:
    v = p.default
    if p.kind is ParamKind.CODE:
        return "*(code)*"
    if isinstance(v, float) and math.isinf(v):
        return "inf" if v > 0 else "-inf"
    if p.kind is ParamKind.SAMPLE_TIME and v == -1:
        return "-1 (inherited)"
    return f"`{v!r}`" if isinstance(v, str) else f"`{v}`"


def block_doc(cls: type[Block]) -> str:
    """The block's docstring, dedented, with Sphinx-style roles turned into plain code."""
    doc = inspect.cleandoc(cls.__doc__ or "")
    return re.sub(r":\w+:`([^`]+)`", r"`\1`", doc)


def block_help_markdown(cls: type[Block], heading_level: int = 2) -> str:
    h = "#" * heading_level
    lines = [f"{h} {cls.label}", "", f"`{cls.type_id}` · {cls.category}", "", block_doc(cls), ""]
    if cls.PARAMS:
        lines += [f"{h}# Parameters", "", "| Name | Default | Unit | Description |", "|---|---|---|---|"]
        for p in cls.PARAMS:
            desc = p.description
            if p.choices:
                desc += " — one of " + ", ".join(f"`{c}`" for c in p.choices)
            lines.append(f"| `{p.name}` | {_fmt_default(p)} | {p.unit} | {desc} |")
        lines.append("")
    ports = []
    if cls.NUM_INPUTS == 0:
        ports.append("no inputs")
    if cls.NUM_OUTPUTS == 0:
        ports.append("no outputs")
    if cls.direct_feedthrough is not Block.direct_feedthrough:
        feed = "depends on parameters"
    else:
        feed = "yes" if cls.DIRECT_FEEDTHROUGH else "no"
    lines += [f"*Direct feedthrough:* {feed}" + (f" · {', '.join(ports)}" if ports else ""), ""]
    return "\n".join(lines)


def category_slug(category: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", category.lower()).strip("-")


def reference_pages() -> dict[str, str]:
    """Markdown pages for the block reference, keyed by file name."""
    pages: dict[str, str] = {}
    cats = dict(sorted(categories().items()))
    index = [
        "# Block reference",
        "",
        "This reference is generated from the block source code (`scripts/gen_block_reference.py`).",
        "",
    ]
    for cat, classes in cats.items():
        slug = category_slug(cat)
        index.append(f"## [{cat}]({slug}.md)\n")
        index += [f"- **{c.label}**: {block_doc(c).splitlines()[0]}" for c in classes]
        index.append("")
        body = [f"# {cat}", ""]
        for c in classes:
            body.append(block_help_markdown(c))
            body.append("---\n")
        pages[f"{slug}.md"] = "\n".join(body)
    pages["index.md"] = "\n".join(index)
    return pages
