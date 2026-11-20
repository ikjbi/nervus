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


def test_shared_pages_are_up_to_date() -> None:
    """Concepts, Coming from Simulink and Model files are written in docs/ and converted for the app."""
    from nervus.help import SHARED_PAGES, docs_page_for_app

    help_dir = EXAMPLES.parent / "src" / "nervus" / "gui" / "resources" / "help"
    for docs_name, app_name in SHARED_PAGES.items():
        expected = docs_page_for_app((EXAMPLES.parent / "docs" / docs_name).read_text(encoding="utf-8"))
        assert (help_dir / app_name).read_text(encoding="utf-8") == expected, (
            f"run scripts/gen_block_reference.py ({app_name})"
        )


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


def test_throttle_ecu_stored_tests_pass() -> None:
    from nervus.testing import run_tests

    results = run_tests(load(EXAMPLES / "throttle_ecu.nervus"), base_dir=EXAMPLES)
    assert len(results) == 3
    assert all(r.passed for r in results), "\n".join(r.summary() for r in results)


def test_idle_speed_control() -> None:
    from nervus.testing import run_tests

    mod = _import("idle_speed_control")
    d = mod.build()
    results = run_tests(d)
    assert all(r.passed for r in results), "\n".join(r.summary() for r in results)
    assert load(EXAMPLES / "idle_speed_control.nervus").tests[0].name == "AC compressor on at 5 s"


def test_idle_ecu_generates_c() -> None:
    from nervus.codegen.sil import back_to_back, find_compiler

    if find_compiler() is None:
        pytest.skip("no C compiler")
    d = _import("idle_speed_control").build()
    k = np.arange(400)
    inputs = {"engine_rpm": 800 + 60 * np.sin(k / 25.0), "target_rpm": 800.0, "ac_request": (k > 200).astype(float)}
    res = back_to_back(d.block("ECU"), inputs, 400)
    assert res.passed, res.summary()


def test_fixed_point_sensor() -> None:
    res = _import("fixed_point_sensor").main()
    assert np.max(np.abs(res["fixed_minus_double"])) <= 2**-6
    assert np.allclose(np.mod(res["filtered_fix"] * 64, 1), 0)
    assert set(np.unique(res["over_150kPa"])) <= {0.0, 1.0}


def test_engine_library_example() -> None:
    from nervus.io.model_file import _block_dict
    from nervus.library import load_library
    from nervus.testing import run_tests

    mod = _import("engine_library")
    d = load(EXAMPLES / "engine_comparison.nervus")
    assert not d.link_warnings
    assert {b.library_link.component for b in d.blocks if getattr(b, "library_link", None)} == {
        "mean_value_engine",
        "throttle_actuator",
    }
    assert all(r.passed for r in run_tests(d))
    res = simulate(d, 4.9)
    assert res["engine_2_0l/to_rpm"][-1] < res["engine_1_6l/to_rpm"][-1]  # same air, more friction
    # The committed library matches the components the example builds.
    lib = load_library(EXAMPLES / "library" / "engine_parts.nervlib")
    for make in (mod.mean_value_engine, mod.throttle_actuator):
        fresh = make()
        stored = _block_dict(lib.block(fresh.name))
        built = _block_dict(fresh)
        stored.pop("meta", None)
        built.pop("meta", None)
        assert stored == built, f"examples/library is stale: run examples/engine_library.py ({fresh.name})"


def test_lambda_control_example() -> None:
    from nervus.codegen import generate_c
    from nervus.testing import run_tests

    mod = _import("lambda_control")
    d = mod.build()
    assert all(r.passed for r in run_tests(d)), [r.summary() for r in run_tests(d)]
    stored = load(EXAMPLES / "lambda_control.nervus")
    assert [t.name for t in stored.tests] == [t.name for t in d.tests]
    code = generate_c(d.block("ECU"))  # the fuel task is ECU code
    assert "stft" in code.files["ECU.c"] and code.rates == [0.01]


def test_drive_cycle_example() -> None:
    from nervus.testing import run_tests

    mod = _import("drive_cycle")
    d = mod.build()
    results = run_tests(d)
    assert all(r.passed for r in results), [r.summary() for r in results]
    assert [t.name for t in load(EXAMPLES / "drive_cycle.nervus").tests] == [t.name for t in d.tests]
    # The cycle definition: 195 s and 994 m (the published ECE-15 values).
    t = np.array([p[0] for p in mod.ECE15], dtype=float)
    v = np.array([p[1] for p in mod.ECE15], dtype=float) / 3.6
    assert t[-1] == 195.0 and np.trapezoid(v, t) == pytest.approx(994.0, abs=0.5)


def test_engine_modes_example(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from nervus.codegen import generate_c
    from nervus.codegen.sil import back_to_back, find_compiler
    from nervus.testing import run_tests

    mod = _import("engine_modes")
    d = mod.build()
    results = run_tests(d)
    assert all(r.passed for r in results), [r.summary() for r in results]
    assert [t.name for t in load(EXAMPLES / "engine_modes.nervus").tests] == [t.name for t in d.tests]
    # A shorter fuel cut-off threshold changes the behaviour: the thresholds really are calibration parameters.
    case = d.tests[2]
    early = simulate(d, case.stop_time, inputs=case.inputs, params={"rpm_cut_off": 2500.0})
    assert early["fuel"][int(len(early.t) * 0.55)] == 1.0
    code = generate_c(d)
    assert "rpm_cut_on" in code.files["engine_modes.h"]
    if find_compiler() is not None:
        k = np.arange(600)
        inputs = {"key": (k > 20).astype(float), "rpm": np.minimum(250 + 8.0 * k, 3000.0), "pedal": 30.0 * (k > 200)}
        res = back_to_back(d, inputs, 600, tolerance=0.0, folder=tmp_path)
        assert res.passed, res.summary()


def test_gear_shift_example(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from nervus.codegen import generate_c
    from nervus.codegen.sil import back_to_back, find_compiler
    from nervus.testing import run_tests

    mod = _import("gear_shift")
    d = mod.build()
    results = run_tests(d)
    assert all(r.passed for r in results), [r.summary() for r in results]
    assert [t.name for t in load(EXAMPLES / "gear_shift.nervus").tests] == [t.name for t in d.tests]
    res = simulate(d)
    times = [t for t, _, _ in mod.shifts(res)]
    assert len(times) >= 8
    assert min(np.diff(times)) >= 1.0 - 1e-9  # no hunting: at least min_gear_time in every gear
    # The hysteresis: every downshift speed is below the upshift speed of the gear below.
    up, down = np.array(mod.UPSHIFT), np.array(mod.DOWNSHIFT)
    assert np.all(down[1:] < up[:-1])
    code = generate_c(d.block("tcu"))
    assert "upshift_map" in code.files["tcu.h"]
    if find_compiler() is not None:
        k = np.arange(800)
        inputs = {
            "speed": np.minimum(0.15 * k, 100.0) - 0.08 * np.maximum(k - 600, 0),
            "pedal": 50 + 50 * np.sin(k / 90),
        }
        sil = back_to_back(d.block("tcu"), inputs, 800, tolerance=0.0, folder=tmp_path)
        assert sil.passed, sil.summary()


def test_obd_ecu_example() -> None:
    from nervus.testing import run_tests

    mod = _import("obd_ecu")
    d = mod.build()
    results = run_tests(d)
    assert all(r.passed for r in results), [r.summary() for r in results]
    assert [t.name for t in load(EXAMPLES / "obd_ecu.nervus").tests] == [t.name for t in d.tests]


def test_circuit_examples() -> None:
    import math

    from nervus.analysis import linearize
    from nervus.testing import run_tests

    mod = _import("circuits")
    for build in (mod.rectifier, mod.relay_driver, mod.buck_converter):
        d = build()
        results = run_tests(d)
        assert all(r.passed for r in results), [r.summary() for r in results]
        assert [t.name for t in load(EXAMPLES / f"{d.name}.nervus").tests] == [t.name for t in d.tests]
    kick = simulate(mod.relay_driver(flyback=False))
    assert 55.0 < kick["V(col)"].max() < 65.0  # clamped only by the transistor's breakdown
    _w, mag, _ = linearize(mod.active_filter()).bode(np.array([2 * math.pi * 1000.0]))
    assert mag[0] == pytest.approx(-3.01, abs=0.05)


def test_physical_examples(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from nervus.codegen.sil import back_to_back, find_compiler
    from nervus.testing import run_tests

    for name in ("starter_motor", "electronic_throttle"):
        d = _import(name).build()
        results = run_tests(d)
        assert all(r.passed for r in results), [r.summary() for r in results]
        assert [t.name for t in load(EXAMPLES / f"{name}.nervus").tests] == [t.name for t in d.tests]
    if find_compiler() is not None:
        ecu = _import("electronic_throttle").build().block("ECU")
        k = np.arange(300)
        inputs = {"target_deg": 5 + 55 * (k > 50), "tps_deg": np.minimum(5 + 0.3 * k, 58.0)}
        sil = back_to_back(ecu, inputs, 300, tolerance=1e-12, folder=tmp_path)
        assert sil.passed, sil.summary()


def test_traction_control_example() -> None:
    from nervus.testing import run_tests

    mod = _import("traction_control")
    d = mod.build()
    assert all(r.passed for r in run_tests(d))
    off = simulate(d, params={"mu_road": 0.5, "tcs_enable": 0.0})
    assert off["slip"][-1] > 0.6  # without TCS the wheels spin
    assert [t.name for t in load(EXAMPLES / "traction_control.nervus").tests] == [t.name for t in d.tests]
