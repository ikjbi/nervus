"""Reusable functions for subsystems in the generated C code.

A subsystem whose *function_name* is set is not written into the model's code block by block (inline): it becomes
one C function, shared by every subsystem with the same function name, and called once per subsystem with that
subsystem's own data (its inputs, outputs, signals, states and calibration parameters)::

    void cyl_trim_initialize(cyl_trim_B_t *B, cyl_trim_DW_t *DW);
    void cyl_trim_output(const cyl_trim_U_t *U, cyl_trim_Y_t *Y, cyl_trim_B_t *B, cyl_trim_DW_t *DW,
                         const cyl_trim_P_t *P);
    void cyl_trim_update(cyl_trim_B_t *B, cyl_trim_DW_t *DW, const cyl_trim_P_t *P);

The model calls ``_output`` where the subsystem's blocks would compute their outputs and ``_update`` where they would
update their states, so the code does exactly what the inline code (and the simulation) does. The instances' data is
``<model>_<subsystem>_U``, ``_Y``, ``_B``, ``_DW`` and the calibratable ``<model>_<subsystem>_P``.

The subsystems must have the same contents (their generated function must be identical), run at one rate (their
own *sample_time*, or blocks with one rate inside) and have no enable or trigger port.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from typing import Any

from nervus.codegen.generator import CGenerator, CodegenError, GeneratedCode
from nervus.core.block import Block, Width
from nervus.core.diagram import Diagram
from nervus.core.sample_time import SampleTime
from nervus.core.types import Array
from nervus.sim.compiler import compile_diagram


class FunctionCall(Block):
    """Stands for one reusable subsystem while the model's code is generated (never simulated)."""

    type_id = "codegen.function_call"
    label = "Function call"
    PARAMS = ()

    def __init__(self, function: str, instance: str, code: GeneratedCode, initializer: str,
                 feedthrough: list[int], period: float, files: dict[str, str], fields: list[Any]) -> None:  # fmt: skip
        super().__init__()
        self.function, self.instance, self.code, self.fields = function, instance, code, fields
        self.initializer, self._feedthrough, self._period, self.files = initializer, feedthrough, period, files

    def num_inputs(self) -> int:
        return len(self.code.inputs)

    def num_outputs(self) -> int:
        return len(self.code.outputs)

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [w for _n, w in self.code.outputs]

    def feedthrough_ports(self) -> list[int]:
        return self._feedthrough

    def direct_feedthrough(self) -> bool:
        return bool(self._feedthrough)

    def sample_time(self) -> SampleTime:
        return SampleTime.from_value(self._period)

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        raise NotImplementedError("a function call block only exists while code is generated")


def _feedthrough(code: GeneratedCode) -> list[int]:
    """The inputs whose values reach an output within the same step (through blocks with direct feedthrough)."""
    m = code.model
    from nervus.blocks.ports import Inport, Outport

    ports = {i: int(b.params["port"]) - 1 for i, b in enumerate(m.blocks) if isinstance(b, Inport)}
    outs = {i for i, b in enumerate(m.blocks) if isinstance(b, Outport)}
    users: dict[int, list[int]] = {}
    for i, b in enumerate(m.blocks):
        through = set(b.feedthrough_ports())
        for port, (src, _p) in enumerate(m.inputs[i]):
            if port in through:
                users.setdefault(src, []).append(i)
    result = []
    for start, port in sorted(ports.items(), key=lambda kv: kv[1]):
        seen, todo = {start}, [start]
        while todo:
            for nxt in users.get(todo.pop(), []):
                if nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        if seen & outs:
            result.append(port)
    return result


def _function_for(sub: Block, function: str) -> tuple[GeneratedCode, CGenerator, float]:
    system = getattr(sub, "system", None)
    if not isinstance(system, Diagram):
        raise CodegenError(f"{sub.name}: only subsystems can become reusable functions", (sub.name,))
    if sub.params.get("enable_port") or sub.params.get("trigger", "none") != "none":
        raise CodegenError(f"{sub.name}: a reusable function cannot have an enable or trigger port", (sub.name,))
    if sub.diagram is not None:
        sub.resolve(sub.diagram.namespace())
    st = sub.sample_time()
    rate = None if st.is_inherited else st
    gen = CGenerator(compile_diagram(system, default_rate=rate), function, reusable=True)
    try:
        code = gen.generate()
    except CodegenError as exc:
        raise CodegenError(f"{sub.name} (function {function}): {exc}", exc.blocks or (sub.name,)) from exc
    return code, gen, code.base_period


def replace_with_calls(diagram: Diagram) -> Diagram:
    """A copy of ``diagram`` in which every subsystem with a *function_name* is a :class:`FunctionCall`."""
    work = copy.deepcopy(diagram)
    groups: dict[str, list[Block]] = {}
    for _path, b in work.walk():
        name = str(b.params.get("function_name", "") or "").strip() if "function_name" in b.params else ""
        if name:
            groups.setdefault(name, []).append(b)
    for function, subs in groups.items():
        if not function.isidentifier():
            raise CodegenError(f"function name '{function}' is not a valid C name", tuple(s.name for s in subs))
        generated = [(s, *_function_for(s, function)) for s in subs]
        ref_code = generated[0][1]
        for s, code, _gen, _period in generated[1:]:
            if code.files[f"{function}.c"] != ref_code.files[f"{function}.c"]:
                raise CodegenError(
                    f"{s.name} and {subs[0].name} share the function name '{function}' but not their contents "
                    "(blocks, wiring or parameter names); give them different function names",
                    (s.name, subs[0].name),
                )
        feed = _feedthrough(ref_code)
        files = {f"{function}.h": ref_code.files[f"{function}.h"], f"{function}.c": ref_code.files[f"{function}.c"]}
        for s, code, gen, period in generated:
            parent = s.diagram
            assert parent is not None
            call = FunctionCall(
                function, s.name, code, gen.param_initializer(), feed, period, files, gen.param_fields()
            )
            conns = [c for c in parent.connections if c.src is s or c.dst is s]
            position = s.meta.get("position")
            name = s.name
            parent.remove(s)
            parent.add(call, name=name)
            if position is not None:
                call.meta["position"] = position
            for c in conns:
                src = call if c.src is s else c.src
                dst = call if c.dst is s else c.dst
                parent.connect((src, c.src_port), (dst, c.dst_port))
    return work


def has_functions(diagram: Diagram) -> bool:
    return any(
        str(b.params.get("function_name", "") or "").strip() for _p, b in diagram.walk() if "function_name" in b.params
    )


def instance_name(gen: Any, block_name: str) -> str:
    from nervus.codegen.generator import c_identifier

    return f"{gen.prefix}_{c_identifier(block_name)}"
