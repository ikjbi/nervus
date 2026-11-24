"""FMU block: run a Functional Mock-up Unit (FMI 2.0 co-simulation) inside a model."""

from __future__ import annotations

import atexit
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from nervus.blocks.registry import register
from nervus.core.block import Block, Width
from nervus.core.errors import ParameterError, install_hint
from nervus.core.params import Param, ParamKind
from nervus.core.sample_time import SampleTime
from nervus.core.types import Array

_OPEN: list[Any] = []


def _close_all() -> None:
    for fmu in _OPEN:
        try:
            fmu.terminate()
            fmu.freeInstance()
        except Exception:  # the FMU may already be gone at exit
            pass
    _OPEN.clear()


atexit.register(_close_all)


@register
class FMU(Block):
    """Runs an **FMU** (Functional Mock-up Unit, FMI 2.0 co-simulation) from another tool: Simulink, Dymola,
    OpenModelica, SimulationX, AMESim, CANoe, or Nervus itself (``Code ▸ Export FMU``). The block's ports are the
    FMU's real-valued inputs and outputs, in the order of its model description.

    The FMU is a **co-simulation** slave: every *sample_time* (the communication step; 0 = the FMU's default step)
    the block sets the inputs, lets the FMU advance by one step, and reads the outputs, which it holds until the
    next step. The outputs therefore lag the inputs by one communication step, as in every co-simulation.
    *parameters* sets the FMU's parameters before it starts, e.g. ``Kp = 2.0, Ki = 30``. Needs fmpy
    (``uv sync --extra fmi``).
    """

    type_id = "fmi.fmu"
    label = "FMU"
    category = "Ports & Subsystems"
    DIRECT_FEEDTHROUGH = False
    PARAMS = (
        Param("fmu_file", "", ParamKind.STR, "FMU file (relative paths are relative to the model file)"),
        Param("parameters", "", ParamKind.STR, "Parameter values for the FMU, e.g. Kp = 2.0, Ki = 30"),
        Param("sample_time", 0.0, ParamKind.SAMPLE_TIME, "Communication step; 0 = the FMU's default step", "s"),
    )

    # ------------------------------------------------------------------ the FMU's description

    def _path(self) -> Path:
        p = Path(str(self.params["fmu_file"]))
        root = self.diagram.root if self.diagram is not None else None
        source = getattr(root, "source_path", None)
        if not p.is_absolute() and source is not None and (Path(source).parent / p).exists():
            return Path(source).parent / p
        return p

    def description(self) -> Any:
        try:
            from fmpy import read_model_description
        except ImportError as exc:
            raise ParameterError(f"FMUs need fmpy: {install_hint('fmi')}") from exc
        path = self._path()
        if not str(self.params["fmu_file"]):
            raise ParameterError("choose an FMU file")
        if not path.exists():
            raise ParameterError(f"FMU not found: {path}")
        key = (str(path.resolve()), path.stat().st_mtime)
        if getattr(self, "_md_key", None) != key:
            md = read_model_description(str(path))
            if md.coSimulation is None:
                raise ParameterError(f"{path.name} is not a co-simulation FMU")
            self._md, self._md_key = md, key
        return self._md

    def _vars(self, causality: str) -> list[Any]:
        try:
            md = self.description()
        except ParameterError:
            return []
        return [v for v in md.modelVariables if v.causality == causality and v.type == "Real"]

    def num_inputs(self) -> int:
        return len(self._vars("input"))

    def input_names(self) -> list[str]:
        return [v.name for v in self._vars("input")]

    def num_outputs(self) -> int:
        return max(1, len(self._vars("output")))

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [1] * self.num_outputs()

    def sample_time(self) -> SampleTime:
        if float(self.params["sample_time"]) == 0.0:
            try:
                step = self.description().defaultExperiment.stepSize
            except (ParameterError, AttributeError):
                step = None
            return SampleTime.from_value(float(step) if step else 0.01)
        return super().sample_time()

    def _parameter_values(self) -> dict[str, float]:
        out = {}
        for item in str(self.params["parameters"]).replace(";", ",").split(","):
            if "=" in item:
                k, v = item.split("=", 1)
                out[k.strip()] = float(v)
        return out

    def validate_params(self) -> None:
        if not str(self.params["fmu_file"]):
            return
        if self.diagram is None and not Path(str(self.params["fmu_file"])).is_absolute():
            return  # a relative path: checked once the block is in a model (next to the model file)
        md = self.description()
        names = {v.name for v in md.modelVariables if v.causality == "parameter"}
        unknown = set(self._parameter_values()) - names
        if unknown:
            raise ParameterError(f"the FMU has no parameter(s) {', '.join(sorted(unknown))}")

    # ------------------------------------------------------------------ running it

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        from fmpy import extract
        from fmpy.fmi2 import FMU2Slave

        super().configure(in_widths, out_widths)
        md = self.description()
        old = getattr(self, "_fmu", None)
        if old is not None:
            try:
                old.terminate()
                old.freeInstance()
            except Exception:  # a crashed instance: start a new one anyway
                pass
            if old in _OPEN:
                _OPEN.remove(old)
        if getattr(self, "_unzipped_key", None) != self._md_key:
            self._unzipped = extract(str(self._path()))
            self._unzipped_key = self._md_key
        fmu = FMU2Slave(guid=md.guid, unzipDirectory=self._unzipped, modelIdentifier=md.coSimulation.modelIdentifier,
                        instanceName=self.name or "fmu")  # fmt: skip
        try:
            fmu.instantiate()
        except Exception as exc:
            raise ValueError(f"the FMU {self._path().name} could not be started: {exc}") from exc
        by_name = {v.name: v.valueReference for v in md.modelVariables}
        fmu.setupExperiment(startTime=0.0)
        fmu.enterInitializationMode()
        for name, value in self._parameter_values().items():
            fmu.setReal([by_name[name]], [value])
        fmu.exitInitializationMode()
        self._fmu = fmu
        _OPEN.append(fmu)
        self._in_vr = [v.valueReference for v in self._vars("input")]
        self._out_vr = [v.valueReference for v in self._vars("output")]

    def initial_discrete_state(self) -> Array:
        fmu = getattr(self, "_fmu", None)
        if fmu is None or not self._out_vr:
            return np.zeros(self.num_outputs())
        return np.asarray(fmu.getReal(self._out_vr), dtype=float)

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [np.array([v]) for v in xd]

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        fmu = self._fmu
        if self._in_vr:
            fmu.setReal(self._in_vr, [float(np.ravel(x)[0]) for x in u])
        fmu.doStep(currentCommunicationPoint=t, communicationStepSize=self.period())
        return np.asarray(fmu.getReal(self._out_vr), dtype=float) if self._out_vr else xd
