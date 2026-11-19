"""The :class:`Block` base class.

A block is a small dynamic system with inputs ``u``, outputs ``y``, continuous states ``xc`` and discrete states
``xd``. Its behaviour is defined by pure functions, so the solver can call them as often as it needs and a code
generator can later translate them one-to-one:

* ``outputs(t, u, xc, xd) -> y``      – the output equation
* ``derivatives(t, u, xc, xd) -> dxc`` – continuous state derivatives (blocks with continuous states)
* ``update(t, u, xc, xd) -> xd'``      – the next discrete state (called at the block's sample hits)

Blocks never store simulation state on ``self``. The simulator owns the state vectors.

Every signal is a 1-D float64 array. A scalar signal has width 1.
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

import numpy as np

from nervus.core.errors import ParameterError
from nervus.core.expressions import UnknownNameError, parse_value
from nervus.core.params import Param, ParamKind, to_jsonable
from nervus.core.sample_time import CONTINUOUS, INHERITED, SampleTime
from nervus.core.types import EMPTY, Array

Width = int | None

EXPRESSION_KINDS = frozenset({ParamKind.FLOAT, ParamKind.INT, ParamKind.ARRAY, ParamKind.SAMPLE_TIME})
"""Parameter kinds that may be given as an expression using workspace variables, e.g. ``"2*Kp"``."""


@dataclass(frozen=True, eq=False)
class InPort:
    block: Block
    index: int

    def __repr__(self) -> str:
        return f"<InPort {self.block.name}[{self.index}]>"


@dataclass(frozen=True, eq=False)
class OutPort:
    block: Block
    index: int

    def __repr__(self) -> str:
        return f"<OutPort {self.block.name}[{self.index}]>"


def broadcast_widths(widths: Sequence[Width]) -> Width:
    """Width that results from combining signals elementwise, with scalar expansion.

    Unknown widths (``None``) are ignored. Returns ``None`` if no width is known yet.
    Raises :class:`ValueError` if two known widths are incompatible.
    """
    known = {w for w in widths if w is not None}
    if not known:
        return None
    non_scalar = known - {1}
    if len(non_scalar) > 1:
        raise ValueError(f"incompatible signal widths {sorted(known)}")
    return non_scalar.pop() if non_scalar else 1


class Block:
    """Base class for all blocks.

    Subclasses set the class attributes below, declare ``PARAMS`` and override the methods they need.
    The class docstring is shown as the block's help text in the GUI and in the generated block reference.
    """

    type_id: ClassVar[str] = ""
    """Unique, stable identifier used in model files, e.g. ``"math.gain"``."""
    label: ClassVar[str] = ""
    """Human-readable name, also used as the base for automatic block names."""
    category: ClassVar[str] = ""
    """Library category, e.g. ``"Math Operations"``."""

    PARAMS: ClassVar[tuple[Param, ...]] = ()
    NUM_INPUTS: ClassVar[int] = 1
    NUM_OUTPUTS: ClassVar[int] = 1
    DIRECT_FEEDTHROUGH: ClassVar[bool] = True
    """Whether ``outputs`` reads ``u``. Blocks whose outputs only depend on state set this to ``False``;
    that is what breaks algebraic loops."""
    DEFAULT_SAMPLE_TIME: ClassVar[SampleTime] = INHERITED
    """Used when the block has no ``sample_time`` parameter."""
    LOGS_INPUTS: ClassVar[bool] = False
    TYPE_RULE: ClassVar[str] = "inherit"
    """How output data types are chosen when the block has no ``output_type`` parameter (or it is
    ``inherit``): ``inherit`` (the common type of the inputs), ``double`` or ``boolean``."""
    TYPE_INPUTS: ClassVar[tuple[int, ...] | None] = None
    """Which inputs the type is inherited from (``None``: all)."""
    """Sinks like Scope set this so the result object can look up their input signals."""

    def __init__(self, name: str = "", **params: Any) -> None:
        self.name = name
        self.meta: dict[str, Any] = {}
        """Free-form metadata (e.g. GUI position). Saved in model files but ignored by the simulator."""
        self.diagram: Any = None
        declared = {p.name: p for p in self.PARAMS}
        unknown = set(params) - set(declared)
        if unknown:
            raise ParameterError(
                f"{type(self).__name__} has no parameter(s) {', '.join(sorted(unknown))}; "
                f"valid parameters: {', '.join(declared) or 'none'}"
            )
        self.params: dict[str, Any] = {}
        self.expressions: dict[str, str] = {}
        """Parameters given as expressions of workspace variables, by parameter name. ``params`` holds their
        most recently resolved values (or the defaults until the block is resolved)."""
        self._unresolved: set[str] = set()
        for p in self.PARAMS:
            self.params[p.name] = p.coerce(p.default)
            self._assign(p, params.get(p.name, p.default))
        if not self._unresolved:  # otherwise validated when the expressions are resolved (see resolve())
            self.validate_params()
        self.in_widths: list[int] = []
        self.out_widths: list[int] = []
        self.resolved_sample_time: SampleTime | None = None
        """Set by the compiler: the sample time after inheritance is resolved."""
        self.sliding = False
        """Set by the simulator when the system chatters along one of this block's discontinuities (Zeno guard):
        the block may then use a smooth version of its switch."""
        self.mode: Array | None = None
        """Frozen discontinuity mode during variable-step integration (set by the simulator, see
        :meth:`compute_mode`). ``None`` means: choose the branch from the current inputs."""

    # ------------------------------------------------------------------ parameters

    @classmethod
    def param_spec(cls, name: str) -> Param:
        for p in cls.PARAMS:
            if p.name == name:
                return p
        raise ParameterError(f"{cls.__name__} has no parameter '{name}'")

    def _namespace(self) -> dict[str, Any] | None:
        d = self.diagram
        if d is None:
            return None
        root = d.root
        if root.parent is not None:  # inside a subsystem that is not part of a model yet
            return None
        try:
            return d.namespace()
        except Exception:
            return None

    def _assign(self, p: Param, value: Any, namespace: dict[str, Any] | None = None) -> None:
        """Store ``value`` for parameter ``p``: a literal, or an expression of workspace variables."""
        if p.kind in EXPRESSION_KINDS and isinstance(value, str):
            try:
                literal = parse_value(value)
            except UnknownNameError:
                if namespace is not None:  # strict: the variables must exist (used by the editor)
                    try:
                        resolved = parse_value(value, namespace)
                    except ValueError as exc:
                        raise ParameterError(f"parameter '{p.name}': {exc}") from exc
                    self.params[p.name] = p.coerce(resolved)
                else:  # lenient: resolve now if possible; unknown variables are reported by Diagram.check()
                    ns = self._namespace()
                    unresolved: set[str] = getattr(self, "_unresolved", set())
                    unresolved.add(p.name)
                    if ns is not None:
                        with contextlib.suppress(ValueError):
                            self.params[p.name] = p.coerce(parse_value(value, ns))
                            unresolved.discard(p.name)
                self.expressions[p.name] = value.strip()
                return
            except ValueError as exc:
                raise ParameterError(f"parameter '{p.name}': {exc}") from exc
            value = literal
        self.expressions.pop(p.name, None)
        self.params[p.name] = p.coerce(value)

    def set_param(self, name: str, value: Any) -> None:
        """Set one parameter (a value or a workspace expression), validating it.
        The old value is kept if validation fails."""
        spec = self.param_spec(name)
        old_value, old_expr = self.params[name], self.expressions.get(name)
        try:
            self._assign(spec, value)
            self.validate_params()
        except Exception:
            self.params[name] = old_value
            if old_expr is None:
                self.expressions.pop(name, None)
            else:
                self.expressions[name] = old_expr
            raise

    def param_source(self, name: str) -> Any:
        """What the user wrote: the expression string if there is one, otherwise the value."""
        return self.expressions.get(name, self.params[name])

    def resolve(self, namespace: dict[str, Any]) -> None:
        """Evaluate all parameter expressions with ``namespace`` (workspace variable values)."""
        if not self.expressions:
            return
        for name, expr in list(self.expressions.items()):
            spec = self.param_spec(name)
            try:
                self.params[name] = spec.coerce(parse_value(expr, namespace))
            except ValueError as exc:
                raise ParameterError(f"parameter '{name}' = {expr!r}: {exc}") from exc
        self._unresolved = set()
        self.validate_params()

    def validate_params(self) -> None:
        """Check parameter combinations. Raise :class:`ParameterError` if invalid."""

    def params_jsonable(self) -> dict[str, Any]:
        """Parameters for saving: expressions are kept as written, values converted for JSON."""
        return {k: self.expressions.get(k, to_jsonable(v)) for k, v in self.params.items()}

    # ------------------------------------------------------------------ ports

    def num_inputs(self) -> int:
        return self.NUM_INPUTS

    def input_names(self) -> list[str]:
        """Names of the inputs, shown as port tooltips in the editor ("" = no name)."""
        return []

    def num_outputs(self) -> int:
        return self.NUM_OUTPUTS

    def in_port(self, index: int = 0) -> InPort:
        if not 0 <= index < self.num_inputs():
            raise IndexError(f"{self.name or type(self).__name__} has no input port {index}")
        return InPort(self, index)

    def out_port(self, index: int = 0) -> OutPort:
        if not 0 <= index < self.num_outputs():
            raise IndexError(f"{self.name or type(self).__name__} has no output port {index}")
        return OutPort(self, index)

    # ------------------------------------------------------------------ compile-time hooks

    def sample_time(self) -> SampleTime:
        """The sample time as declared (may be inherited, ``-1``)."""
        if "sample_time" in self.params:
            return SampleTime.from_value(self.params["sample_time"])
        return self.DEFAULT_SAMPLE_TIME

    def major_step(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array | None:
        """Called at every major time step: return a new continuous state to make it jump (e.g. an integrator
        reset), or ``None``. The solver restarts from the new state."""
        return None

    def output_sample_time(self) -> SampleTime | None:
        """The rate that blocks fed by this one inherit, if it differs from this block's own rate (e.g. a
        Rate Transition from a slow to a fast task). ``None``: the block's resolved rate."""
        return None

    def period(self) -> float:
        """The resolved sample period in seconds of a discrete block (valid during simulation).

        Inherited sample times are resolved by the compiler, so use this instead of ``sample_time().period``
        in ``outputs``/``update``.
        """
        st = self.resolved_sample_time or self.sample_time()
        return st.period

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        """Return the width of each output given the (possibly unknown) input widths.

        Called repeatedly until all widths settle. Return ``None`` for a width that cannot be known yet.
        A provisional guess is allowed; it will be revised once more information is available.
        The default combines all inputs elementwise (scalar expansion), or gives width 1 for blocks
        without inputs.
        """
        if self.num_inputs() == 0:
            return [1] * self.num_outputs()
        return [broadcast_widths(in_widths)] * self.num_outputs()

    def output_types(self, in_types: list[Any]) -> list[Any]:
        """Data types of the outputs (:class:`~nervus.core.datatypes.DataType`) given the input types
        (``None`` = not known yet). Called repeatedly until the types settle, like :meth:`output_widths`."""
        from nervus.core.datatypes import BOOLEAN, DOUBLE, common_type, parse_datatype

        n = self.num_outputs()
        if "output_type" in self.params:
            explicit = parse_datatype(self.params["output_type"])
            if explicit is not None:
                return [explicit] * n
        if self.TYPE_RULE == "double":
            return [DOUBLE] * n
        if self.TYPE_RULE == "boolean":
            return [BOOLEAN] * n
        if self.num_inputs() == 0:
            return [DOUBLE] * n
        picked = [in_types[k] for k in (self.TYPE_INPUTS or range(len(in_types))) if k < len(in_types)]
        known = [t for t in picked if t is not None]
        if not known:
            return [None] * n
        return [common_type(known)] * n

    def coverage_outcomes(self) -> list[str]:
        """All decision outcomes of this block for model coverage, e.g. ``["true", "false"]``. Empty if the
        block makes no decisions."""
        return []

    def coverage_hits(self, t: float, u: Sequence[Array], y: Sequence[Array], xd: Array) -> list[str]:
        """The outcomes taken at this time step (called with the block's inputs, outputs and state)."""
        return []

    def suggestions(self, param: str) -> list[str]:
        """Values to offer for a text parameter in the editor (e.g. the messages of a DBC file)."""
        return []

    def quantization(self) -> tuple[str, str]:
        """(rounding, overflow) used when the block's outputs are converted to their data type."""
        return (self.params.get("rounding", "nearest"), self.params.get("overflow", "saturate"))

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        """Called once before simulation with the resolved widths. Raise ``ValueError`` if they are invalid."""
        self.in_widths = in_widths
        self.out_widths = out_widths

    def direct_feedthrough(self) -> bool:
        """Whether outputs depend directly on inputs. Called after :meth:`configure`."""
        return self.DIRECT_FEEDTHROUGH

    def initial_continuous_state(self) -> Array:
        return EMPTY

    def initial_discrete_state(self) -> Array:
        return EMPTY

    def zero_crossings(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array | None:
        """Signals whose sign changes exactly where the block's output (or derivative) is discontinuous,
        e.g. ``u - upper`` for a saturation. Variable-step solvers locate these events precisely. Return
        ``None`` (the default) if the block has none."""
        return None

    def compute_mode(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array | None:
        """Which branch of a discontinuity the block is on (e.g. -1/0/+1 for lower/linear/upper of a saturation).

        Blocks with :meth:`zero_crossings` can implement this. The simulator freezes the mode during each
        integration step so the equations stay smooth, and switches it only at a located zero crossing. This is
        what makes discontinuities exact. While :attr:`mode` is ``None`` the block picks its branch itself.
        """
        return None

    def breakpoints(self, t_start: float, t_final: float) -> list[float]:
        """Times where the block's output is discontinuous (e.g. a step). Variable-step solvers stop exactly
        at these times instead of stepping over them."""
        return []

    # ------------------------------------------------------------------ run-time equations

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        raise NotImplementedError(f"{type(self).__name__}.outputs")

    def derivatives(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        return np.zeros_like(xc)

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        return xd

    # ------------------------------------------------------------------ misc

    def result_aliases(self) -> dict[str, int]:
        """Extra names under which this block's *input* signals appear in the simulation result,
        mapped to the input port index (used by To Workspace)."""
        return {}

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name!r}>"


__all__ = [
    "CONTINUOUS",
    "INHERITED",
    "Block",
    "InPort",
    "OutPort",
    "Width",
    "broadcast_widths",
]
