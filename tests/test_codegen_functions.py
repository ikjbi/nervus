"""Reusable functions for subsystems in the generated C code."""

import numpy as np
import pytest

from nervus import Diagram
from nervus.blocks import Gain, Inport, Outport, Subsystem, Sum, UnitDelay, ZeroOrderHold
from nervus.codegen import generate_c
from nervus.codegen.generator import CodegenError
from nervus.codegen.sil import back_to_back, find_compiler
from nervus.core import Variable

pytestmark = pytest.mark.skipif(find_compiler() is None, reason="no C compiler")


def _trim(gain: float, function: str = "cyl_trim") -> Subsystem:
    """A cylinder trim: y = K * u + the sum of the previous outputs (an accumulator), every 10 ms; K in the mask."""
    inner = Diagram("trim")
    u = inner.add(Inport(port=1), name="u")
    k = inner.add(Gain(gain="K"), name="k")
    acc = inner.add(Sum(signs="++"), name="acc")
    mem = inner.add(UnitDelay(initial=0.0, sample_time=0.01), name="mem")
    inner.chain(u, k)
    inner.connect(k, (acc, 0))
    inner.connect(mem, (acc, 1))
    inner.chain(acc, mem)
    inner.connect(acc, inner.add(Outport(port=1), name="y"))
    sub = Subsystem(system=inner, sample_time=0.01, function_name=function)
    sub.mask.add(Variable("K", gain))
    return sub


def _engine(functions: tuple[str, ...] = ("cyl_trim",) * 3) -> Diagram:
    d = Diagram("engine")
    for c, (gain, fn) in enumerate(zip((0.5, 1.0, 2.0), functions, strict=True)):
        u = d.add(Inport(port=c + 1), name=f"u{c}")
        z = d.add(ZeroOrderHold(sample_time=0.01), name=f"z{c}")
        s = d.add(_trim(gain, fn), name=f"cyl{c}")
        d.chain(u, z, s)
        d.connect(s, d.add(Outport(port=c + 1), name=f"y{c}"))
    return d


def test_one_function_three_calls_same_results(tmp_path) -> None:  # type: ignore[no-untyped-def]
    d = _engine()
    code = generate_c(d)
    assert "cyl_trim.c" in code.c_files and "cyl_trim.h" in code.c_files
    c = code.files["engine.c"]
    assert c.count("cyl_trim_output(&") == 3 and c.count("cyl_trim_update(&") == 3
    assert "engine_cyl1_P" in code.files["engine.h"]  # each instance has its own calibration
    a2l = code.files["engine.a2l"]  # and the calibration tool sees it
    assert all(f"CHARACTERISTIC engine_cyl{c}_P.k_gain" in a2l for c in range(3))
    fn = code.files["cyl_trim.c"]
    assert "void cyl_trim_output(" in fn and "(*P).k_gain" in fn and fn.count("void cyl_trim_update(") == 1
    rng = np.random.default_rng(3)
    inputs = {f"u{c}": rng.uniform(-1, 1, 50) for c in range(3)}
    res = back_to_back(d, inputs, 50, tolerance=0.0, folder=tmp_path)
    assert res.passed, res.summary()
    # the instances really differ: K = 0.5, 1, 2
    assert not np.allclose(res.c["y0"], res.c["y2"])


def test_instances_must_have_the_same_contents() -> None:
    d = _engine()
    other = d.block("cyl2").system.block("acc")  # type: ignore[attr-defined]
    other.set_param("signs", "+-")  # a different structure (a different value would just be its own calibration)
    with pytest.raises(CodegenError, match="share the function name 'cyl_trim' but not their contents"):
        generate_c(d)


def test_different_names_give_different_functions() -> None:
    code = generate_c(_engine(("trim_a", "trim_a", "trim_b")))
    assert {"trim_a.c", "trim_b.c"} <= set(code.c_files)


def test_misra_and_strict_compile(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import subprocess

    from nervus.codegen.misra import cppcheck_path, misra_check

    code = generate_c(_engine())
    code.write(tmp_path)
    cc = find_compiler()
    srcs = ["engine.c", "cyl_trim.c", "main_example.c"]
    run = subprocess.run([cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "-c", *srcs], cwd=tmp_path,
                         capture_output=True, text=True)  # fmt: skip
    assert run.returncode == 0, run.stderr
    if cppcheck_path() is not None:
        assert [str(f) for f in misra_check(code)] == []


def test_inside_a_subsystem_target(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Code for an ECU subsystem whose cylinders are reusable functions, the plant around it left out."""
    from nervus.blocks import Constant

    ecu_inner = _engine()
    outer = Diagram("vehicle")
    ecu = outer.add(Subsystem(system=ecu_inner), name="ECU")
    for c in range(3):
        outer.connect(outer.add(Constant(value=float(c + 1)), name=f"sensor{c}"), (ecu, c))
    code = generate_c(ecu)
    assert code.name == "ECU" and "cyl_trim.c" in code.c_files
    rng = np.random.default_rng(4)
    res = back_to_back(ecu, {f"u{c}": rng.uniform(-1, 1, 30) for c in range(3)}, 30, tolerance=0.0, folder=tmp_path)
    assert res.passed, res.summary()


def test_a_function_needs_one_rate() -> None:
    d = _engine()
    for c in range(3):
        d.block(f"cyl{c}").system.block("mem").set_param("sample_time", 0.02)  # type: ignore[attr-defined]
    with pytest.raises(CodegenError, match="one rate"):
        generate_c(d)
