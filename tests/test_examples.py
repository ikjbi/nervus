"""Run the example scripts so they never go stale."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from nervus import load, simulate

EXAMPLES = Path(__file__).parent.parent / "examples"


def _import(name: str):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(name, EXAMPLES / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_mass_spring_damper_pid() -> None:
    res = _import("mass_spring_damper_pid").main(show_plot=False)
    assert res["position"][-1] == pytest.approx(1.0, abs=1e-3)
    assert abs(res["pid"]).max() <= 50.0 + 1e-9


def test_throttle_pi() -> None:
    res = _import("throttle_pi").main(show_plot=False)
    t, angle = res.t, res["plate_angle"]
    assert float(np.interp(1.15, t, angle)) == pytest.approx(60.0, abs=0.5)
    assert float(np.interp(1.95, t, angle)) == pytest.approx(20.0, abs=0.5)
    assert res["throttle_pi"].min() >= 0.0 and res["throttle_pi"].max() <= 100.0


@pytest.mark.parametrize("name", ["mass_spring_damper_pid", "throttle_pi"])
def test_saved_model_matches_script(name: str) -> None:
    mod = _import(name)
    expected = simulate(mod.build())
    loaded = simulate(load(EXAMPLES / f"{name}.nervus"))
    for key in expected.signals:
        np.testing.assert_allclose(loaded.signals[key], expected.signals[key])


def test_block_reference_is_up_to_date() -> None:
    """docs/blocks must match the code. Regenerate with: uv run python scripts/gen_block_reference.py"""
    from nervus.help import reference_pages

    docs = EXAMPLES.parent / "docs" / "blocks"
    for name, text in reference_pages().items():
        assert (docs / name).read_text(encoding="utf-8") == text.rstrip() + "\n", f"docs/blocks/{name} is stale"


def test_app_help_copies_are_up_to_date() -> None:
    """docs/app-help mirrors the in-app help. Regenerate with: uv run python scripts/gen_block_reference.py"""
    src = EXAMPLES.parent / "src" / "nervus" / "gui" / "resources" / "help"
    out = EXAMPLES.parent / "docs" / "app-help"
    for page in src.glob("*.md"):
        assert (out / page.name).read_text() == page.read_text(), f"docs/app-help/{page.name} is stale"
