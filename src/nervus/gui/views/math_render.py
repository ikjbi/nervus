"""Render the LaTeX equations in help pages to images, so the in-app help shows real typeset math.

Qt's Markdown renderer has no math support. Each ``$$ ... $$`` block is rendered with matplotlib's built-in
math engine (no TeX installation needed) and registered as an image resource on the help document. If
rendering fails, the equation falls back to readable plain text.
"""

from __future__ import annotations

import hashlib
import io
import re

from PySide6.QtGui import QImage

from nervus.help import latex_to_text


def _mathtext(tex: str) -> list[str]:
    """Adapt LaTeX to matplotlib mathtext. Returns one or more lines (``cases`` is split into lines)."""
    tex = re.sub(r"\\(ge|le)(?![a-zA-Z])", r"\\\1q", tex.strip())  # \ge -> \geq, \le -> \leq
    m = re.search(r"\\begin\{cases\}(.*)\\end\{cases\}", tex, re.S)
    if m:
        prefix = tex[: m.start()].strip()
        rows = [r.strip() for r in m.group(1).split(r"\\") if r.strip()]
        lines = []
        for i, row in enumerate(rows):
            row = row.replace("&", r"\quad ")
            lead = prefix if i == 0 else r"\phantom{" + prefix + "}"
            lines.append(f"{lead} {row}")
        return lines
    return [line.strip().rstrip(",") for line in re.split(r"\\qquad", tex) if line.strip().rstrip(",")]


def render_latex(tex: str, color: str, dpi: int = 250) -> list[QImage]:
    """Render ``tex`` to images (one per line). Raises on failure."""
    from matplotlib.mathtext import math_to_image  # imported lazily: matplotlib is slow to import

    images = []
    for line in _mathtext(tex):
        buf = io.BytesIO()
        math_to_image(f"${line}$", buf, dpi=dpi, format="png", color=color)
        img = QImage.fromData(buf.getvalue())  # format auto-detected (PNG)
        if img.isNull():
            raise ValueError("could not render equation")
        img.setDevicePixelRatio(2.0)
        images.append(img)
    return images


def markdown_with_math(markdown: str, images: dict[str, QImage], color: str) -> str:
    """Replace ``$$...$$`` blocks with image references (the images are added to ``images``, keyed by URL);
    inline ``$...$`` becomes code."""

    def block(m: re.Match[str]) -> str:
        tex = m.group(1)
        try:
            rendered = render_latex(tex, color)
        except Exception:
            return "\n\n```\n" + latex_to_text(tex) + "\n```\n\n"
        refs = []
        for i, img in enumerate(rendered):
            key = "math:" + hashlib.sha1(f"{color}{tex}{i}".encode()).hexdigest()[:16]
            images[key] = img
            refs.append(f"![equation]({key})")
        return "\n\n" + "\n\n".join(refs) + "\n\n"

    out = re.sub(r"\$\$(.+?)\$\$", block, markdown, flags=re.S)
    out = re.sub(r"(?<![\$\\])\$([^$\n]+)\$", lambda m: "`" + latex_to_text(m.group(1)) + "`", out)
    return out
