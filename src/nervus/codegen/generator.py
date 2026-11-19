"""Generate embedded C code from a discrete-time model.

The generated code is plain C99 with static memory only (no malloc, no recursion), in the style of
Simulink Embedded Coder:

* ``<model>.h`` declares the structs and the API.
* ``<model>.c`` contains ``<model>_initialize()`` and ``<model>_step()``.

Call ``<model>_initialize()`` once, then ``<model>_step()`` every base period (e.g. from a 10 ms task). Before
each step, write the inputs to ``<model>_U``; after it, read the outputs from ``<model>_Y``. Tunable
parameters are in ``<model>_P``. A parameter given as a bare workspace variable (``Kp``) becomes one shared
field named after the variable, which a calibration tool can change at run time.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from nervus import __version__
from nervus.blocks.ports import Inport, Outport, PortProxy
from nervus.codegen.a2l import generate_a2l
from nervus.core.block import Block
from nervus.core.diagram import Diagram
from nervus.core.errors import ModelError
from nervus.sim.compiler import CompiledModel, Kind, compile_diagram


class CodegenError(ModelError):
    """The model (or a block in it) cannot be turned into C code."""


def c_identifier(name: str) -> str:
    """Turn a block path like ``ECU/throttle pi`` into a valid C identifier ``ECU_throttle_pi``."""
    s = re.sub(r"[^0-9A-Za-z_]", "_", name)
    if not s or s[0].isdigit():
        s = "b_" + s
    return s


def c_float(v: float) -> str:
    if math.isinf(v):
        return "INFINITY" if v > 0 else "(-INFINITY)"
    if math.isnan(v):
        return "NAN"
    r = repr(float(v))
    return r if ("." in r or "e" in r) else r + ".0"


@dataclass
class _Field:
    name: str
    size: int
    init: list[float]
    comment: str = ""


@dataclass
class BlockCode:
    outputs: list[str] = field(default_factory=list)
    update: list[str] = field(default_factory=list)


class Emitter:
    """Helper handed to each block's code template."""

    def __init__(self, gen: CGenerator, index: int) -> None:
        self.gen = gen
        self.i = index
        self.block = gen.model.blocks[index]
        self.path = gen.model.names[index]
        self.cname = gen.cnames[index]
        self.in_widths = gen.model.in_widths[index]
        self.out_widths = gen.model.out_widths[index]

    # signals --------------------------------------------------------------

    def u(self, port: int, ix: str = "i") -> str:
        s, p = self.gen.model.inputs[self.i][port]
        var = self.gen.signal_var(s, p)
        return f"{var}[0]" if self.gen.model.out_widths[s][p] == 1 else f"{var}[{ix}]"

    def u_var(self, port: int) -> str:
        s, p = self.gen.model.inputs[self.i][port]
        return self.gen.signal_var(s, p)

    def y(self, port: int = 0, ix: str = "i") -> str:
        return f"{self.gen.signal_var(self.i, port)}[{ix}]"

    def w(self, port: int = 0) -> int:
        return self.out_widths[port]

    # parameters and states --------------------------------------------------

    def param(self, pname: str, value: Any = None) -> str:
        """A tunable parameter field; returns the C expression of the field (an array name or scalar)."""
        value = self.block.params[pname] if value is None else value
        arr = np.atleast_1d(np.asarray(value, dtype=float)).ravel()
        expr = self.block.expressions.get(pname, "").strip()
        if expr.isidentifier() and expr in self.gen.namespace:
            fname = c_identifier(expr)  # shared calibration parameter named after the variable
            comment = f"workspace variable {expr}"
        else:
            fname = f"{self.cname}_{pname}"
            comment = f"{self.path}: {pname}" + (f" = {expr}" if expr else "")
        self.gen.add_param(fname, arr, comment)
        return f"{self.gen.prefix}_P.{fname}"

    def p(self, pname: str, ix: str = "i", value: Any = None) -> str:
        """Element ``ix`` of a parameter (or the scalar), with scalar expansion."""
        field_expr = self.param(pname, value)
        size = self.gen.params[field_expr.split(".", 1)[1]].size
        return f"{field_expr}[0]" if size == 1 else f"{field_expr}[{ix}]"

    def state(self, sname: str, init: Iterable[float], comment: str = "") -> str:
        values = [float(v) for v in np.atleast_1d(np.asarray(list(init), dtype=float))]
        fname = f"{self.cname}_{sname}"
        self.gen.states[fname] = _Field(fname, max(1, len(values)), values or [0.0], comment or self.path)
        return f"{self.gen.prefix}_DW.{fname}"

    @property
    def period(self) -> float:
        return self.block.period()

    # loops --------------------------------------------------------------------

    def each(self, width: int, body: Callable[[str], list[str]]) -> list[str]:
        if width == 1:
            return body("0")
        lines = body("i")
        return [f"for (i = 0; i < {width}; i++) {{", *[f"    {line}" for line in lines], "}"]


Template = Callable[[Emitter], BlockCode]
TEMPLATES: dict[str, Template] = {}


def template(*type_ids: str) -> Callable[[Template], Template]:
    """Register a C code template for one or more block types (also usable for custom blocks)."""

    def deco(fn: Template) -> Template:
        for t in type_ids:
            TEMPLATES[t] = fn
        return fn

    return deco


@dataclass
class GeneratedCode:
    name: str
    files: dict[str, str]
    base_period: float
    rates: list[float]
    inputs: list[tuple[str, int]]
    """(C field name, width) of each input, in port order."""
    outputs: list[tuple[str, int]]
    params: dict[str, list[float]]
    model: CompiledModel

    @property
    def c_files(self) -> dict[str, str]:
        """The files that belong in the ECU project (no SIL accessors, examples or report)."""
        return {k: v for k, v in self.files.items() if k in (f"{self.name}.h", f"{self.name}.c")}

    def write(self, folder: str | Path) -> list[Path]:
        out = Path(folder)
        out.mkdir(parents=True, exist_ok=True)
        paths = []
        for fname, text in self.files.items():
            p = out / fname
            p.write_text(text, encoding="utf-8")
            paths.append(p)
        return paths


class CGenerator:
    def __init__(self, model: CompiledModel, name: str) -> None:
        self.model = model
        self.prefix = c_identifier(name)
        self.namespace = model.diagram.root.workspace.namespace()
        self.cnames = self._unique_cnames(model.names)
        self.params: dict[str, _Field] = {}
        self.states: dict[str, _Field] = {}

    @staticmethod
    def _unique_cnames(names: list[str]) -> list[str]:
        seen: dict[str, int] = {}
        out = []
        for n in names:
            c = c_identifier(n)
            if c in seen:
                seen[c] += 1
                c = f"{c}_{seen[c]}"
            else:
                seen[c] = 0
            out.append(c)
        return out

    def signal_var(self, block: int, port: int) -> str:
        return f"{self.prefix}_B.{self.cnames[block]}" + (f"_o{port}" if len(self.model.out_widths[block]) > 1 else "")

    def add_param(self, fname: str, values: np.ndarray, comment: str) -> None:
        existing = self.params.get(fname)
        vals = [float(v) for v in values]
        if existing is not None and existing.init != vals:
            raise CodegenError(f"parameter {fname} has conflicting values ({existing.init} vs {vals})")
        self.params[fname] = _Field(fname, len(vals), vals, comment)

    # ------------------------------------------------------------------ checks

    def _check(self) -> None:
        m = self.model
        problems = []
        for i, b in enumerate(m.blocks):
            if m.xc_slices[i].stop > m.xc_slices[i].start:
                problems.append(f"{m.names[i]}: continuous states (only discrete-time blocks can become C code)")
            elif b.type_id not in TEMPLATES and not isinstance(b, PortProxy):
                problems.append(f"{m.names[i]}: no C code template for block type {b.type_id or type(b).__name__!r}")
        if problems:
            raise CodegenError(
                "cannot generate C code:\n  - "
                + "\n  - ".join(problems)
                + "\nGenerate code for the controller subsystem only, with In/Out blocks at its boundary.",
                tuple(p.split(":", 1)[0] for p in problems),
            )
        if not m.rates:
            raise CodegenError("the model has no discrete sample time; set the sample time of at least one block")

    # ------------------------------------------------------------------ generation

    def generate(self) -> GeneratedCode:
        self._check()
        m = self.model
        periods = [Fraction(v).limit_denominator(10**9) for r in m.rates for v in (r.period, r.offset) if v]
        base = periods[0]
        for v in periods[1:]:
            base = Fraction(
                math.gcd(base.numerator * v.denominator, v.numerator * base.denominator),
                base.denominator * v.denominator,
            )
        base_period = float(base)
        steps = [(round(r.period / base_period), round(r.offset / base_period)) for r in m.rates]

        codes: list[BlockCode] = []
        for i, b in enumerate(m.blocks):
            if isinstance(b, PortProxy):
                codes.append(_pass_through(Emitter(self, i)))
            else:
                codes.append(TEMPLATES[b.type_id](Emitter(self, i)))

        inputs = [(i, b) for i, b in enumerate(m.blocks) if isinstance(b, Inport)]
        outputs = [(i, b) for i, b in enumerate(m.blocks) if isinstance(b, Outport)]
        inputs.sort(key=lambda x: x[1].params["port"])
        outputs.sort(key=lambda x: x[1].params["port"])
        in_fields = [(c_identifier(m.names[i]), m.out_widths[i][0]) for i, _ in inputs]
        out_fields = [(c_identifier(m.names[i]), m.in_widths[i][0]) for i, _ in outputs]

        header = self._header(in_fields, out_fields, base_period, steps)
        source = self._source(codes, steps, base_period)
        files = {
            f"{self.prefix}.h": header,
            f"{self.prefix}.c": source,
            f"{self.prefix}_sil.c": self._sil(in_fields, out_fields),
            "main_example.c": self._main_example(in_fields, out_fields, base_period),
            f"{self.prefix}_report.html": self._report(source, in_fields, out_fields, base_period, steps),
            f"{self.prefix}.a2l": generate_a2l(self),
        }
        return GeneratedCode(
            name=self.prefix,
            files=files,
            base_period=base_period,
            rates=[r.period for r in m.rates],
            inputs=in_fields,
            outputs=out_fields,
            params={k: v.init for k, v in self.params.items()},
            model=m,
        )

    def _banner(self, what: str) -> list[str]:
        return [
            "/*",
            f" * {what}",
            f" * Generated by Nervus {__version__} from model '{self.model.diagram.name}'. Do not edit by hand.",
            " */",
        ]

    @staticmethod
    def _struct(name: str, fields: list[tuple[str, int, str]]) -> list[str]:
        lines = ["typedef struct {"]
        if not fields:
            lines.append("    real_T dummy[1]; /* (empty) */")
        for fname, size, comment in fields:
            lines.append(f"    real_T {fname}[{size}];" + (f" /* {comment} */" if comment else ""))
        lines.append(f"}} {name};")
        return lines

    def _header(
        self, ins: list[tuple[str, int]], outs: list[tuple[str, int]], base: float, steps: list[tuple[int, int]]
    ) -> str:
        pfx = self.prefix
        guard = f"{pfx.upper()}_H"
        m = self.model
        signals = []
        for i, ws in enumerate(m.out_widths):
            for p, w in enumerate(ws):
                signals.append((self.signal_var(i, p).split(".", 1)[1], w, m.names[i]))
        lines = [
            *self._banner(f"{pfx}.h"),
            f"#ifndef {guard}",
            f"#define {guard}",
            "",
            "#include <stdint.h>",
            "",
            "typedef double real_T;",
            "typedef uint32_t uint32_T;",
            "",
            f"#define {pfx.upper()}_BASE_PERIOD ({c_float(base)}) /* seconds between calls to {pfx}_step() */",
            "",
            "/* Inputs: write before each step */",
            *self._struct(f"{pfx}_U_t", [(n, w, "") for n, w in ins]),
            "",
            "/* Outputs: read after each step */",
            *self._struct(f"{pfx}_Y_t", [(n, w, "") for n, w in outs]),
            "",
            "/* Tunable parameters (calibration) */",
            *self._struct(f"{pfx}_P_t", [(f.name, f.size, f.comment) for f in self.params.values()]),
            "",
            "/* Block signals */",
            *self._struct(f"{pfx}_B_t", signals),
            "",
            "/* States */",
            *self._struct(f"{pfx}_DW_t", [(f.name, f.size, f.comment) for f in self.states.values()]),
            "",
            f"extern {pfx}_U_t {pfx}_U;",
            f"extern {pfx}_Y_t {pfx}_Y;",
            f"extern {pfx}_P_t {pfx}_P;",
            f"extern {pfx}_B_t {pfx}_B;",
            f"extern {pfx}_DW_t {pfx}_DW;",
            "",
            f"void {pfx}_initialize(void);",
            f"void {pfx}_step(void);",
            "",
            f"#endif /* {guard} */",
            "",
        ]
        return "\n".join(lines)

    def _source(self, codes: list[BlockCode], steps: list[tuple[int, int]], base: float) -> str:
        pfx = self.prefix
        m = self.model

        def init_values(f: _Field) -> str:
            return "{" + ", ".join(c_float(v) for v in f.init) + "}"

        param_init = ",\n".join(f"    {init_values(f)} /* {f.name} */" for f in self.params.values()) or "    {0.0}"
        multirate = len(steps) > 1 or any(n > 1 or off for n, off in steps)

        body_out: list[str] = []
        body_upd: list[str] = []
        init_out: list[str] = []
        for i, code in enumerate(codes):
            kind, rate = m.kinds[i], m.rate_index[i]
            label = f"/* {m.names[i]} ({m.blocks[i].label or 'port'}) */"
            if kind is Kind.CONSTANT:
                if code.outputs:
                    init_out += [label, *code.outputs]
                continue
            guard = f"rt_hit[{rate}]" if (kind is Kind.DISCRETE and multirate) else None
            if code.outputs:
                if guard:
                    body_out += [label, f"if ({guard}) {{", *[f"    {x}" for x in code.outputs], "}"]
                else:
                    body_out += [label, *code.outputs]
            if code.update:
                if guard:
                    body_upd += [label, f"if ({guard}) {{", *[f"    {x}" for x in code.update], "}"]
                else:
                    body_upd += [label, *code.update]

        lines = [
            *self._banner(f"{pfx}.c"),
            f'#include "{pfx}.h"',
            "#include <math.h>",
            "",
            f"{pfx}_U_t {pfx}_U;",
            f"{pfx}_Y_t {pfx}_Y;",
            f"{pfx}_P_t {pfx}_P = {{",
            param_init,
            "};",
            f"{pfx}_B_t {pfx}_B;",
            f"{pfx}_DW_t {pfx}_DW;",
            "",
        ]
        if multirate:
            lines += [
                f"static uint32_T rt_count[{len(steps)}];",
                f"static const uint32_T rt_period[{len(steps)}] = {{" + ", ".join(f"{n}u" for n, _ in steps) + "};",
                f"static int rt_hit[{len(steps)}];",
                "",
            ]
        lines += [f"void {pfx}_initialize(void)", "{", "    uint32_T i;", "    (void)i;"]
        for f in self.states.values():
            if all(v == 0 for v in f.init):
                lines.append(f"    for (i = 0; i < {f.size}u; i++) {{ {pfx}_DW.{f.name}[i] = 0.0; }}")
            else:
                for k, v in enumerate(f.init):
                    lines.append(f"    {pfx}_DW.{f.name}[{k}] = {c_float(v)};")
        if multirate:
            for k, (n, off) in enumerate(steps):
                lines.append(
                    f"    rt_count[{k}] = {(n - off) % n}u; /* rate {k}: every {n} base steps, offset {off} */"
                )
        lines += [f"    {x}" for x in init_out]
        lines += ["}", "", f"void {pfx}_step(void)", "{", "    uint32_T i;", "    (void)i;"]
        if multirate:
            lines += [f"    for (i = 0; i < {len(steps)}u; i++) {{ rt_hit[i] = (rt_count[i] == 0u); }}"]
        lines += ["", "    /* outputs */", *[f"    {x}" for x in body_out]]
        lines += ["", "    /* state updates */", *[f"    {x}" for x in body_upd]]
        if multirate:
            lines += [
                "",
                "    /* advance the rate counters */",
                f"    for (i = 0; i < {len(steps)}u; i++) {{",
                "        rt_count[i] = (rt_count[i] + 1u == rt_period[i]) ? 0u : rt_count[i] + 1u;",
                "    }",
            ]
        lines += ["}", ""]
        return "\n".join(lines)

    def _main_example(self, ins: list[tuple[str, int]], outs: list[tuple[str, int]], base: float) -> str:
        """A template for the ECU side: how to call the generated code from a periodic task."""
        pfx = self.prefix
        read = [f"    {pfx}_U.{n}[{k}] = 0.0; /* TODO: read sensor */" for n, w in ins for k in range(w)]
        write = [f"    (void){pfx}_Y.{n}[{k}]; /* TODO: drive actuator */" for n, w in outs for k in range(w)]
        lines = [
            *self._banner("main_example.c: how to run the generated code on a target (a template)"),
            f'#include "{pfx}.h"',
            "",
            f"/* Call this every {pfx.upper()}_BASE_PERIOD = {base:g} s, e.g. from a timer interrupt or an RTOS task. */",
            f"void {pfx}_task(void)",
            "{",
            *read,
            f"    {pfx}_step();",
            *write,
            "}",
            "",
            "int main(void)",
            "{",
            f"    {pfx}_initialize();",
            "    for (;;) {",
            "        /* TODO: wait for the next period tick */",
            f"        {pfx}_task();",
            "    }",
            "}",
            "",
        ]
        return "\n".join(lines)

    def _report(
        self,
        source: str,
        ins: list[tuple[str, int]],
        outs: list[tuple[str, int]],
        base: float,
        steps: list[tuple[int, int]],
    ) -> str:
        """An HTML code generation report: interface, rates, parameters, and block-to-code traceability."""
        import html

        m = self.model
        rows = []
        lines = source.splitlines()
        for i, name in enumerate(m.names):
            marker = f"/* {name} ("
            found = [n + 1 for n, line in enumerate(lines) if line.strip().startswith(marker)]
            st = m.sample_times[i]
            links = ", ".join(f'<a href="#L{n}">{n}</a>' for n in found) or "—"
            rows.append(
                f"<tr><td>{html.escape(name)}</td><td>{html.escape(m.blocks[i].label or 'port')}</td>"
                f"<td>{html.escape(str(st))}</td><td>{links}</td></tr>"
            )
        code_html = "\n".join(
            f'<span id="L{n}" class="ln">{n:4d}</span>  {html.escape(line)}' for n, line in enumerate(lines, 1)
        )
        param_rows = []
        for f in self.params.values():
            values = ", ".join(f"{v:g}" for v in f.init[:8]) + (" …" if f.size > 8 else "")
            param_rows.append(
                f"<tr><td><code>{html.escape(f.name)}</code></td><td>{f.size}</td><td>{html.escape(values)}</td>"
                f"<td>{html.escape(f.comment)}</td></tr>"
            )
        params = "".join(param_rows)
        io = "".join(f"<tr><td>input</td><td><code>{n}</code></td><td>{w}</td></tr>" for n, w in ins) + "".join(
            f"<tr><td>output</td><td><code>{n}</code></td><td>{w}</td></tr>" for n, w in outs
        )
        rates = "".join(f"<li>rate {k}: every {n} base step(s), offset {off}</li>" for k, (n, off) in enumerate(steps))
        css = (
            "body{font-family:system-ui,sans-serif;margin:24px;color:#1d1d1b;background:#fcfcfb}"
            "table{border-collapse:collapse;margin:8px 0 20px}td,th{border:1px solid #dcdbd5;padding:4px 8px;text-align:left}"
            "pre{background:#f3f3f1;padding:12px;overflow:auto;font-size:12px}.ln{color:#86857f}"
            "@media (prefers-color-scheme: dark){body{background:#1a1a19;color:#f2f2ef}pre{background:#262625}"
            "td,th{border-color:#353532}a{color:#3987e5}}"
        )
        return f"""<!doctype html><html><head><meta charset="utf-8"><title>{self.prefix} code generation report</title>
<style>{css}</style></head><body>
<h1>Code generation report: {html.escape(self.prefix)}</h1>
<p>Model <b>{html.escape(m.diagram.name)}</b>, generated by Nervus {__version__}. Base period {base:g} s
(call <code>{self.prefix}_step()</code> every {base:g} s).</p>
<ul>{rates}</ul>
<h2>Interface</h2><table><tr><th>kind</th><th>field</th><th>width</th></tr>{io}</table>
<h2>Tunable parameters</h2><table><tr><th>field</th><th>size</th><th>value</th><th>source</th></tr>{params}</table>
<h2>Blocks and code</h2><table><tr><th>block</th><th>type</th><th>sample time</th><th>lines in {self.prefix}.c</th></tr>
{"".join(rows)}</table>
<h2>{self.prefix}.c</h2><pre>{code_html}</pre>
</body></html>
"""

    def _sil(self, ins: list[tuple[str, int]], outs: list[tuple[str, int]]) -> str:
        """Accessors used by the software-in-the-loop harness (not needed on the ECU)."""
        pfx = self.prefix
        lines = [
            *self._banner(f"{pfx}_sil.c: accessors for software-in-the-loop testing"),
            f'#include "{pfx}.h"',
            "#include <string.h>",
            "",
        ]
        lines += ["void nervus_sil_set_input(int k, const double *v)", "{", "    switch (k) {"]
        for k, (n, _w) in enumerate(ins):
            lines.append(f"    case {k}: memcpy({pfx}_U.{n}, v, sizeof({pfx}_U.{n})); break;")
        lines += ["    default: break;", "    }", "}", ""]
        lines += ["void nervus_sil_get_output(int k, double *v)", "{", "    switch (k) {"]
        for k, (n, _w) in enumerate(outs):
            lines.append(f"    case {k}: memcpy(v, {pfx}_Y.{n}, sizeof({pfx}_Y.{n})); break;")
        lines += ["    default: break;", "    }", "}", ""]
        lines += [
            f"void nervus_sil_initialize(void) {{ {pfx}_initialize(); }}",
            f"void nervus_sil_step(void) {{ {pfx}_step(); }}",
            "",
        ]
        return "\n".join(lines)


def _pass_through(e: Emitter) -> BlockCode:
    """Subsystem port: copy the signal (the C compiler optimises this away)."""

    def body(ix: str) -> list[str]:
        return [f"{e.y(0, ix)} = {e.u(0, ix)};"]

    return BlockCode(outputs=e.each(e.w(), body))


def generate_c(target: Diagram | Block, name: str | None = None) -> GeneratedCode:
    """Generate C code for a model, or for a subsystem of a model.

    For a subsystem, its In/Out blocks become the inputs and outputs of the generated code, and the rest of
    the model (e.g. the plant) is left out. Every block in the generated part must be discrete-time (or
    constant/stateless) and have a C template.
    """
    system = getattr(target, "system", None)
    diagram = system if isinstance(system, Diagram) else target
    if not isinstance(diagram, Diagram):
        raise TypeError("generate_c needs a Diagram or a Subsystem block")
    model = compile_diagram(diagram)
    label = name or (target.name if isinstance(target, Block) else diagram.name) or "model"
    return CGenerator(model, label).generate()


# Register the block templates.
from nervus.codegen import templates as _templates  # noqa: E402,F401
