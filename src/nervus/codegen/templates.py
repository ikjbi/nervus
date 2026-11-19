"""C code templates for the standard blocks.

Each template receives an :class:`~nervus.codegen.generator.Emitter` and returns the C statements for the
block's output equation and (for blocks with state) its state update. Signals are ``real_T`` arrays; ``ix``
is the element index (``"0"`` for scalars, ``"i"`` inside a loop).
"""

from __future__ import annotations

import ast

import numpy as np

from nervus.codegen.generator import BlockCode, CodegenError, Emitter, c_float, template
from nervus.core.types import as_signal

# ---------------------------------------------------------------------------- ports, sources, sinks


@template("ports.inport")
def _inport(e: Emitter) -> BlockCode:
    from nervus.codegen.generator import c_identifier

    field = c_identifier(e.path)
    dtype = e.gen.model.out_types[e.i][0]
    scale = f" * {c_float(dtype.slope)} + {c_float(dtype.bias)}" if dtype.is_fixed and not dtype.is_integer else ""
    return BlockCode(e.each(e.w(), lambda ix: [f"{e.y(0, ix)} = (real_T){e.gen.prefix}_U.{field}[{ix}]{scale};"]))


@template("ports.outport")
def _outport(e: Emitter) -> BlockCode:
    from nervus.codegen.generator import c_identifier

    field = c_identifier(e.path)
    s, p = e.gen.model.inputs[e.i][0]
    dtype = e.gen.model.out_types[s][p]
    if dtype.is_double:
        return BlockCode(e.each(e.in_widths[0], lambda ix: [f"{e.gen.prefix}_Y.{field}[{ix}] = {e.u(0, ix)};"]))
    if dtype.is_fixed and not dtype.is_integer:

        def conv(ix: str) -> str:
            return f"({dtype.c_type})round(({e.u(0, ix)} - {c_float(dtype.bias)}) / {c_float(dtype.slope)})"
    else:

        def conv(ix: str) -> str:
            return f"({dtype.c_type}){e.u(0, ix)}"

    return BlockCode(e.each(e.in_widths[0], lambda ix: [f"{e.gen.prefix}_Y.{field}[{ix}] = {conv(ix)};"]))


@template("routing.datatype_conversion")
def _dtc(e: Emitter) -> BlockCode:
    return BlockCode(e.each(e.w(), lambda ix: [f"{e.y(0, ix)} = {e.u(0, ix)};"]))  # quantized afterwards


@template("sinks.scope", "sinks.to_workspace", "sinks.terminator", "sinks.stop", "sinks.assertion")
def _sink(e: Emitter) -> BlockCode:
    return BlockCode()  # simulation-only blocks: nothing on the target


@template("sources.constant")
def _constant(e: Emitter) -> BlockCode:
    return BlockCode(e.each(e.w(), lambda ix: [f"{e.y(0, ix)} = {e.p('value', ix)};"]))


@template("sources.ground")
def _ground(e: Emitter) -> BlockCode:
    return BlockCode([f"{e.y(0, '0')} = 0.0;"])


# ---------------------------------------------------------------------------- math


@template("math.gain")
def _gain(e: Emitter) -> BlockCode:
    if e.block.params["multiplication"] == "matrix":
        k = np.asarray(e.block.params["gain"], dtype=float)
        rows, cols = k.shape
        kp = e.param("gain", k.ravel())  # row-major
        u = e.u_var(0)
        return BlockCode(
            [
                f"for (i = 0; i < {rows}; i++) {{",
                "    uint32_T j;",
                f"    {e.y(0, 'i')} = 0.0;",
                f"    for (j = 0; j < {cols}u; j++) {{ {e.y(0, 'i')} += {kp}[i * {cols}u + j] * {u}[j]; }}",
                "}",
            ]
        )
    return BlockCode(e.each(e.w(), lambda ix: [f"{e.y(0, ix)} = {e.p('gain', ix)} * {e.u(0, ix)};"]))


@template("math.sum")
def _sum(e: Emitter) -> BlockCode:
    signs = e.block._signs()  # type: ignore[attr-defined]

    def body(ix: str) -> list[str]:
        terms = "".join(f" {'+' if s == '+' else '-'} {e.u(k, ix)}" for k, s in enumerate(signs))
        terms = terms.strip()
        if terms.startswith("+ "):
            terms = terms[2:]
        elif terms.startswith("- "):
            terms = "-" + terms[2:]
        return [f"{e.y(0, ix)} = {terms};"]

    return BlockCode(e.each(e.w(), body))


@template("math.product")
def _product(e: Emitter) -> BlockCode:
    ops = e.block.params["ops"]

    def body(ix: str) -> list[str]:
        expr = "1.0"
        for k, op in enumerate(ops):
            expr = f"{expr} {op} {e.u(k, ix)}"
        return [f"{e.y(0, ix)} = {expr};"]

    return BlockCode(e.each(e.w(), body))


@template("math.abs")
def _abs(e: Emitter) -> BlockCode:
    return BlockCode(e.each(e.w(), lambda ix: [f"{e.y(0, ix)} = fabs({e.u(0, ix)});"]))


@template("math.bias")
def _bias(e: Emitter) -> BlockCode:
    return BlockCode(e.each(e.w(), lambda ix: [f"{e.y(0, ix)} = {e.u(0, ix)} + {e.p('bias', ix)};"]))


@template("math.saturation")
def _saturation(e: Emitter) -> BlockCode:
    def body(ix: str) -> list[str]:
        lo, hi, u, y = e.p("lower", "0"), e.p("upper", "0"), e.u(0, ix), e.y(0, ix)
        return [f"{y} = ({u} > {hi}) ? {hi} : (({u} < {lo}) ? {lo} : {u});"]

    return BlockCode(e.each(e.w(), body))


_C_FUNCTIONS = {
    "exp": "exp({u})",
    "log": "log({u})",
    "log10": "log10({u})",
    "sqrt": "sqrt({u})",
    "square": "({u}) * ({u})",
    "reciprocal": "1.0 / ({u})",
    "sin": "sin({u})",
    "cos": "cos({u})",
    "tan": "tan({u})",
    "asin": "asin({u})",
    "acos": "acos({u})",
    "atan": "atan({u})",
    "sinh": "sinh({u})",
    "cosh": "cosh({u})",
    "tanh": "tanh({u})",
    "sign": "(({u}) > 0.0 ? 1.0 : (({u}) < 0.0 ? -1.0 : 0.0))",
    "floor": "floor({u})",
    "ceil": "ceil({u})",
    "round": "nearbyint({u})",
}


@template("math.function")
def _math_function(e: Emitter) -> BlockCode:
    fmt = _C_FUNCTIONS[e.block.params["function"]]
    return BlockCode(e.each(e.w(), lambda ix: [f"{e.y(0, ix)} = {fmt.format(u=e.u(0, ix))};"]))


@template("math.minmax")
def _minmax(e: Emitter) -> BlockCode:
    fn = "fmin" if e.block.params["function"] == "min" else "fmax"
    if e.block.num_inputs() == 1:
        w = e.in_widths[0]
        u = e.u_var(0)
        return BlockCode(
            [
                f"{e.y(0, '0')} = {u}[0];",
                f"for (i = 1; i < {w}; i++) {{ {e.y(0, '0')} = {fn}({e.y(0, '0')}, {u}[i]); }}",
            ]
        )

    def body(ix: str) -> list[str]:
        expr = e.u(0, ix)
        for k in range(1, e.block.num_inputs()):
            expr = f"{fn}({expr}, {e.u(k, ix)})"
        return [f"{e.y(0, ix)} = {expr};"]

    return BlockCode(e.each(e.w(), body))


# ---------------------------------------------------------------------------- discontinuities, logic


@template("discontinuities.dead_zone")
def _dead_zone(e: Emitter) -> BlockCode:
    def body(ix: str) -> list[str]:
        lo, hi, u, y = e.p("start", "0"), e.p("end", "0"), e.u(0, ix), e.y(0, ix)
        return [f"{y} = ({u} > {hi}) ? ({u} - {hi}) : (({u} < {lo}) ? ({u} - {lo}) : 0.0);"]

    return BlockCode(e.each(e.w(), body))


@template("discontinuities.quantizer")
def _quantizer(e: Emitter) -> BlockCode:
    q = e.p("interval", "0")
    return BlockCode(e.each(e.w(), lambda ix: [f"{e.y(0, ix)} = {q} * nearbyint({e.u(0, ix)} / {q});"]))


@template("discontinuities.relay")
def _relay(e: Emitter) -> BlockCode:
    w = e.w()
    s = e.state("state", e.block.initial_discrete_state(), "relay on/off state")
    on, off = e.p("on_point", "0"), e.p("off_point", "0")
    von, voff = e.p("on_value", "0"), e.p("off_value", "0")

    def nxt(ix: str) -> str:
        u = e.u(0, ix)
        return f"(({u} >= {on}) ? 1.0 : (({u} <= {off}) ? 0.0 : {s}[{ix}]))"

    out = e.each(w, lambda ix: [f"{e.y(0, ix)} = ({nxt(ix)} > 0.5) ? {von} : {voff};"])
    upd = e.each(w, lambda ix: [f"{s}[{ix}] = {nxt(ix)};"])
    return BlockCode(out, upd)


@template("discontinuities.rate_limiter")
def _rate_limiter(e: Emitter) -> BlockCode:
    s = e.state("prev", e.block.initial_discrete_state(), "previous output")
    ts = c_float(e.period)
    rise, fall = e.p("rising_rate", "0"), e.p("falling_rate", "0")

    def body(ix: str) -> list[str]:
        u, y, prev = e.u(0, ix), e.y(0, ix), f"{s}[{ix}]"
        return [f"{y} = fmin(fmax({u}, {prev} + {fall} * {ts}), {prev} + {rise} * {ts});"]

    return BlockCode(e.each(e.w(), body), e.each(e.w(), lambda ix: [f"{s}[{ix}] = {e.y(0, ix)};"]))


_REL = {"==": "==", "!=": "!=", "<": "<", "<=": "<=", ">": ">", ">=": ">="}


@template("logic.relational")
def _relational(e: Emitter) -> BlockCode:
    op = _REL[e.block.params["operator"]]
    return BlockCode(e.each(e.w(), lambda ix: [f"{e.y(0, ix)} = ({e.u(0, ix)} {op} {e.u(1, ix)}) ? 1.0 : 0.0;"]))


@template("logic.compare_to_constant")
def _compare_const(e: Emitter) -> BlockCode:
    op = _REL[e.block.params["operator"]]
    c = e.p("constant", "0")
    return BlockCode(e.each(e.w(), lambda ix: [f"{e.y(0, ix)} = ({e.u(0, ix)} {op} {c}) ? 1.0 : 0.0;"]))


@template("logic.logical")
def _logical(e: Emitter) -> BlockCode:
    op = e.block.params["operator"]

    def body(ix: str) -> list[str]:
        terms = [f"({e.u(k, ix)} != 0.0)" for k in range(e.block.num_inputs())]
        if op == "NOT":
            expr = f"!{terms[0]}"
        elif op in ("AND", "NAND"):
            expr = " && ".join(terms)
        elif op in ("OR", "NOR"):
            expr = " || ".join(terms)
        else:  # XOR: odd number of true inputs
            expr = "((" + " + ".join(f"(int){t}" for t in terms) + ") % 2 == 1)"
        if op in ("NAND", "NOR"):
            expr = f"!({expr})"
        return [f"{e.y(0, ix)} = ({expr}) ? 1.0 : 0.0;"]

    return BlockCode(e.each(e.w(), body))


# ---------------------------------------------------------------------------- routing


@template("routing.mux")
def _mux(e: Emitter) -> BlockCode:
    lines, offset = [], 0
    for k, w in enumerate(e.in_widths):
        u = e.u_var(k)
        lines.append(f"for (i = 0; i < {w}; i++) {{ {e.y(0, f'{offset} + i')} = {u}[i]; }}")
        offset += w
    return BlockCode(lines)


@template("routing.demux")
def _demux(e: Emitter) -> BlockCode:
    lines, offset = [], 0
    u = e.u_var(0)
    for p, w in enumerate(e.out_widths):
        lines.append(f"for (i = 0; i < {w}; i++) {{ {e.y(p, 'i')} = {u}[{offset} + i]; }}")
        offset += w
    return BlockCode(lines)


@template("routing.switch")
def _switch(e: Emitter) -> BlockCode:
    crit = e.block.params["criterion"]
    thr = e.p("threshold", "0")
    c = e.u(1, "0")
    cond = (
        f"{c} >= {thr}" if crit == "u1 >= threshold" else f"{c} > {thr}" if crit == "u1 > threshold" else f"{c} != 0.0"
    )
    return BlockCode(e.each(e.w(), lambda ix: [f"{e.y(0, ix)} = ({cond}) ? {e.u(0, ix)} : {e.u(2, ix)};"]))


# ---------------------------------------------------------------------------- discrete


@template("discrete.zero_order_hold")
def _zoh(e: Emitter) -> BlockCode:
    return BlockCode(e.each(e.w(), lambda ix: [f"{e.y(0, ix)} = {e.u(0, ix)};"]))


@template("discrete.unit_delay")
def _unit_delay(e: Emitter) -> BlockCode:
    s = e.state("x", e.block.initial_discrete_state(), "previous input")
    out = e.each(e.w(), lambda ix: [f"{e.y(0, ix)} = {s}[{ix}];"])
    upd = e.each(e.w(), lambda ix: [f"{s}[{ix}] = {e.u(0, ix)};"])
    return BlockCode(out, upd)


@template("discrete.integer_delay")
def _integer_delay(e: Emitter) -> BlockCode:
    w, n = e.w(), int(e.block.params["delay"])
    s = e.state("buf", e.block.initial_discrete_state(), f"last {n} inputs, oldest first")
    out = e.each(w, lambda ix: [f"{e.y(0, ix)} = {s}[{ix}];"])
    upd = [f"for (i = 0; i < {(n - 1) * w}u; i++) {{ {s}[i] = {s}[i + {w}u]; }}"] if n > 1 else []
    upd += e.each(w, lambda ix: [f"{s}[{(n - 1) * w} + {ix}] = {e.u(0, ix)};"])
    return BlockCode(out, upd)


@template("discrete.integrator")
def _discrete_integrator(e: Emitter) -> BlockCode:
    b = e.block
    w = e.w()
    reset = b.params.get("external_reset", "none")
    s = e.state(
        "x", b.initial_discrete_state(), "accumulator" + (f", [{w}] previous reset input" if reset != "none" else "")
    )
    k, lo, hi = e.p("gain", "0"), e.p("lower", "0"), e.p("upper", "0")
    ts = c_float(e.period)

    def step(ix: str) -> str:
        return f"fmin(fmax({s}[{ix}] + {k} * {ts} * {e.u(0, ix)}, {lo}), {hi})"

    pre: list[str] = []
    post: list[str] = []
    if reset != "none":
        # The reset is decided when the outputs are computed: the state goes back to its initial value first, so
        # the output and the update of this step both use it (as in the simulation).
        r, prev = e.u(1, "0"), f"{s}[{w}]"
        rising, falling = f"(({prev} <= 0.0) && ({r} > 0.0))", f"(({prev} > 0.0) && ({r} <= 0.0))"
        cond = {"rising": rising, "falling": falling, "either": f"({rising} || {falling})", "level": f"({r} != 0.0)"}
        x0 = b._x0()  # type: ignore[attr-defined]
        pre = [f"if {cond[reset]} {{ /* external reset ({reset}) */"]
        pre += [f"    {s}[{ix}] = {c_float(float(x0[ix]))};" for ix in range(w)]
        pre += ["}", f"{prev} = {r};"]
    if b.params["method"] == "backward_euler":
        out = pre + e.each(w, lambda ix: [f"{e.y(0, ix)} = {step(ix)};"])
        upd = e.each(w, lambda ix: [f"{s}[{ix}] = {e.y(0, ix)};"])
    else:
        out = pre + e.each(w, lambda ix: [f"{e.y(0, ix)} = {s}[{ix}];"])
        upd = e.each(w, lambda ix: [f"{s}[{ix}] = {step(ix)};"])
    return BlockCode(out, upd + post)


@template("discrete.transfer_function")
def _discrete_tf(e: Emitter) -> BlockCode:
    a, b, c, d = e.block.matrices()  # type: ignore[attr-defined]
    n = a.shape[0]
    if n == 0:
        dp = e.param("D", d.ravel())
        return BlockCode([f"{e.y(0, '0')} = {dp}[0] * {e.u(0, '0')};"])
    s = e.state("x", e.block.initial_discrete_state(), "state vector")
    ap, bp, cp, dp = (e.param(nm, m.ravel()) for nm, m in (("A", a), ("B", b), ("C", c), ("D", d)))
    u = e.u(0, "0")
    out = [f"{e.y(0, '0')} = {dp}[0] * {u};", f"for (i = 0; i < {n}; i++) {{ {e.y(0, '0')} += {cp}[i] * {s}[i]; }}"]
    upd = [
        "{",
        f"    real_T x_new[{n}];",
        "    uint32_T j;",
        f"    for (i = 0; i < {n}; i++) {{",
        f"        x_new[i] = {bp}[i] * {u};",
        f"        for (j = 0; j < {n}u; j++) {{ x_new[i] += {ap}[i * {n}u + j] * {s}[j]; }}",
        "    }",
        f"    for (i = 0; i < {n}; i++) {{ {s}[i] = x_new[i]; }}",
        "}",
    ]
    return BlockCode(out, upd)


@template("discrete.counter")
def _counter(e: Emitter) -> BlockCode:
    s = e.state("count", e.block.initial_discrete_state(), "count")
    lim = e.p("limit", "0")
    wrap = e.block.params["at_limit"] == "wrap"

    def upd(ix: str) -> list[str]:
        nxt = f"{s}[{ix}] + (({e.u(0, ix)} != 0.0) ? 1.0 : 0.0)"
        if wrap:
            return [f"{s}[{ix}] = ({nxt} > {lim}) ? 0.0 : ({nxt});"]
        return [f"{s}[{ix}] = fmin({nxt}, {lim});"]

    return BlockCode(e.each(e.w(), lambda ix: [f"{e.y(0, ix)} = {s}[{ix}];"]), e.each(e.w(), upd))


@template("discrete.edge_detect")
def _edge_detect(e: Emitter) -> BlockCode:
    s = e.state("prev", e.block.initial_discrete_state(), "previous input (boolean)")
    d = e.block.params["direction"]

    def out(ix: str) -> list[str]:
        now, before = f"({e.u(0, ix)} != 0.0)", f"({s}[{ix}] != 0.0)"
        cond = (
            f"{now} && !{before}"
            if d == "rising"
            else f"!{now} && {before}"
            if d == "falling"
            else f"{now} != {before}"
        )
        return [f"{e.y(0, ix)} = ({cond}) ? 1.0 : 0.0;"]

    upd = e.each(e.w(), lambda ix: [f"{s}[{ix}] = ({e.u(0, ix)} != 0.0) ? 1.0 : 0.0;"])
    return BlockCode(e.each(e.w(), out), upd)


@template("discrete.debounce")
def _debounce(e: Emitter) -> BlockCode:
    s = e.state("dw", [0.0, 0.0], "[0] output state, [1] samples disagreeing with it")
    on_n, off_n = int(e.block.params["on_samples"]), int(e.block.params["off_samples"])
    u = e.u(0, "0")
    common = [
        f"real_T now = ({u} != 0.0) ? 1.0 : 0.0;",
        f"real_T st = {s}[0];",
        f"real_T cnt = {s}[1];",
        "if (now == st) { cnt = 0.0; }",
        f"else {{ cnt += 1.0; if (cnt >= ((now != 0.0) ? {on_n}.0 : {off_n}.0)) {{ st = now; cnt = 0.0; }} }}",
    ]
    out = ["{", *[f"    {x}" for x in common], f"    {e.y(0, '0')} = st;", "}"]
    upd = ["{", *[f"    {x}" for x in common], f"    {s}[0] = st;", f"    {s}[1] = cnt;", "}"]
    return BlockCode(out, upd)


@template("discrete.filter")
def _pt1(e: Emitter) -> BlockCode:
    s = e.state("y", e.block.initial_discrete_state(), "previous output")
    ts = c_float(e.period)
    tau = e.p("time_constant", "0")

    def out(ix: str) -> list[str]:
        return [f"{e.y(0, ix)} = {s}[{ix}] + ({ts} / ({tau} + {ts})) * ({e.u(0, ix)} - {s}[{ix}]);"]

    return BlockCode(e.each(e.w(), out), e.each(e.w(), lambda ix: [f"{s}[{ix}] = {e.y(0, ix)};"]))


@template("discrete.moving_average")
def _moving_average(e: Emitter) -> BlockCode:
    w, n = e.w(), int(e.block.params["length"])
    if n == 1:
        return BlockCode(e.each(w, lambda ix: [f"{e.y(0, ix)} = {e.u(0, ix)};"]))
    s = e.state("buf", e.block.initial_discrete_state(), f"last {n - 1} inputs")

    def out(ix: str) -> list[str]:
        return [
            f"{e.y(0, ix)} = {e.u(0, ix)};",
            "{",
            "    uint32_T k;",
            f"    for (k = 0; k < {n - 1}u; k++) {{ {e.y(0, ix)} += {s}[k * {w}u + {ix}]; }}",
            "}",
            f"{e.y(0, ix)} /= {n}.0;",
        ]

    upd = [f"for (i = 0; i < {(n - 2) * w}u; i++) {{ {s}[i] = {s}[i + {w}u]; }}"] if n > 2 else []
    upd += e.each(w, lambda ix: [f"{s}[{(n - 2) * w} + {ix}] = {e.u(0, ix)};"])
    return BlockCode(e.each(w, out), upd)


@template("control.discrete_pid")
def _discrete_pid(e: Emitter) -> BlockCode:
    if e.w() != 1:
        raise CodegenError(f"{e.path}: generated code supports scalar PID controllers only", (e.path,))
    s = e.state("x", e.block.initial_discrete_state(), "[0] integral, [1] derivative filter")
    kp, ki, kd, kn = (e.p(n, "0") for n in ("P", "I", "D", "N"))
    lo, hi, kb = e.p("lower", "0"), e.p("upper", "0"), e.p("Kb", "0")
    ts = c_float(e.period)
    aw = e.block.params["anti_windup"]
    u = e.u(0, "0")
    law = [
        f"real_T err = {u};",
        f"real_T d_term = {kd} * {kn} * (err - {s}[1]);",
        f"real_T unsat = {kp} * err + {s}[0] + d_term;",
        f"real_T y = fmin(fmax(unsat, {lo}), {hi});",
    ]
    di = [f"real_T di = {ki} * err;"]
    if aw == "none":
        di.append("(void)y; /* no anti-windup */")
    elif aw == "clamping":
        di.append("if ((unsat != y) && (((unsat - y) > 0.0) == (di > 0.0)) && (di != 0.0)) { di = 0.0; }")
    elif aw == "back_calculation":
        di.append(f"di += {kb} * (y - unsat);")
    out = ["{", *[f"    {x}" for x in law], f"    {e.y(0, '0')} = y;", "}"]
    upd = [
        "{",
        *[f"    {x}" for x in law + di],
        f"    {s}[0] += {ts} * di;",
        f"    {s}[1] += {ts} * {kn} * (err - {s}[1]);",
        "}",
    ]
    return BlockCode(out, upd)


# ---------------------------------------------------------------------------- lookup tables


def _locate_c(x: str, bp: str, n: int, interp: str, extrap: str, i_var: str, f_var: str) -> list[str]:
    """C statements computing interval index ``i_var`` and fraction ``f_var``, matching lookup.locate()."""
    lines = [f"{i_var} = 0u;"]
    if n > 2:  # with two breakpoints there is only one interval
        lines.append(f"while (({i_var} < {n - 2}u) && ({x} >= {bp}[{i_var} + 1u])) {{ {i_var}++; }}")
    lines += [
        f"{f_var} = ({x} - {bp}[{i_var}]) / ({bp}[{i_var} + 1u] - {bp}[{i_var}]);",
    ]
    if extrap == "clip":
        lines.append(f"{f_var} = fmin(fmax({f_var}, 0.0), 1.0);")
    if interp == "nearest":
        lines.append(f"{f_var} = (fmin(fmax({f_var}, 0.0), 1.0) >= 0.5) ? 1.0 : 0.0;")
    elif interp == "flat":
        lines.append(f"{f_var} = ({x} >= {bp}[{n - 1}]) ? 1.0 : ((({f_var}) >= 1.0) ? 1.0 : 0.0);")
    return lines


@template("lookup.table_1d")
def _lookup1d(e: Emitter) -> BlockCode:
    bp_arr, tab_arr = e.block._data()  # type: ignore[attr-defined]
    n = bp_arr.size
    bp, tab = e.param("breakpoints", bp_arr), e.param("table", tab_arr)
    interp, extrap = e.block.params["interpolation"], e.block.params["extrapolation"]

    def body(ix: str) -> list[str]:
        return [
            "{",
            "    uint32_T k;",
            "    real_T f;",
            *[f"    {x}" for x in _locate_c(e.u(0, ix), bp, n, interp, extrap, "k", "f")],
            f"    {e.y(0, ix)} = {tab}[k] + f * ({tab}[k + 1u] - {tab}[k]);",
            "}",
        ]

    return BlockCode(e.each(e.w(), body))


@template("lookup.prelookup")
def _prelookup(e: Emitter) -> BlockCode:
    bp_arr = e.block._bp()  # type: ignore[attr-defined]
    bp = e.param("breakpoints", bp_arr)

    def body(ix: str) -> list[str]:
        return [
            "{",
            "    uint32_T k;",
            "    real_T f;",
            *[
                f"    {x}"
                for x in _locate_c(e.u(0, ix), bp, bp_arr.size, "linear", e.block.params["extrapolation"], "k", "f")
            ],
            f"    {e.y(0, ix)} = (real_T)k;",
            f"    {e.y(1, ix)} = f;",
            "}",
        ]

    return BlockCode(e.each(e.w(), body))


@template("lookup.interpolation")
def _interpolation(e: Emitter) -> BlockCode:
    tab_arr = e.block._table()  # type: ignore[attr-defined]
    tab = e.param("table", tab_arr.ravel())  # row-major

    def index(port: int, ix: str, n: int) -> str:
        # The index comes from a Prelookup (an integer stored as real_T); clamp it like the simulation does.
        return f"(uint32_T)fmin(fmax({e.u(port, ix)}, 0.0), {float(n - 2)})"

    if tab_arr.ndim == 1:
        n = tab_arr.size

        def body1(ix: str) -> list[str]:
            return [
                "{",
                f"    uint32_T k = {index(0, ix, n)};",
                f"    real_T f = {e.u(1, ix)};",
                f"    {e.y(0, ix)} = {tab}[k] + f * ({tab}[k + 1u] - {tab}[k]);",
                "}",
            ]

        return BlockCode(e.each(e.w(), body1))
    nr, nc = tab_arr.shape

    def t(i: str, j: str) -> str:
        return f"{tab}[({i}) * {nc}u + ({j})]"

    def body2(ix: str) -> list[str]:
        return [
            "{",
            f"    uint32_T r = {index(0, ix, nr)};",
            f"    real_T fr = {e.u(1, ix)};",
            f"    uint32_T c = {index(2, ix, nc)};",
            f"    real_T fc = {e.u(3, ix)};",
            f"    {e.y(0, ix)} = (1.0 - fr) * (1.0 - fc) * {t('r', 'c')} + (1.0 - fr) * fc * {t('r', 'c + 1u')}",
            f"        + fr * (1.0 - fc) * {t('r + 1u', 'c')} + fr * fc * {t('r + 1u', 'c + 1u')};",
            "}",
        ]

    return BlockCode(e.each(e.w(), body2))


@template("lookup.table_2d")
def _lookup2d(e: Emitter) -> BlockCode:
    r_arr, c_arr, t_arr = e.block._data()  # type: ignore[attr-defined]
    nr, nc = r_arr.size, c_arr.size
    rb, cb = e.param("row_breakpoints", r_arr), e.param("column_breakpoints", c_arr)
    tab = e.param("table", t_arr.ravel())  # row-major
    interp, extrap = e.block.params["interpolation"], e.block.params["extrapolation"]

    def t(i: str, j: str) -> str:
        return f"{tab}[({i}) * {nc}u + ({j})]"

    def body(ix: str) -> list[str]:
        return [
            "{",
            "    uint32_T r, c;",
            "    real_T fr, fc;",
            *[f"    {x}" for x in _locate_c(e.u(0, ix), rb, nr, interp, extrap, "r", "fr")],
            *[f"    {x}" for x in _locate_c(e.u(1, ix), cb, nc, interp, extrap, "c", "fc")],
            f"    {e.y(0, ix)} = (1.0 - fr) * (1.0 - fc) * {t('r', 'c')} + (1.0 - fr) * fc * {t('r', 'c + 1u')}",
            f"        + fr * (1.0 - fc) * {t('r + 1u', 'c')} + fr * fc * {t('r + 1u', 'c + 1u')};",
            "}",
        ]

    return BlockCode(e.each(e.w(), body))


# ---------------------------------------------------------------------------- state charts

_C_CALLS = {
    "abs": "fabs",
    "min": "fmin",
    "max": "fmax",
    "sqrt": "sqrt",
    "exp": "exp",
    "log": "log",
    "sin": "sin",
    "cos": "cos",
    "floor": "floor",
    "ceil": "ceil",
}
_C_BINOPS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}
_C_CMPS = {ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}


class _ChartC:
    """Translates the (whitelisted) chart AST into C expressions and statements."""

    def __init__(self, names: dict[str, str], ticks: str, period: str) -> None:
        self.names, self.ticks, self.period = names, ticks, period

    def expr(self, n: ast.AST) -> str:
        if isinstance(n, ast.Constant):
            if not isinstance(n.value, int | float):
                raise CodegenError(f"chart constant {n.value!r} is not a number")
            return c_float(float(n.value))
        if isinstance(n, ast.Name):
            if n.id == "t_in_state":
                return f"(({self.ticks} + 1.0) * {self.period})"
            consts = {
                "pi": "3.141592653589793",
                "e": "2.718281828459045",
                "true": "1.0",
                "True": "1.0",
                "false": "0.0",
                "False": "0.0",
            }
            return self.names.get(n.id, consts.get(n.id, n.id))
        if isinstance(n, ast.BinOp):
            a, b = self.expr(n.left), self.expr(n.right)
            if isinstance(n.op, ast.Pow):
                return f"pow({a}, {b})"
            if isinstance(n.op, ast.Mod):
                return f"fmod({a}, {b})"
            return f"({a} {_C_BINOPS[type(n.op)]} {b})"
        if isinstance(n, ast.UnaryOp):
            v = self.expr(n.operand)
            return f"(!{v})" if isinstance(n.op, ast.Not) else f"(-{v})" if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.BoolOp):
            op = " && " if isinstance(n.op, ast.And) else " || "
            return (
                "(" + op.join(f"({self.expr(v)} != 0.0)" if not _is_bool(v) else self.expr(v) for v in n.values) + ")"
            )
        if isinstance(n, ast.Compare):
            parts, left = [], n.left
            for cmp_op, right in zip(n.ops, n.comparators, strict=True):
                parts.append(f"({self.expr(left)} {_C_CMPS[type(cmp_op)]} {self.expr(right)})")
                left = right
            return "(" + " && ".join(parts) + ")"
        if isinstance(n, ast.IfExp):
            return f"(({self.expr(n.test)}) ? {self.expr(n.body)} : {self.expr(n.orelse)})"
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            if n.func.id == "after":
                return f"(({self.ticks} + 1.0) >= {self.expr(n.args[0])})"
            fn = _C_CALLS[n.func.id]
            args = [self.expr(a) for a in n.args]
            if fn in ("fmin", "fmax") and len(args) > 2:
                out = args[0]
                for a in args[1:]:
                    out = f"{fn}({out}, {a})"
                return out
            return f"{fn}({', '.join(args)})"
        raise CodegenError(f"chart construct not supported in C: {ast.dump(n)}")

    def stmts(self, body: list[ast.stmt]) -> list[str]:
        lines = []
        for st in body:
            if isinstance(st, ast.Assign):
                target = st.targets[0]
                assert isinstance(target, ast.Name)
                lines.append(f"{self.names[target.id]} = {self.cond_value(st.value)};")
            elif isinstance(st, ast.AugAssign):
                assert isinstance(st.target, ast.Name)
                var = self.names[st.target.id]
                rhs = ast.BinOp(left=ast.Name(st.target.id, ast.Load()), op=st.op, right=st.value)
                lines.append(f"{var} = {self.expr(rhs)};")
        return lines

    def cond_value(self, n: ast.AST) -> str:
        """A boolean expression used as a value becomes 1.0/0.0."""
        return f"(({self.expr(n)}) ? 1.0 : 0.0)" if _is_bool(n) else self.expr(n)


def _is_bool(n: ast.AST) -> bool:
    return isinstance(n, ast.Compare | ast.BoolOp) or (isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not))


@template("charts.state_chart")
def _state_chart(e: Emitter) -> BlockCode:
    blk = e.block
    spec = blk.spec  # type: ignore[attr-defined]
    s = e.state("chart", blk.initial_discrete_state(), "[0] active state, [1] samples in state, then variables")
    names = {n: e.u(k, "0") for k, n in enumerate(spec.inputs)}
    for k, n in enumerate(spec.variables):
        names[n] = f"{s}[{2 + k}]"
    cg = _ChartC(names, "ticks", c_float(e.period))
    lines = [
        "{",
        f"    int st = (int){s}[0];",
        f"    real_T ticks = {s}[1];",
        "    int fired = 0;",
        "    switch (st) {",
    ]
    by_source: dict[int, list[int]] = {}
    for k, tr in enumerate(spec.transitions):
        by_source.setdefault(tr.source, []).append(k)
    for si, state in enumerate(spec.states):
        lines.append(f"    case {si}: /* {state.name} */")
        for n, k in enumerate(by_source.get(si, [])):
            tr = spec.transitions[k]
            target = spec.states[tr.target]
            body = cg.stmts(state.exit) + cg.stmts(tr.action) + cg.stmts(target.entry)
            kw = "if" if n == 0 else "else if"
            lines.append(f"        {kw} ({cg.expr(tr.guard)}) {{ /* -> {target.name} */")
            lines += [f"            {x}" for x in body]
            lines.append(f"            st = {tr.target}; ticks = 0.0; fired = 1;")
            lines.append("        }")
        lines.append("        break;")
    lines += ["    default: break;", "    }", "    if (!fired) {", "        switch (st) {"]
    for si, state in enumerate(spec.states):
        during = cg.stmts(state.during)
        if during:
            lines.append(f"        case {si}:")
            lines += [f"            {x}" for x in during]
            lines.append("            break;")
    lines += [
        "        default: break;",
        "        }",
        "        ticks += 1.0;",
        "    }",
        f"    {s}[0] = (real_T)st;",
        f"    {s}[1] = ticks;",
    ]
    for k, (name, _init) in enumerate(spec.outputs):
        lines.append(f"    {e.y(k, '0')} = {names[name]};")
    if blk.params["state_output"]:
        lines.append(f"    {e.y(len(spec.outputs), '0')} = (real_T)st;")
    lines.append("}")
    return BlockCode(lines)


# ---------------------------------------------------------------------------- CAN


def _can_words(u: str, need_le: bool, need_be: bool) -> list[str]:
    """Assemble the frame into 64-bit words: ``le`` (Intel byte order) and/or ``be`` (Motorola)."""
    decl = ", ".join(n for n, need in (("le = 0u", need_le), ("be = 0u", need_be)) if need)
    body = []
    if need_le:
        body.append("    le |= b << (8 * k);")
    if need_be:
        body.append("    be |= b << (56 - 8 * k);")
    return [
        f"uint64_T {decl};",
        "int k;",
        "for (k = 0; k < 8; k++) {",
        f"    uint64_T b = (uint64_T)((uint8_T){u}[k]);",
        *body,
        "}",
    ]


def _mask(length: int) -> str:
    return "0xFFFFFFFFFFFFFFFFu" if length >= 64 else f"0x{(1 << length) - 1:X}u"


@template("can.unpack")
def _can_unpack(e: Emitter) -> BlockCode:
    sigs = e.block._signals  # type: ignore[attr-defined]
    need_le, need_be = any(x.little_endian for x in sigs), any(not x.little_endian for x in sigs)
    lines = ["{", *[f"    {x}" for x in _can_words(e.u_var(0), need_le, need_be)]]
    for p, s in enumerate(sigs):
        word = "le" if s.little_endian else "be"
        lines.append(f"    {{ /* {s.name} */")
        lines.append(f"        uint64_T raw = ({word} >> {s.shift}) & {_mask(s.length)};")
        if s.signed:
            lines.append(
                f"        real_T v = (raw & ((uint64_T)1u << {s.length - 1})) ? "
                f"(real_T)((int64_T)raw - ((int64_T)1 << {s.length})) : (real_T)raw;"
            )
        else:
            lines.append("        real_T v = (real_T)raw;")
        lines.append(f"        {e.y(p, '0')} = v * {c_float(s.factor)} + {c_float(s.offset)};")
        lines.append("    }")
    lines.append("}")
    return BlockCode(lines)


@template("can.pack")
def _can_pack(e: Emitter) -> BlockCode:
    sigs = e.block._signals  # type: ignore[attr-defined]
    lines = ["{", "    uint64_T le = 0u, be = 0u;", "    int k;"]
    for p, s in enumerate(sigs):
        lo, hi = (-(1 << (s.length - 1)), (1 << (s.length - 1)) - 1) if s.signed else (0, (1 << s.length) - 1)
        word = "le" if s.little_endian else "be"
        lines += [
            f"    {{ /* {s.name} */",
            f"        real_T r = round(({e.u(p, '0')} - {c_float(s.offset)}) / {c_float(s.factor)});",
            f"        if (r > {c_float(float(hi))}) {{ r = {c_float(float(hi))}; }} else if (r < {c_float(float(lo))}) {{ r = {c_float(float(lo))}; }}",
            f"        {word} |= (((uint64_T)(int64_T)r) & {_mask(s.length)}) << {s.shift};",
            "    }",
        ]
    lines += [
        "    for (k = 0; k < 8; k++) {",
        f"        {e.y(0, 'k')} = (real_T)((le >> (8 * k)) & 0xFFu) + (real_T)((be >> (56 - 8 * k)) & 0xFFu);",
        "    }",
        "}",
    ]
    return BlockCode(lines)


__all__ = ["as_signal"]
