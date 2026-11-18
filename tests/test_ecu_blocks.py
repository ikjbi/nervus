"""Tests for the ECU block library (Phase 8)."""

from typing import ClassVar

import numpy as np
import pytest

from nervus import Diagram, ModelError, ParameterError, simulate
from nervus.blocks import (
    Bias,
    CompareToConstant,
    Constant,
    Counter,
    DeadZone,
    Debounce,
    DiscreteFilter,
    EdgeDetect,
    FromWorkspace,
    Ground,
    IntegerDelay,
    LogicalOperator,
    Lookup1D,
    Lookup2D,
    MinMax,
    MovingAverage,
    Quantizer,
    RateLimiter,
    RelationalOperator,
    Relay,
    Scope,
    Sine,
    Terminator,
    ZeroOrderHold,
)
from nervus.core import Block


def static(block: Block, *values: object) -> np.ndarray:
    """Output of a stateless block for constant inputs."""
    d = Diagram()
    b = d.add(block, name="dut")
    for k, v in enumerate(values):
        d.connect(d.add(Constant(value=v)), (b, k))
    d.connect(b, d.add(Terminator()))
    return simulate(d, 0.0)["dut"][-1]


def sequence(block: Block, u: list[float], ts: float = 1.0) -> np.ndarray:
    """Output of a discrete block for an input sequence, one value per sample."""
    k = np.arange(len(u), dtype=float) * ts
    d = Diagram()
    src = d.add(FromWorkspace(time=k, data=u, interpolation="hold"), name="u")
    z = d.add(ZeroOrderHold(sample_time=ts), name="zoh")
    b = d.add(block, name="dut")
    d.chain(src, z, b, d.add(Terminator()))
    return simulate(d, float(k[-1]), solver="rk4", step=ts)["dut"]


class TestLookup1D:
    bp: ClassVar[list[float]] = [0.0, 1.0, 2.0]
    tab: ClassVar[list[float]] = [0.0, 10.0, 0.0]

    @pytest.mark.parametrize(
        ("u", "interp", "extrap", "y"),
        [
            (0.5, "linear", "clip", 5.0),
            (1.5, "linear", "clip", 5.0),
            (-1.0, "linear", "clip", 0.0),
            (3.0, "linear", "clip", 0.0),
            (-1.0, "linear", "linear", -10.0),
            (2.5, "linear", "linear", -5.0),
            (0.4, "nearest", "clip", 0.0),
            (0.6, "nearest", "clip", 10.0),
            (0.9, "flat", "clip", 0.0),
            (1.0, "flat", "clip", 10.0),
            (5.0, "flat", "clip", 0.0),
        ],
    )
    def test_modes(self, u: float, interp: str, extrap: str, y: float) -> None:
        blk = Lookup1D(breakpoints=self.bp, table=self.tab, interpolation=interp, extrapolation=extrap)
        assert static(blk, u) == pytest.approx(y)

    def test_vector_input(self) -> None:
        np.testing.assert_allclose(static(Lookup1D(breakpoints=self.bp, table=self.tab), [0.5, 1.0]), [5.0, 10.0])

    def test_validation(self) -> None:
        with pytest.raises(ParameterError, match="increasing"):
            Lookup1D(breakpoints=[0, 0, 1], table=[1, 2, 3])
        with pytest.raises(ParameterError, match="table has"):
            Lookup1D(breakpoints=[0, 1], table=[1, 2, 3])


class TestLookup2D:
    blk_args: ClassVar[dict[str, list]] = {
        "row_breakpoints": [0.0, 1.0],
        "column_breakpoints": [0.0, 10.0, 20.0],
        "table": [[0.0, 1.0, 2.0], [10.0, 11.0, 12.0]],
    }

    def test_bilinear(self) -> None:
        assert static(Lookup2D(**self.blk_args), 0.5, 5.0) == pytest.approx(5.5)
        assert static(Lookup2D(**self.blk_args), 1.0, 20.0) == pytest.approx(12.0)
        assert static(Lookup2D(**self.blk_args), 2.0, 30.0) == pytest.approx(12.0)  # clipped

    def test_linear_extrapolation_and_nearest(self) -> None:
        assert static(Lookup2D(**self.blk_args, extrapolation="linear"), 2.0, 0.0) == pytest.approx(20.0)
        assert static(Lookup2D(**self.blk_args, interpolation="nearest"), 0.6, 4.0) == pytest.approx(10.0)

    def test_shape_validation(self) -> None:
        with pytest.raises(ParameterError, match="2×3"):
            Lookup2D(**{**self.blk_args, "table": [[1, 2], [3, 4]]})

    def test_uses_workspace_map(self) -> None:
        d = Diagram()
        d.workspace["map"] = self.blk_args["table"]
        d.workspace["rows"] = [0.0, 1.0]
        d.workspace["cols"] = [0.0, 10.0, 20.0]
        b = d.add(Lookup2D(row_breakpoints="rows", column_breakpoints="cols", table="map"), name="m")
        d.connect(d.add(Constant(value=0.5)), (b, 0))
        d.connect(d.add(Constant(value=5.0)), (b, 1))
        d.connect(b, d.add(Scope()))
        assert simulate(d, 0.0)["m"][-1] == pytest.approx(5.5)


@pytest.mark.parametrize(
    ("op", "a", "b", "y"),
    [("<", 1, 2, 1), ("<=", 2, 2, 1), (">", 1, 2, 0), (">=", 2, 1, 1), ("==", 2, 2, 1), ("!=", 2, 2, 0)],
)
def test_relational(op: str, a: float, b: float, y: float) -> None:
    assert static(RelationalOperator(operator=op), a, b) == y


def test_compare_to_constant() -> None:
    np.testing.assert_array_equal(static(CompareToConstant(operator=">", constant=1.0), [0.0, 2.0]), [0, 1])


@pytest.mark.parametrize(
    ("op", "inputs", "y"),
    [
        ("AND", (1, 1, 1), 1),
        ("AND", (1, 0, 1), 0),
        ("OR", (0, 0, 3), 1),
        ("XOR", (1, 1, 1), 1),
        ("XOR", (1, 1, 0), 0),
        ("NAND", (1, 1, 1), 0),
        ("NOR", (0, 0, 0), 1),
    ],
)
def test_logical(op: str, inputs: tuple[float, ...], y: float) -> None:
    assert static(LogicalOperator(operator=op, num_inputs=len(inputs)), *inputs) == y


def test_logical_not_has_one_input() -> None:
    blk = LogicalOperator(operator="NOT")
    assert blk.num_inputs() == 1
    assert static(blk, 0.0) == 1.0
    with pytest.raises(ParameterError):
        LogicalOperator(operator="AND", num_inputs=1)


def test_dead_zone_quantizer_minmax_bias_ground() -> None:
    np.testing.assert_allclose(static(DeadZone(start=-1, end=1), [-3, 0.5, 2.5]), [-2, 0, 1.5])
    np.testing.assert_allclose(static(Quantizer(interval=0.5), [0.2, 0.3, -0.74]), [0.0, 0.5, -0.5])
    assert static(MinMax(function="max", num_inputs=1), [1, 5, 3]) == 5
    np.testing.assert_allclose(static(MinMax(function="min"), [1, 5], [3, 2]), [1, 2])
    np.testing.assert_allclose(static(Bias(bias=2.0), [1, 2]), [3, 4])
    d = Diagram()
    g = d.add(Ground(), name="g")
    d.connect(g, d.add(Terminator()))
    assert simulate(d, 1.0)["g"][-1] == 0.0


def test_relay_hysteresis() -> None:
    u = [0.0, 0.6, 1.0, 0.5, 0.1, 0.0, 0.5, 1.2]
    y = sequence(Relay(on_point=1.0, off_point=0.0), u)
    np.testing.assert_array_equal(y, [0, 0, 1, 1, 1, 0, 0, 1])


def test_relay_needs_discrete_rate() -> None:
    d = Diagram()
    d.chain(d.add(Sine()), d.add(Relay()), d.add(Terminator()))
    with pytest.raises(ModelError, match="discrete sample time"):
        simulate(d, 1.0)


def test_rate_limiter() -> None:
    y = sequence(RateLimiter(rising_rate=2.0, falling_rate=-1.0), [0, 10, 10, 10, 10, 0, 0, 0], ts=0.5)
    np.testing.assert_allclose(y, [0, 1, 2, 3, 4, 3.5, 3, 2.5])


def test_integer_delay() -> None:
    np.testing.assert_array_equal(sequence(IntegerDelay(delay=3, initial=-1), [1, 2, 3, 4, 5]), [-1, -1, -1, 1, 2])


def test_counter_wrap_and_saturate() -> None:
    u = [1, 1, 1, 0, 1, 1, 1]
    np.testing.assert_array_equal(sequence(Counter(limit=3), u), [0, 1, 2, 3, 3, 0, 1])
    np.testing.assert_array_equal(sequence(Counter(limit=3, at_limit="saturate"), u), [0, 1, 2, 3, 3, 3, 3])


def test_edge_detect() -> None:
    u = [0, 1, 1, 0, 1, 0]
    np.testing.assert_array_equal(sequence(EdgeDetect(direction="rising"), u), [0, 1, 0, 0, 1, 0])
    np.testing.assert_array_equal(sequence(EdgeDetect(direction="falling"), u), [0, 0, 0, 1, 0, 1])
    np.testing.assert_array_equal(sequence(EdgeDetect(direction="either"), u), [0, 1, 0, 1, 1, 1])


def test_debounce() -> None:
    u = [1, 1, 0, 1, 1, 1, 1, 0, 1, 0, 0, 0]
    y = sequence(Debounce(on_samples=3, off_samples=2), u)
    np.testing.assert_array_equal(y, [0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 0, 0])


def test_discrete_filter_step() -> None:
    ts, tau = 0.01, 0.1
    y = sequence(DiscreteFilter(time_constant=tau), [1.0] * 51, ts=ts)
    alpha = ts / (tau + ts)
    expected = 1 - (1 - alpha) ** np.arange(1, 52)
    np.testing.assert_allclose(y, expected)


def test_moving_average() -> None:
    np.testing.assert_allclose(sequence(MovingAverage(length=3), [3, 3, 3, 6, 6]), [1, 2, 3, 4, 5])
    np.testing.assert_allclose(sequence(MovingAverage(length=1), [3, 4]), [3, 4])
