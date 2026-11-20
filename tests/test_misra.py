"""The generated code follows MISRA C:2012 (checked with cppcheck's MISRA addon) and compiles without warnings."""

import subprocess
import sys
from pathlib import Path

import pytest

from nervus import load
from nervus.blocks.registry import _REGISTRY
from nervus.codegen import generate_c
from nervus.codegen.generator import TEMPLATES
from nervus.codegen.misra import cppcheck_path, misra_check
from nervus.codegen.sil import find_compiler

sys.path.insert(0, str(Path(__file__).parent))
from test_codegen import harness

EXAMPLES = Path(__file__).parent.parent / "examples"
pytestmark = pytest.mark.skipif(cppcheck_path() is None, reason="needs cppcheck")
# Blocks that need more than their defaults to generate code (a DBC file, frame bytes, a wider input); they are
# covered by the example models below or by their own tests.
NEEDS_SETUP = {"can.e2e_check", "can.e2e_protect", "can.pack", "can.unpack", "routing.demux",
               "ports.inport", "sources.constant", "sources.ground"}  # fmt: skip
TYPES = sorted(t for t in TEMPLATES if t in _REGISTRY and t not in NEEDS_SETUP)


def _strict_compile(code, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    cc = find_compiler()
    if cc is None:
        return
    code.write(tmp_path)
    run = subprocess.run([cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "-c",
                          f"{code.name}.c", "main_example.c"], cwd=tmp_path, capture_output=True, text=True)  # fmt: skip
    assert run.returncode == 0, run.stderr


@pytest.mark.parametrize("type_id", TYPES)
def test_every_block_template(type_id: str, tmp_path: Path) -> None:
    block = _REGISTRY[type_id]()
    code = generate_c(harness(block, block.num_inputs()))
    assert [str(f) for f in misra_check(code)] == []
    _strict_compile(code, tmp_path)


@pytest.mark.parametrize(("model", "target"), [
    ("throttle_ecu", "ECU"), ("engine_modes", None), ("lambda_control", "ECU"), ("ignition_knock", "ECU"),
    ("electronic_throttle", "ECU"), ("gear_shift", "tcu"),
])  # fmt: skip
def test_example_models(model: str, target: str | None, tmp_path: Path) -> None:
    d = load(EXAMPLES / f"{model}.nervus")
    code = generate_c(d.block(target) if target else d)
    assert [str(f) for f in misra_check(code)] == []
    _strict_compile(code, tmp_path)


def test_integer_and_fixed_point_types(tmp_path: Path) -> None:
    """Integer and fixed-point signals: saturating and wrapping conversions, scaled values."""
    from nervus import Diagram
    from nervus.blocks import CompareToConstant, DataTypeConversion, Gain, Inport, Outport, Sum, ZeroOrderHold

    d = Diagram("typed")
    u = d.add(Inport(port=1, output_type="int16"), name="sensor_raw")
    z = d.add(ZeroOrderHold(sample_time=0.01), name="z")
    scale = d.add(Gain(gain=0.0123, output_type="fixdt(1, 16, 7)"), name="scaled")
    acc = d.add(Sum(signs="++", output_type="int8"), name="acc")
    wrap = d.add(DataTypeConversion(output_type="uint8", overflow="wrap", rounding="floor"), name="wrapped")
    temp = d.add(DataTypeConversion(output_type="fixdt(0, 8, 0.5, -40)"), name="temp")
    hot = d.add(CompareToConstant(operator=">", constant=10.0), name="hot")
    d.chain(u, z, scale)
    d.connect(scale, (acc, 0))
    d.connect(z, (acc, 1))
    d.chain(scale, wrap)
    d.chain(scale, temp, hot)
    for k, blk in enumerate((acc, wrap, temp, hot)):
        d.connect(blk, d.add(Outport(port=k + 1), name=f"y{k}"))
    code = generate_c(d)
    assert [str(f) for f in misra_check(code)] == []
    _strict_compile(code, tmp_path)


def test_sample_time_offsets() -> None:
    from nervus import Diagram
    from nervus.blocks import Inport, Outport, UnitDelay, ZeroOrderHold

    d = Diagram("offsets")
    z = d.add(ZeroOrderHold(sample_time=0.01), name="z")
    delay = d.add(UnitDelay(initial=5.0, sample_time=[0.04, 0.03]), name="delay")
    d.chain(d.add(Inport(port=1), name="u"), z, delay)
    d.connect(delay, d.add(Outport(port=1), name="y"))
    assert [str(f) for f in misra_check(generate_c(d))] == []


def test_one_function_per_task() -> None:
    from test_tasks_codegen import two_tasks

    assert [str(f) for f in misra_check(generate_c(two_tasks(), tasks=True))] == []


def test_findings_are_reported() -> None:
    """Without the deviations, the check reports them: rule 2.5 for the base-period macro."""
    from nervus.blocks import Gain

    findings = misra_check(generate_c(harness(Gain(gain=2.0), 1)), deviations={})
    assert any(f.rule == "2.5" and "BASE_PERIOD" in f.source for f in findings)
