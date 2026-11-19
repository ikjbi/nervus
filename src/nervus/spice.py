"""Read and write SPICE netlists (``.cir``, ``.net``, ``.sp``), e.g. circuits exported from LTspice.

LTspice: *View → SPICE Netlist*, then save the text as ``circuit.cir``. Nervus reads the common subset:

=================  ==================================================================
``R C L``          resistor, capacitor, inductor (``IC=`` initial value)
``V I``            sources: ``DC 5`` / ``5``, ``SIN(VO VA FREQ)``, ``PULSE(V1 V2 TD TR TF PW PER)``
``D``              diode with ``.model name D(IS= N= BV= IBV=)``
``Q``              bipolar transistor, ``.model name NPN(IS= BF= BR=)`` or ``PNP``
``M``              MOSFET (``d g s b``), ``.model name NMOS(VTO= KP= LAMBDA=)`` or ``PMOS``, ``W= L=``
``E G``            voltage-controlled voltage / current source
``.tran``          ``.tran TSTEP TSTOP``: the stop time and the step
``.param``         ``.param name=value``: workspace variables (``{name}`` in values)
=================  ==================================================================

Node ``0`` (or ``gnd``) is ground. Every other node gets a Voltage Sensor named ``V(node)``, so the
result has the node voltages under SPICE's names: ``res["V(out)"]``. Values take SI suffixes: f p n u m k
meg g t (``4.7k``, ``10u``, ``1meg``). Rise and fall times of ``PULSE`` are ignored (ideal edges).

    from nervus.spice import read_netlist, write_netlist
    d = read_netlist("rectifier.cir")
    res = simulate(d)
    write_netlist(d, "out.cir")
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from nervus.core.block import Block
from nervus.core.diagram import Diagram
from nervus.core.errors import ModelError
from nervus.core.workspace import Variable

SUFFIXES = {
    "t": 1e12,
    "g": 1e9,
    "meg": 1e6,
    "k": 1e3,
    "m": 1e-3,
    "u": 1e-6,
    "µ": 1e-6,
    "n": 1e-9,
    "p": 1e-12,
    "f": 1e-15,
}
_NUMBER = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)(meg|[tgkmuµnpf])?[a-zA-Z]*$", re.IGNORECASE)


def parse_number(text: str, params: dict[str, float] | None = None) -> float:
    """A SPICE number: ``4.7k`` -> 4700, ``10uF`` -> 1e-5, ``1meg`` -> 1e6; ``{R1}`` -> a ``.param``."""
    t = text.strip()
    if t.startswith("{") and t.endswith("}"):
        name = t[1:-1].strip().lower()  # SPICE names are not case-sensitive
        if params is None or name not in params:
            raise ModelError(f"unknown .param {t[1:-1].strip()!r}")
        return params[name]
    m = _NUMBER.match(t)
    if m is None:
        raise ModelError(f"not a number: {text!r}")
    value = float(m.group(1))
    suffix = (m.group(2) or "").lower()
    return value * SUFFIXES.get(suffix, 1.0)


def format_number(v: float) -> str:
    """The shortest SPICE spelling of ``v`` (``4.7k``, ``10u``)."""
    if v == 0 or not math.isfinite(v):
        return f"{v:g}"
    for suffix, scale in (("meg", 1e6), ("k", 1e3), ("", 1.0), ("m", 1e-3), ("u", 1e-6), ("n", 1e-9), ("p", 1e-12)):
        if abs(v) >= scale * 0.9999:
            return f"{v / scale:.6g}{suffix}"
    return f"{v:g}"


def _lines(text: str) -> list[str]:
    out: list[str] = []
    for raw in text.splitlines()[1:]:  # the first line is the title
        line = raw.split(";")[0].rstrip()
        if not line.strip() or line.lstrip().startswith("*"):
            continue
        if line.lstrip().startswith("+") and out:
            out[-1] += " " + line.lstrip()[1:]
        else:
            out.append(line.strip())
    return out


def _kv(tokens: list[str]) -> dict[str, str]:
    """``W=10u L=1u`` -> {"w": "10u", "l": "1u"}."""
    joined = " ".join(tokens).replace(" =", "=").replace("= ", "=")
    return {k.lower(): v for k, v in re.findall(r"(\w+)=([^\s()]+)", joined)}


def _models(lines: list[str]) -> dict[str, tuple[str, dict[str, str]]]:
    models = {}
    for line in lines:
        if line.lower().startswith(".model"):
            m = re.match(r"\.model\s+(\S+)\s+(\w+)\s*\(?(.*?)\)?\s*$", line, re.IGNORECASE)
            if m:
                models[m.group(1).lower()] = (m.group(2).upper(), _kv([m.group(3)]))
    return models


def read_netlist(source: str | Path, name: str | None = None) -> Diagram:
    """Build a Nervus model from a SPICE netlist (a file path, or the netlist text itself)."""
    from nervus.blocks import (
        BJT,
        MOSFET,
        VCCS,
        VCVS,
        Bias,
        Capacitor,
        CurrentSource,
        ElectricalReference,
        Inductor,
        Pulse,
        Resistor,
        SemiconductorDiode,
        Sine,
        VoltageSensor,
        VoltageSource,
    )

    path = Path(source) if isinstance(source, Path) or "\n" not in str(source) else None
    text = path.read_text(encoding="utf-8", errors="replace") if path is not None else str(source)
    d = Diagram(name or (path.stem if path is not None else "netlist"))
    lines = _lines(text)
    params: dict[str, float] = {}
    for line in lines:
        if line.lower().startswith(".param"):
            for k, v in re.findall(r"(\w+)\s*=\s*(\S+)", line[6:]):
                params[k.lower()] = parse_number(v, params)
                d.workspace.add(Variable(k, params[k.lower()], "from .param"))
    models = _models(lines)
    nets: dict[str, tuple[Block, str]] = {}
    gnd = d.add(ElectricalReference(), name="gnd")

    def num(t: str) -> float:
        return parse_number(t, params)

    def join(net: str, block: Block, port: str) -> None:
        key = "0" if net.lower() in ("0", "gnd") else net
        if key == "0":
            d.link((gnd, "p"), (block, port))
        elif key in nets:
            d.link(nets[key], (block, port))
        else:
            nets[key] = (block, port)

    def add_source(kind: str, elem: str, tokens: list[str], p: str, n: str) -> None:
        spec = " ".join(tokens)
        sine = re.search(r"sin\s*\(([^)]*)\)", spec, re.IGNORECASE)
        pulse = re.search(r"pulse\s*\(([^)]*)\)", spec, re.IGNORECASE)
        cls = VoltageSource if kind == "V" else CurrentSource
        if sine or pulse:
            blk = d.add(cls(controlled=True), name=elem)
            if sine:
                a = [num(x) for x in sine.group(1).replace(",", " ").split()]
                vo, va, freq = [*a, 0.0, 0.0, 0.0][:3]
                sig: Block = d.add(Sine(amplitude=va, frequency=2 * math.pi * freq, bias=vo), name=f"{elem}_sin")
            else:
                a = [num(x) for x in pulse.group(1).replace(",", " ").split()]  # type: ignore[union-attr]
                v1, v2, td, _tr, _tf, pw, per = [*a, *([0.0] * 7)][:7]
                per = per or 1e9
                sig = d.add(Pulse(amplitude=v2 - v1, period=per, duty=min(100.0, 100.0 * pw / per), delay=td),
                            name=f"{elem}_pulse")  # fmt: skip
                if v1:
                    bias = d.add(Bias(bias=v1), name=f"{elem}_v1")
                    d.connect(sig, bias)
                    sig = bias
            d.connect(sig, blk)
        else:
            values = [t for t in tokens if t.lower() not in ("dc",) and not t.lower().startswith("ac")]
            value = num(values[0]) if values else 0.0
            amount: dict[str, Any] = {"V": value} if kind == "V" else {"I": value}
            blk = d.add(cls(**amount), name=elem)
        join(p, blk, "p")
        join(n, blk, "n")

    skipped: list[str] = []
    for line in lines:
        tokens = line.split()
        elem, kind = tokens[0], tokens[0][0].upper()
        if kind == ".":
            directive = elem.lower()
            if directive == ".tran" and len(tokens) >= 3:
                d.settings.step = num(tokens[1])
                d.settings.t_final = num(tokens[2])
                d.settings.solver = "auto"
                d.settings.max_step = num(tokens[1])
            continue
        if kind in "RCL":
            kv = _kv(tokens[4:])
            value = num(tokens[3])
            if kind == "R":
                blk: Block = d.add(Resistor(R=value), name=elem)
            elif kind == "C":
                blk = d.add(Capacitor(C=value, v0=num(kv["ic"]) if "ic" in kv else 0.0), name=elem)
            else:
                blk = d.add(Inductor(L=value, i0=num(kv["ic"]) if "ic" in kv else 0.0), name=elem)
            join(tokens[1], blk, "p")
            join(tokens[2], blk, "n")
        elif kind in "VI":
            add_source(kind, elem, tokens[3:], tokens[1], tokens[2])
        elif kind == "D":
            mtype, mp = models.get(tokens[3].lower(), ("D", {})) if len(tokens) > 3 else ("D", {})
            keys = {"is": "Is", "n": "N", "bv": "BV", "ibv": "IBV"}
            args: dict[str, Any] = {keys[k]: num(v) for k, v in mp.items() if k in keys}
            blk = d.add(SemiconductorDiode(**args), name=elem)
            join(tokens[1], blk, "p")
            join(tokens[2], blk, "n")
        elif kind == "Q":
            mtype, mp = models.get(tokens[4].lower(), ("NPN", {})) if len(tokens) > 4 else ("NPN", {})
            args2: dict[str, Any] = {"type": "PNP" if mtype == "PNP" else "NPN"}
            for k, key in (("is", "Is"), ("bf", "BF"), ("br", "BR")):
                if k in mp:
                    args2[key] = num(mp[k])
            blk = d.add(BJT(**args2), name=elem)
            for port, net in zip(("c", "b", "e"), tokens[1:4], strict=True):
                join(net, blk, port)
        elif kind == "M":
            mtype, mp = models.get(tokens[5].lower(), ("NMOS", {})) if len(tokens) > 5 else ("NMOS", {})
            kv = _kv(tokens[6:])
            ratio = (num(kv["w"]) / num(kv["l"])) if "w" in kv and "l" in kv else 1.0
            args3: dict[str, Any] = {"type": "P" if mtype == "PMOS" else "N"}
            if "vto" in mp:
                args3["Vth"] = abs(num(mp["vto"]))
            if "kp" in mp:
                args3["K"] = num(mp["kp"]) * ratio
            if "lambda" in mp:
                args3["lam"] = num(mp["lambda"])
            blk = d.add(MOSFET(**args3), name=elem)
            for port, net in zip(("d", "g", "s"), tokens[1:4], strict=True):  # the bulk (tokens[4]) is ignored
                join(net, blk, port)
        elif kind in "EG":
            value = num(tokens[5])
            blk = d.add(VCVS(gain=value) if kind == "E" else VCCS(gm=value), name=elem)
            for port, net in zip(("p", "n", "cp", "cn"), tokens[1:5], strict=True):
                join(net, blk, port)
        else:
            skipped.append(elem)
    if skipped:
        d.meta["spice_skipped"] = skipped
    for net in nets:
        sensor = d.add(VoltageSensor(), name=f"V({net})")
        join(net, sensor, "p")
        d.link((sensor, "n"), (gnd, "p"))
    _grid(d)
    return d


def _grid(d: Diagram) -> None:
    for k, b in enumerate(d.blocks):
        b.meta["position"] = [float(160 * (k % 6)), float(110 * (k // 6))]


_LETTER = {
    "electrical.resistor": "R",
    "electrical.capacitor": "C",
    "electrical.inductor": "L",
    "electrical.voltage_source": "V",
    "electrical.current_source": "I",
    "semiconductors.diode": "D",
    "semiconductors.bjt": "Q",
    "semiconductors.mosfet": "M",
    "electrical.vcvs": "E",
    "electrical.vccs": "G",
}


def _stimulus(diagram: Diagram, source: Block) -> str:
    """SIN(...) or PULSE(...) for a controlled source driven by a Sine or Pulse block (through a Bias)."""
    conn = diagram.driver(source, 0)
    drv, v1 = (conn.src if conn else None), 0.0
    if drv is not None and drv.type_id == "math.bias":
        v1 = float(drv.params["bias"])
        up = diagram.driver(drv, 0)
        drv = up.src if up else None
    if drv is not None and drv.type_id == "sources.sine":
        q = drv.params
        return f"SIN({format_number(q['bias'] + v1)} {format_number(q['amplitude'])} {format_number(q['frequency'] / (2 * math.pi))})"
    if drv is not None and drv.type_id == "sources.pulse":
        q = drv.params
        per, pw = q["period"], q["period"] * q["duty"] / 100
        return f"PULSE({format_number(v1)} {format_number(v1 + q['amplitude'])} {format_number(q['delay'])} 0 0 {format_number(pw)} {format_number(per)})"
    return "0 ; controlled by a signal in Nervus"


def write_netlist(diagram: Diagram, path: str | Path | None = None) -> str:
    """The top level of ``diagram`` as a SPICE netlist (and written to ``path`` if given). Components without a
    SPICE equivalent (motors, batteries, switches, signal blocks) are listed as comments."""
    parent: dict[tuple[int, str], tuple[int, str]] = {}

    def find(k: tuple[int, str]) -> tuple[int, str]:
        while parent.setdefault(k, k) != k:
            k = parent[k]
        return k

    for link in diagram.links:
        parent[find((id(link.a), link.a_port))] = find((id(link.b), link.b_port))
    names: dict[tuple[int, str], str] = {}
    for b in diagram.blocks:
        if b.type_id == "electrical.reference":
            names[find((id(b), "p"))] = "0"
        m = re.fullmatch(r"V\((.+)\)", b.name)
        if b.type_id == "electrical.voltage_sensor" and m:
            names.setdefault(find((id(b), "p")), m.group(1))
    counter = 0

    def net(b: Block, port: str) -> str:
        nonlocal counter
        root = find((id(b), port))
        if root not in names:
            counter += 1
            names[root] = f"N{counter:03d}"
        return names[root]

    out = [f"* {diagram.name or 'nervus'} (written by Nervus)"]
    models: list[str] = []
    for b in diagram.blocks:
        letter = _LETTER.get(b.type_id)
        if letter is None:
            if b.physical_ports() and b.type_id not in ("electrical.reference", "electrical.voltage_sensor"):
                out.append(f"* {b.name}: {b.label} has no SPICE equivalent")
            continue
        ref = b.name if b.name[0].upper() == letter else f"{letter}{b.name}"
        p = b.params
        pins = [net(b, port) for port, _dom in b.physical_ports()]
        if letter in "RCL":
            value = format_number(p["R" if letter == "R" else "C" if letter == "C" else "L"])
            ic = p.get("v0" if letter == "C" else "i0", 0.0)
            out.append(f"{ref} {pins[0]} {pins[1]} {value}" + (f" IC={format_number(ic)}" if ic else ""))
        elif letter in "VI":
            if p["controlled"]:
                out.append(f"{ref} {pins[0]} {pins[1]} {_stimulus(diagram, b)}")
            else:
                out.append(f"{ref} {pins[0]} {pins[1]} DC {format_number(p['V' if letter == 'V' else 'I'])}")
        elif letter == "D":
            model = f"D_{ref}"
            bv = f" BV={format_number(p['BV'])} IBV={format_number(p['IBV'])}" if math.isfinite(p["BV"]) else ""
            models.append(f".model {model} D(IS={p['Is']:g} N={p['N']:g}{bv})")
            out.append(f"{ref} {pins[0]} {pins[1]} {model}")
        elif letter == "Q":
            model = f"Q_{ref}"
            models.append(f".model {model} {p['type']}(IS={p['Is']:g} BF={p['BF']:g} BR={p['BR']:g})")
            out.append(f"{ref} {pins[0]} {pins[1]} {pins[2]} {model}")
        elif letter == "M":
            model = f"M_{ref}"
            kind = "NMOS" if p["type"] == "N" else "PMOS"
            vto = p["Vth"] if p["type"] == "N" else -p["Vth"]
            models.append(f".model {model} {kind}(VTO={vto:g} KP={p['K']:g} LAMBDA={p['lam']:g})")
            out.append(f"{ref} {pins[0]} {pins[1]} {pins[2]} {pins[2]} {model} W=1 L=1")
        else:
            gain = p["gain"] if letter == "E" else p["gm"]
            out.append(f"{ref} {' '.join(pins)} {format_number(gain)}")
    out += models
    s = diagram.settings
    if s.step:
        out.append(f".tran {format_number(s.step)} {format_number(s.t_final)}")
    out.append(".end")
    text = "\n".join(out) + "\n"
    if path is not None:
        Path(path).write_text(text, encoding="utf-8")
    return text
