"""C code generation: compile the generated code and compare it with the Python model (back-to-back)."""

from collections.abc import Callable

import numpy as np
import pytest

from nervus import Diagram
from nervus.blocks import (
    Abs,
    Bias,
    CompareToConstant,
    Constant,
    Counter,
    DeadZone,
    Debounce,
    Demux,
    DiscreteFilter,
    DiscreteIntegrator,
    DiscretePID,
    DiscreteTransferFunction,
    EdgeDetect,
    Gain,
    Inport,
    IntegerDelay,
    Integrator,
    LogicalOperator,
    Lookup1D,
    Lookup2D,
    MathFunction,
    MinMax,
    MovingAverage,
    Mux,
    Outport,
    Product,
    Quantizer,
    RateLimiter,
    RelationalOperator,
    Relay,
    Saturation,
    Scope,
    Subsystem,
    Sum,
    Switch,
    UnitDelay,
    ZeroOrderHold,
)
from nervus.codegen import CodegenError, generate_c
from nervus.codegen.sil import back_to_back, find_compiler
from nervus.core import Block

pytestmark = pytest.mark.skipif(find_compiler() is None, reason="no C compiler available")

STEPS = 60
RNG = np.random.default_rng(42)


def harness(block: Block, n_inputs: int, ts: float = 0.01) -> Diagram:
    """In -> ZOH -> block -> Out, so the block runs at a discrete rate."""
    d = Diagram("dut")
    b = d.add(block, name="dut")
    for k in range(n_inputs):
        u = d.add(Inport(port=k + 1), name=f"u{k}")
        z = d.add(ZeroOrderHold(sample_time=ts), name=f"zoh{k}")
        d.chain(u, z)
        d.connect(z, (b, k))
    for p in range(b.num_outputs()):
        d.connect((b, p), d.add(Outport(port=p + 1), name=f"y{p}"))
    return d


def random_inputs(n: int, kind: str = "real") -> dict[str, np.ndarray]:
    out = {}
    for k in range(n):
        if kind == "bool":
            out[f"u{k}"] = (RNG.random(STEPS) > 0.5).astype(float)
        elif kind == "positive":
            out[f"u{k}"] = RNG.uniform(0.1, 5.0, STEPS)
        else:
            out[f"u{k}"] = RNG.uniform(-3.0, 3.0, STEPS)
    return out


CASES: list[tuple[str, Callable[[], Block], int, str]] = [
    ("gain", lambda: Gain(gain=2.5), 1, "real"),
    ("sum", lambda: Sum(signs="+-+"), 3, "real"),
    ("product", lambda: Product(ops="*/"), 2, "positive"),
    ("abs", lambda: Abs(), 1, "real"),
    ("bias", lambda: Bias(bias=1.5), 1, "real"),
    ("saturation", lambda: Saturation(upper=1.0, lower=-0.5), 1, "real"),
    ("sqrt", lambda: MathFunction(function="sqrt"), 1, "positive"),
    ("tanh", lambda: MathFunction(function="tanh"), 1, "real"),
    ("sign", lambda: MathFunction(function="sign"), 1, "real"),
    ("minmax", lambda: MinMax(function="max", num_inputs=3), 3, "real"),
    ("dead_zone", lambda: DeadZone(start=-1.0, end=0.5), 1, "real"),
    ("quantizer", lambda: Quantizer(interval=0.25), 1, "real"),
    ("relay", lambda: Relay(on_point=1.0, off_point=-1.0, on_value=5.0, off_value=-2.0), 1, "real"),
    ("rate_limiter", lambda: RateLimiter(rising_rate=50.0, falling_rate=-20.0), 1, "real"),
    ("relational", lambda: RelationalOperator(operator=">="), 2, "real"),
    ("compare", lambda: CompareToConstant(operator="<", constant=0.3), 1, "real"),
    ("and", lambda: LogicalOperator(operator="AND", num_inputs=3), 3, "bool"),
    ("xor", lambda: LogicalOperator(operator="XOR", num_inputs=3), 3, "bool"),
    ("nor", lambda: LogicalOperator(operator="NOR"), 2, "bool"),
    ("not", lambda: LogicalOperator(operator="NOT"), 1, "bool"),
    ("switch", lambda: Switch(threshold=0.2), 3, "real"),
    ("unit_delay", lambda: UnitDelay(initial=0.7), 1, "real"),
    ("integer_delay", lambda: IntegerDelay(delay=4, initial=-1.0), 1, "real"),
    ("dint_fwd", lambda: DiscreteIntegrator(gain=2.0, upper=1.0, lower=-1.0), 1, "real"),
    ("dint_bwd", lambda: DiscreteIntegrator(method="backward_euler"), 1, "real"),
    ("dtf", lambda: DiscreteTransferFunction(numerator=[0.2, 0.1], denominator=[1.0, -1.2, 0.5]), 1, "real"),
    ("dtf_static", lambda: DiscreteTransferFunction(numerator=[2.0], denominator=[1.0]), 1, "real"),
    ("counter_wrap", lambda: Counter(limit=7), 1, "bool"),
    ("counter_sat", lambda: Counter(limit=7, at_limit="saturate"), 1, "bool"),
    ("edge_rising", lambda: EdgeDetect(direction="rising"), 1, "bool"),
    ("edge_either", lambda: EdgeDetect(direction="either"), 1, "bool"),
    ("debounce", lambda: Debounce(on_samples=3, off_samples=2), 1, "bool"),
    ("pt1", lambda: DiscreteFilter(time_constant=0.05), 1, "real"),
    ("moving_avg", lambda: MovingAverage(length=5), 1, "real"),
    (
        "pid",
        lambda: DiscretePID(P=1.2, I=3.0, D=0.05, N=50.0, upper=2.0, lower=-2.0, anti_windup="clamping"),
        1,
        "real",
    ),
    ("pid_none", lambda: DiscretePID(P=0.8, I=2.0, D=0.1, N=20.0), 1, "real"),
    ("pid_bc", lambda: DiscretePID(P=1.0, I=4.0, upper=1.0, lower=-1.0, anti_windup="back_calculation"), 1, "real"),
    ("lookup1d", lambda: Lookup1D(breakpoints=[-2, 0, 1, 2], table=[4, 0, 1, 3]), 1, "real"),
    (
        "lookup1d_lin",
        lambda: Lookup1D(breakpoints=[-2, 0, 1, 2], table=[4, 0, 1, 3], extrapolation="linear"),
        1,
        "real",
    ),
    ("lookup1d_flat", lambda: Lookup1D(breakpoints=[-2, 0, 1, 2], table=[4, 0, 1, 3], interpolation="flat"), 1, "real"),
    (
        "lookup1d_near",
        lambda: Lookup1D(breakpoints=[-2, 0, 1, 2], table=[4, 0, 1, 3], interpolation="nearest"),
        1,
        "real",
    ),
    (
        "lookup2d",
        lambda: Lookup2D(row_breakpoints=[-2, 0, 2], column_breakpoints=[-1, 1], table=[[1, 2], [3, 5], [0, -1]]),
        2,
        "real",
    ),
]


@pytest.mark.parametrize(("label", "factory", "n_inputs", "kind"), CASES, ids=[c[0] for c in CASES])
def test_block_back_to_back(label: str, factory: Callable[[], Block], n_inputs: int, kind: str, tmp_path) -> None:  # type: ignore[no-untyped-def]
    d = harness(factory(), n_inputs)
    res = back_to_back(d, random_inputs(n_inputs, kind), STEPS, tolerance=1e-12, folder=tmp_path)
    assert res.passed, res.summary()


def test_vectors_mux_demux_matrix_gain(tmp_path) -> None:  # type: ignore[no-untyped-def]
    d = Diagram("vec")
    a = d.add(Inport(port=1, value=[0.0, 0.0]), name="a")
    b = d.add(Inport(port=2), name="b")
    za, zb = d.add(ZeroOrderHold(sample_time=0.01)), d.add(ZeroOrderHold(sample_time=0.01))
    m = d.add(Mux(), name="mux")
    k = d.add(Gain(gain=[[1, 2, 3], [0, -1, 4]], multiplication="matrix"), name="K")
    dm = d.add(Demux(num_outputs=2), name="demux")
    d.chain(a, za)
    d.chain(b, zb)
    d.connect(za, (m, 0))
    d.connect(zb, (m, 1))
    d.chain(m, k, dm)
    d.connect((dm, 0), d.add(Outport(port=1), name="y0"))
    d.connect((dm, 1), d.add(Outport(port=2), name="y1"))
    inputs = {"a": RNG.uniform(-1, 1, (STEPS, 2)), "b": RNG.uniform(-1, 1, STEPS)}
    res = back_to_back(d, inputs, STEPS, tolerance=1e-12, folder=tmp_path)
    assert res.passed, res.summary()


def test_multirate(tmp_path) -> None:  # type: ignore[no-untyped-def]
    d = Diagram("multirate")
    u = d.add(Inport(port=1), name="u")
    fast = d.add(ZeroOrderHold(sample_time=0.01), name="fast")
    slow = d.add(ZeroOrderHold(sample_time=0.05), name="slow")
    acc = d.add(DiscreteIntegrator(sample_time=0.05), name="acc")
    s = d.add(Sum(), name="sum")
    d.chain(u, fast)
    d.chain(u, slow, acc)
    d.connect(fast, (s, 0))
    d.connect(acc, (s, 1))
    d.connect(s, d.add(Outport(port=1), name="y"))
    code = generate_c(d)
    assert code.base_period == pytest.approx(0.01)
    assert "rt_hit[1]" in code.files["multirate.c"]
    res = back_to_back(d, {"u": np.sin(np.arange(STEPS) * 0.3)}, STEPS, tolerance=1e-12, folder=tmp_path)
    assert res.passed, res.summary()


def test_workspace_variables_become_shared_parameters() -> None:
    d = harness(Gain(gain="Kp"), 1)
    d.workspace["Kp"] = 2.0
    d2 = d.add(Gain(gain="Kp"), name="g2")
    d.connect(d.block("dut"), d2)
    d.connect(d2, d.add(Outport(port=2), name="y_2"))
    code = generate_c(d)
    assert code.params["Kp"] == [2.0]
    assert sum("ECU" in k or k == "Kp" for k in code.params) == 1
    assert "dut_P.Kp[0]" in code.files["dut.c"]


def test_subsystem_only(tmp_path) -> None:  # type: ignore[no-untyped-def]
    inner = harness(Gain(gain=3.0), 1)
    d = Diagram("model")
    sub = d.add(Subsystem(system=inner), name="controller")
    plant = d.add(Integrator(), name="plant")  # continuous: fine, it is outside the generated subsystem
    d.chain(d.add(Constant(value=1.0)), sub, plant, d.add(Scope()))
    code = generate_c(sub)
    assert set(code.c_files) == {"controller.h", "controller.c"}
    assert {"controller_sil.c", "main_example.c", "controller_report.html"} <= set(code.files)
    with pytest.raises(CodegenError, match="continuous states"):
        generate_c(d)


def test_unsupported_blocks_are_listed() -> None:
    d = Diagram("bad")
    i = d.add(Integrator(), name="int")
    d.chain(d.add(Constant()), i, d.add(Outport(port=1)))
    with pytest.raises(CodegenError) as exc:
        generate_c(d)
    assert "int" in exc.value.blocks


def test_generated_header_api() -> None:
    code = generate_c(harness(Gain(gain=2.0), 1))
    h = code.files["dut.h"]
    for needle in ("void dut_initialize(void);", "void dut_step(void);", "extern dut_U_t dut_U;", "dut_BASE_PERIOD"):
        assert needle in h or needle.upper() in h


def test_main_example_and_report_compile(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import subprocess

    code = generate_c(harness(DiscretePID(P=1.0, I=2.0), 1))
    code.write(tmp_path)
    cc = find_compiler()
    proc = subprocess.run(
        [cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "-c", "dut.c", "main_example.c"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    report = (tmp_path / "dut_report.html").read_text()
    assert "Code generation report" in report and "dut" in report and 'href="#L' in report
    assert set(code.c_files) == {"dut.h", "dut.c"}


def test_a2l_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from nervus.codegen.a2l import fill_addresses, symbol_addresses
    from nervus.codegen.sil import build_shared_library
    from nervus.core import Variable

    d = harness(DiscretePID(P="Kp", I=2.0), 1)
    d.workspace.add(Variable("Kp", 1.5, "Proportional gain", "%/deg", min=0.0, max=10.0))
    code = generate_c(d)
    a2l = code.files["dut.a2l"]
    assert a2l.count("/begin") == a2l.count("/end")
    assert '/begin CHARACTERISTIC dut_P.Kp "Proportional gain"' in a2l
    assert "RL_FLOAT64 0 CM___deg 0.0 10.0" in a2l
    assert "MEASUREMENT dut_B.dut" in a2l
    lib = build_shared_library(code, tmp_path)
    filled = fill_addresses(a2l, symbol_addresses(lib))
    assert "@dut_P" not in filled and "@dut_B" not in filled
