"""Qt model holding the state and result of the latest simulation run."""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QObject, Signal

from nervus.sim import SimResult


class SimulationState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    FINISHED = "finished"
    STOPPED = "stopped"
    FAILED = "failed"


class SimulationModel(QObject):
    stateChanged = Signal(object)  # SimulationState
    progressChanged = Signal(float)  # fraction 0..1
    resultChanged = Signal(object)  # SimResult | None
    errorOccurred = Signal(str, tuple)  # message, block names

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state = SimulationState.IDLE
        self._result: SimResult | None = None
        self._error: str = ""

    @property
    def state(self) -> SimulationState:
        return self._state

    @property
    def result(self) -> SimResult | None:
        return self._result

    @property
    def error(self) -> str:
        return self._error

    @property
    def is_running(self) -> bool:
        return self._state is SimulationState.RUNNING

    def set_state(self, state: SimulationState) -> None:
        if state is not self._state:
            self._state = state
            self.stateChanged.emit(state)

    def set_progress(self, fraction: float) -> None:
        self.progressChanged.emit(max(0.0, min(1.0, fraction)))

    def set_result(self, result: SimResult | None) -> None:
        self._result = result
        self.resultChanged.emit(result)

    def set_error(self, message: str, blocks: tuple[str, ...] = ()) -> None:
        self._error = message
        self.errorOccurred.emit(message, blocks)
