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


def test_throttle_calibration_file() -> None:
    from nervus import ParameterSet

    d = load(EXAMPLES / "throttle_pi.nervus")
    base = simulate(d)["plate_angle"].max()
    d.workspace.apply(ParameterSet.load(EXAMPLES / "throttle_tight.nervcal").values)
    tight = simulate(d)["plate_angle"].max()
    assert tight < base - 1.0  # less overshoot over the 60 degree target


def test_coolant_fan_hysteresis() -> None:
    mod = _import("coolant_fan")
    res = simulate(mod.build(), 300.0, solver="rk4", step=0.01)
    fan, temp = res["fan_on"], res["coolant_temp"]
    switches = int((abs(np.diff(fan)) > 0.5).sum())
    assert 2 <= switches <= 20  # switches, but does not chatter
    assert temp.max() < 100.0
    on_times = res.t[1:][np.diff(fan) > 0.5]
    # The fan switches on only once the filtered temperature reaches T_on.
    assert all(res["temp_filtered"][np.searchsorted(res.t, ton)] >= 97.9 for ton in on_times)


def test_throttle_ecu_and_committed_generated_code() -> None:
    """examples/generated/ECU must match what the generator produces now (run examples/throttle_ecu.py)."""
    mod = _import("throttle_ecu")
    d = mod.build()
    from nervus.codegen import generate_c

    code = generate_c(d.block("ECU"))
    for name, text in code.c_files.items():
        assert (EXAMPLES / "generated" / "ECU" / name).read_text() == text, f"generated/ECU/{name} is stale"
    res = simulate(d)
    assert float(np.interp(1.15, res.t, res["plate_angle"])) == pytest.approx(60.0, abs=0.5)
