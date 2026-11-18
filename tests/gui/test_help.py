"""Every equation and figure referenced by the block help must render, in the app and in the docs."""

import re
from importlib import resources

import pytest

from nervus.blocks import block_types
from nervus.help import block_doc

EQUATIONS = [
    (cls.__name__, tex) for cls in block_types().values() for tex in re.findall(r"\$\$(.+?)\$\$", block_doc(cls), re.S)
]
FIGURES = sorted({f for cls in block_types().values() for f in re.findall(r"figures/(\w+\.png)", block_doc(cls))})


def test_blocks_have_equations_and_figures() -> None:
    assert len(EQUATIONS) >= 15
    assert "gain_modes.png" in FIGURES


@pytest.mark.parametrize(("block", "tex"), EQUATIONS)
def test_equation_renders(qapp, block: str, tex: str) -> None:  # type: ignore[no-untyped-def]
    from nervus.gui.views.math_render import render_latex

    images = render_latex(tex, "#000000")
    assert images and not any(img.isNull() for img in images)


@pytest.mark.parametrize("name", FIGURES)
def test_figure_is_bundled(name: str) -> None:
    assert resources.files("nervus.gui.resources.figures").joinpath(name).is_file()


def test_help_browser_renders_math_and_figures(window) -> None:  # type: ignore[no-untyped-def]
    window.show_help_for_type("math.gain")
    browser = window._help
    assert browser is not None
    html = browser.text.toHtml()
    assert "math:" in html  # typeset equation images
    assert "figures/gain_modes.png" in html
    assert not browser.text.loadResource(
        2, browser.text.source().resolved(__import__("PySide6.QtCore").QtCore.QUrl("figures/gain_modes.png"))
    ).isNull()
