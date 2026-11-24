"""Software-in-the-loop (SIL) testing: run the generated C and compare it with the Python simulation.

This is the "back-to-back" test used in model-based development: the same input sequence goes into the model
(in Python) and into the compiled code, and the outputs must agree within a tolerance.
"""

from __future__ import annotations

import ctypes
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from nervus.blocks.ports import Inport, Outport
from nervus.codegen.generator import CodegenError, GeneratedCode, c_identifier, generate_c
from nervus.core.block import Block
from nervus.core.diagram import Diagram
from nervus.core.types import Array
from nervus.sim.compiler import CompiledModel
from nervus.sim.simulator import _RateScheduler


def find_compiler() -> str | None:
    for cc in ("cc", "gcc", "clang"):
        path = shutil.which(cc)
        if path:
            return path
    return None


def build_shared_library(code: GeneratedCode, folder: str | Path | None = None) -> Path:
    """Compile the generated code (plus SIL accessors) into a shared library. Returns its path."""
    cc = find_compiler()
    if cc is None:
        raise CodegenError("no C compiler found (install gcc or clang) for software-in-the-loop testing")
    out = Path(folder) if folder is not None else Path(tempfile.mkdtemp(prefix="nervus_sil_"))
    code.write(out)
    lib = out / f"lib{code.name}_sil.so"
    cmd = [
        cc,
        "-std=c99",
        "-O2",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic",
        "-shared",
        "-fPIC",
        "-o",
        str(lib),
        str(out / f"{code.name}.c"),
        str(out / f"{code.name}_sil.c"),
        *[str(out / f) for f in code.extra_sources if f.endswith(".c")],  # reusable subsystem functions
        "-lm",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise CodegenError(f"the generated code does not compile:\n{proc.stderr}")
    return lib


def _input_table(code: GeneratedCode, inputs: dict[str, Any], steps: int) -> list[Array]:
    """One (steps, width) array per input port, from a dict keyed by In block name."""
    tables = []
    for name, width in code.inputs:
        match = [k for k in inputs if c_identifier(k) == name]
        if not match:
            raise CodegenError(f"no values given for input {name!r}")
        arr = np.asarray(inputs[match[0]], dtype=float)
        if arr.ndim == 0:
            arr = np.full((steps, width), float(arr))
        arr = arr.reshape(arr.shape[0], -1)
        if arr.shape[0] == 1:
            arr = np.repeat(arr, steps, axis=0)
        if arr.shape != (steps, width) and arr.shape[1] == 1:
            arr = np.repeat(arr, width, axis=1)
        if arr.shape != (steps, width):
            raise CodegenError(f"input {name!r} must have shape ({steps}, {width}), got {arr.shape}")
        tables.append(arr)
    return tables


class SilModel:
    """The compiled generated code, driven step by step from Python."""

    def __init__(self, code: GeneratedCode, folder: str | Path | None = None) -> None:
        self.code = code
        self.library_path = build_shared_library(code, folder)
        self.lib = ctypes.CDLL(str(self.library_path))
        dbl_p = ctypes.POINTER(ctypes.c_double)
        self.lib.nervus_sil_set_input.argtypes = [ctypes.c_int, dbl_p]
        self.lib.nervus_sil_get_output.argtypes = [ctypes.c_int, dbl_p]

    def run(self, inputs: dict[str, Any], steps: int) -> dict[str, Array]:
        """Initialize, then call the step function ``steps`` times. Returns each output as (steps, width)."""
        tables = _input_table(self.code, inputs, steps)
        results = {name: np.zeros((steps, w)) for name, w in self.code.outputs}
        buf = {name: (ctypes.c_double * w)() for name, w in self.code.outputs}
        self.lib.nervus_sil_initialize()
        for k in range(steps):
            for j, table in enumerate(tables):
                row = np.ascontiguousarray(table[k])
                self.lib.nervus_sil_set_input(j, row.ctypes.data_as(ctypes.POINTER(ctypes.c_double)))
            self.lib.nervus_sil_step()
            for j, (name, _w) in enumerate(self.code.outputs):
                self.lib.nervus_sil_get_output(j, buf[name])
                results[name][k] = np.ctypeslib.as_array(buf[name])
        return results


def run_python(code: GeneratedCode, inputs: dict[str, Any], steps: int) -> dict[str, Array]:
    """Step the Python model at the base period with the same inputs (the reference for SIL)."""
    model: CompiledModel = code.model
    model.reset()
    tables = _input_table(code, inputs, steps)
    in_nodes = sorted(
        ((i, b) for i, b in enumerate(model.blocks) if isinstance(b, Inport)), key=lambda x: x[1].params["port"]
    )
    out_nodes = sorted(
        ((i, b) for i, b in enumerate(model.blocks) if isinstance(b, Outport)), key=lambda x: x[1].params["port"]
    )
    saved = [b.params["value"] for _, b in in_nodes]
    sched = _RateScheduler(model.rates, 0.0)
    xc = model.xc0.copy()
    results = {name: np.zeros((steps, w)) for name, w in code.outputs}
    try:
        for k in range(steps):
            t = k * code.base_period
            for (_i, b), table in zip(in_nodes, tables, strict=True):
                b.params["value"] = table[k].copy()
            hits = sched.hits(t)
            model.eval_outputs(t, xc, hits, init=(k == 0))
            for (i, _b), (name, _w) in zip(out_nodes, code.outputs, strict=True):
                s, p = model.inputs[i][0]
                results[name][k] = model.y[s][p]
            model.update(t, xc, hits)
            sched.advance(hits)
    finally:
        for (_i, b), v in zip(in_nodes, saved, strict=True):
            b.params["value"] = v
    return results


@dataclass
class SilComparison:
    steps: int
    max_abs_error: dict[str, float]
    python: dict[str, Array]
    c: dict[str, Array]
    tolerance: float

    @property
    def passed(self) -> bool:
        return all(e <= self.tolerance for e in self.max_abs_error.values())

    def summary(self) -> str:
        lines = [f"Back-to-back test, {self.steps} steps: {'PASSED' if self.passed else 'FAILED'}"]
        for name, err in self.max_abs_error.items():
            lines.append(f"  {name}: max |C - Python| = {err:.3g}")
        return "\n".join(lines)


def back_to_back(
    target: Diagram | Block,
    inputs: dict[str, Any],
    steps: int,
    tolerance: float = 1e-9,
    folder: str | Path | None = None,
    tasks: bool = False,
) -> SilComparison:
    """Generate code for ``target``, run it and the Python model with ``inputs``, and compare the outputs."""
    code = generate_c(target, tasks=tasks)
    c_out = SilModel(code, folder).run(inputs, steps)
    py_out = run_python(code, inputs, steps)
    errors = {name: float(np.max(np.abs(c_out[name] - py_out[name]))) if steps else 0.0 for name, _ in code.outputs}
    return SilComparison(steps, errors, py_out, c_out, tolerance)
