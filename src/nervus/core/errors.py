"""Exception types raised by Nervus."""

from __future__ import annotations


class NervusError(Exception):
    """Base class for all Nervus errors."""


class ParameterError(NervusError, ValueError):
    """A block parameter has an invalid value."""


class ModelError(NervusError):
    """The diagram is structurally invalid (bad connections, widths, sample times, ...).

    ``blocks`` names the blocks involved, so a GUI can highlight them.
    """

    def __init__(self, message: str, blocks: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.blocks = blocks


class AlgebraicLoopError(ModelError):
    """A cycle of direct-feedthrough blocks without any state to break it."""


class SimulationError(NervusError):
    """An error that occurred while the simulation was running."""

    def __init__(self, message: str, blocks: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.blocks = blocks
