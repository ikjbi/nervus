"""Sink blocks: blocks without outputs that display or store signals."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from nervus.blocks.registry import register
from nervus.core.block import Block
from nervus.core.errors import ParameterError
from nervus.core.params import Param, ParamKind
from nervus.core.types import Array

CATEGORY = "Sinks"


class _Sink(Block):
    category = CATEGORY
    NUM_OUTPUTS = 0
    DIRECT_FEEDTHROUGH = False

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return []


@register
class Scope(_Sink):
    """Plots its input signals. In scripts, read the data with ``result.inputs("scope_name")``."""

    type_id = "sinks.scope"
    label = "Scope"
    LOGS_INPUTS = True
    PARAMS = (Param("num_inputs", 1, ParamKind.INT, "Number of inputs", min=1),)

    def num_inputs(self) -> int:
        return int(self.params["num_inputs"])


@register
class ToWorkspace(_Sink):
    """Saves its input in the simulation result under *variable*, so ``result[variable]`` returns it."""

    type_id = "sinks.to_workspace"
    label = "To Workspace"
    LOGS_INPUTS = True
    PARAMS = (Param("variable", "simout", ParamKind.STR, "Name in the result"),)

    def validate_params(self) -> None:
        if not self.params["variable"].isidentifier():
            raise ParameterError("variable must be a valid identifier")

    def result_aliases(self) -> dict[str, int]:
        return {self.params["variable"]: 0}


@register
class Terminator(_Sink):
    """Terminates an unused output, so the diagram has no unconnected-output warnings."""

    type_id = "sinks.terminator"
    label = "Terminator"


@register
class StopSimulation(_Sink):
    """Stops the simulation at the first major time step where the input is non-zero (true).

    Use it to end a run when something happens, e.g. when the engine stalls or a test scenario is complete.
    The result contains everything up to that point.
    """

    type_id = "sinks.stop"
    label = "Stop Simulation"

    def check_major(self, t: float, u: Sequence[Array]) -> str | None:
        return "stop" if np.any(u[0] != 0) else None


@register
class Assertion(_Sink):
    """Fails the simulation with an error if the input is zero (false) at a major time step.

    Connect a condition that must always hold, e.g. ``engine_speed < 7000`` from a Compare To Constant block.
    The error message names the block and the time.
    """

    type_id = "sinks.assertion"
    label = "Assertion"
    PARAMS = (Param("message", "assertion failed", ParamKind.STR, "Error message"),)

    def check_major(self, t: float, u: Sequence[Array]) -> str | None:
        if np.any(u[0] == 0):
            return f"error:{self.params['message']} at t = {t:g}"
        return None
