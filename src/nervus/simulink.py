"""Import a Simulink model (``.slx``) as a Nervus model.

    from nervus.simulink import read_slx
    model = read_slx("controller.slx")
    print(model.meta["simulink_report"])   # what was not imported

An ``.slx`` file is a zip archive of XML files: ``simulink/systems/system_root.xml`` is the top level, and every
subsystem refers to its own ``system_<n>.xml``. Each ``<Block>`` has a ``BlockType``, a ``Name``, an ``SID`` and
``<P Name="...">`` parameters (parameters at their default value are left out); each ``<Line>`` goes from
``<SID>#out:<port>`` to ``<SID>#in:<port>``, with ``<Branch>`` elements where it fans out.

The common blocks are translated (sources, math, continuous and discrete, logic, routing, lookup tables, PID
controllers, ports and subsystems, with masks). MATLAB expressions in parameters are kept with their workspace
variables (``K``, ``2*pi``, ``[1 2 3]``; ``^`` becomes ``**`` and ``0:0.5:2`` a list). A block that cannot be
translated becomes an empty subsystem with the same ports, named after the Simulink block, so the wiring stays; the
import report lists those blocks and the workspace variables the model uses (added with the value 1: give them their
values). ``.mdl`` files are read too, the classic text format and the newer one (R2019b on) that packs the same XML
parts as an ``.slx``.

**Stateflow charts** become State Chart blocks (see :mod:`nervus.stateflow`): states, hierarchy, parallel states,
transitions through junctions, temporal logic and the chart's data. The report lists what was approximated. The
stop time and fixed step of the model's configuration are imported too.
"""

from __future__ import annotations

import math
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from nervus.blocks import (
    PID,
    Abs,
    Bias,
    Clock,
    CompareToConstant,
    Constant,
    DataTypeConversion,
    DeadZone,
    Demux,
    DiscreteIntegrator,
    DiscretePID,
    DiscreteTransferFunction,
    Gain,
    Ground,
    Inport,
    Integrator,
    LogicalOperator,
    Lookup1D,
    Lookup2D,
    MinMax,
    Mux,
    Outport,
    Product,
    Quantizer,
    Ramp,
    RateLimiter,
    RelationalOperator,
    Relay,
    RepeatingSequence,
    Saturation,
    Scope,
    Sine,
    StateChart,
    StateSpace,
    Step,
    Subsystem,
    Sum,
    Switch,
    Terminator,
    ToWorkspace,
    TransferFunction,
    UnitDelay,
    ZeroOrderHold,
)
from nervus.core import Diagram, Variable
from nervus.core.block import Block
from nervus.core.errors import NervusError
from nervus.core.expressions import parse_value

_KNOWN_NAMES = {"pi", "inf", "Inf", "eps", "e", "sqrt", "exp", "log", "sin", "cos", "tan", "abs", "min", "max",
                "true", "false", "floor", "ceil", "round", "nan", "NaN"}  # fmt: skip


@dataclass
class ImportReport:
    blocks: int = 0
    unsupported: list[str] = field(default_factory=list)
    """``path (BlockType)`` of the blocks that became empty placeholders."""
    variables: list[str] = field(default_factory=list)
    """Workspace variables the model uses (added with the value 1)."""
    notes: list[str] = field(default_factory=list)
    charts: list[str] = field(default_factory=list)
    """Stateflow charts imported as State Charts."""

    def __str__(self) -> str:
        lines = [f"Imported {self.blocks} blocks."]
        if self.charts:
            lines.append(f"Stateflow charts imported as State Charts ({len(self.charts)}): {', '.join(self.charts)}")
        if self.unsupported:
            lines.append(f"Not supported, imported as empty subsystems ({len(self.unsupported)}): "
                         + ", ".join(self.unsupported))  # fmt: skip
        if self.variables:
            lines.append("Workspace variables, set to 1 (give them their values in the Model Workspace): "
                         + ", ".join(self.variables))  # fmt: skip
        lines += self.notes
        return "\n".join(lines)


# ---------------------------------------------------------------------------- MATLAB expressions


def matlab_expr(text: str) -> str:
    """A MATLAB parameter expression in Nervus's syntax: ``^`` → ``**``, element-wise operators, ranges, ``~=``."""
    s = text.strip()
    s = s.replace(".^", "**").replace(".*", "*").replace("./", "/").replace("^", "**").replace("~=", "!=")

    def expand(m: re.Match[str]) -> str:
        parts = [float(x) for x in m.group(0).split(":")]
        start, step, stop = (parts[0], 1.0, parts[1]) if len(parts) == 2 else parts
        if step == 0 or (stop - start) / step > 10000:
            return m.group(0)
        n = int((stop - start) / step + 1e-9) + 1
        return " ".join(f"{start + k * step:.15g}" for k in range(max(n, 0)))  # all digits, no rounding noise

    number = r"-?\d+(?:\.\d*)?(?:e[-+]?\d+)?"
    return re.sub(rf"{number}:{number}(?::{number})?", expand, s)


def _names(expr: str) -> set[str]:
    return {n for n in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr) if n not in _KNOWN_NAMES} - {"e"}


# ---------------------------------------------------------------------------- reading the archive


class _Archive:
    def __init__(self, path: Path) -> None:
        try:
            self.zip = zipfile.ZipFile(path)
        except zipfile.BadZipFile as exc:
            raise NervusError(f"{path.name} is not an .slx file (an .slx is a zip archive)") from exc
        self.names = set(self.zip.namelist())
        self.open_refs: set[str] = set()
        """The systems being read (a subsystem that contains itself would never end)."""

    def read(self, name: str) -> bytes | None:
        """A part of the archive (``simulink/stateflow/machine.xml``), or ``None``."""
        if name not in self.names:
            return None
        try:
            return self.zip.read(name)
        except (zipfile.BadZipFile, OSError) as exc:
            raise NervusError(f"cannot read {name} in the .slx file: {exc}") from exc

    def system(self, ref: str) -> ET.Element:
        name = f"simulink/systems/{ref}.xml"
        data = self.read(name)
        if data is None:
            raise NervusError(f"the model file has no {name}")
        try:
            return ET.fromstring(data)
        except ET.ParseError as exc:
            raise NervusError(f"cannot read {name} in the model file: {exc}") from exc


class _TextPackage(_Archive):
    """An ``.mdl`` file of R2019b and later: the parts of an ``.slx`` as text, each after a line
    ``__MWOPC_PART_BEGIN__ /simulink/systems/system_root.xml`` (binary parts are base64 and not needed)."""

    def __init__(self, text: str) -> None:
        self.parts: dict[str, bytes] = {}
        for chunk in text.split("__MWOPC_PART_BEGIN__ ")[1:]:
            head, _, body = chunk.partition("\n")
            name = head.strip().split(" ")[0].lstrip("/")
            if head.strip().endswith("BASE64"):
                continue
            body = body.split("__MWOPC_PACKAGE_END__")[0]
            self.parts[name] = body.encode("utf-8")
        self.names = set(self.parts)
        self.open_refs = set()

    def read(self, name: str) -> bytes | None:
        return self.parts.get(name)


def _params(el: ET.Element) -> dict[str, str]:
    """The block's parameters, with those of a library block's ``<InstanceData>``."""
    out = {p.get("Name", ""): (p.text or "") for p in el.findall("P")}
    for inst in el.findall("InstanceData"):
        out.update({p.get("Name", ""): (p.text or "") for p in inst.findall("P")})
    return out


def _mask(el: ET.Element) -> dict[str, str]:
    """Mask parameters of a masked subsystem: name -> value expression."""
    out: dict[str, str] = {}
    mask = el.find("Mask")
    if mask is None:
        return out
    for mp in mask.findall("MaskParameter"):
        name = mp.get("Name", "")
        value = mp.findtext("Value") or ""
        if name:
            out[name] = value
    return out


def _ports(params: dict[str, str]) -> tuple[int, int]:
    nums = [int(x) for x in re.findall(r"\d+", params.get("Ports", "[1, 1]"))]
    return (nums[0] if nums else 1), (nums[1] if len(nums) > 1 else 1)


# ---------------------------------------------------------------------------- blocks


def _count(spec: str) -> int:
    """A number of ports written as ``3`` or as a list of widths ``[1, 2]``."""
    spec = spec.strip()
    return int(spec) if spec.isdigit() else max(1, len([x for x in spec.strip("[]").split(",") if x.strip()]))


def _signs(spec: str, plus: str) -> str:
    spec = spec.strip() or "2"
    if spec.isdigit():
        return plus * int(spec)
    return spec.replace("|", "")


def _make(btype: str, p: dict[str, str], mask_source: str) -> Block | None:
    """The Nervus block for a Simulink block, or ``None`` if there is none."""
    g = p.get
    e = matlab_expr
    if btype == "Reference":  # a library block, e.g. the PID controller
        source = mask_source
        if "PID Controller" in source:
            kw = {"P": e(g("P", "1")), "I": e(g("I", "1")), "D": e(g("D", "0")), "N": e(g("N", "100"))}
            if "Discrete" in source or g("TimeDomain", "") == "Discrete-time":
                return DiscretePID(sample_time=e(g("SampleTime", "-1")), **kw)
            return PID(**kw)
        if "Repeating" in source and "Sequence" in source and "Stair" not in source:
            return RepeatingSequence(times=e(g("rep_seq_t", "[0 2]")), values=e(g("rep_seq_y", "[0 2]")))
        return None
    if btype == "Gain":
        return Gain(gain=e(g("Gain", "1")))
    if btype == "Sum":
        return Sum(signs=_signs(g("Inputs", "++"), "+"))
    if btype == "Product":
        return Product(ops=_signs(g("Inputs", "2"), "*"))
    if btype == "Constant":
        return Constant(value=e(g("Value", "1")))
    if btype == "Step":
        return Step(time=e(g("Time", "1")), initial=e(g("Before", "0")), final=e(g("After", "1")))
    if btype == "Sin":
        return Sine(amplitude=e(g("Amplitude", "1")), frequency=e(g("Frequency", "1")),
                    phase=e(g("Phase", "0")), bias=e(g("Bias", "0")))  # fmt: skip
    if btype == "Ramp":
        return Ramp(slope=e(g("slope", "1")), start_time=e(g("start", "0")), initial=e(g("InitialOutput", "0")))
    if btype == "Clock":
        return Clock()
    if btype == "Ground":
        return Ground()
    if btype == "Integrator":
        return Integrator(initial=e(g("InitialCondition", "0")), upper=e(g("UpperSaturationLimit", "inf")),
                          lower=e(g("LowerSaturationLimit", "-inf")))  # fmt: skip
    if btype == "TransferFcn":
        return TransferFunction(numerator=e(g("Numerator", "[1]")), denominator=e(g("Denominator", "[1 1]")))
    if btype == "StateSpace":
        return StateSpace(A=e(g("A", "1")), B=e(g("B", "1")), C=e(g("C", "1")), D=e(g("D", "1")))
    if btype in ("UnitDelay", "Memory"):
        return UnitDelay(initial=e(g("InitialCondition", g("X0", "0"))), sample_time=e(g("SampleTime", "-1")))
    if btype == "ZeroOrderHold":
        return ZeroOrderHold(sample_time=e(g("SampleTime", "1")))
    if btype == "DiscreteIntegrator":
        return DiscreteIntegrator(gain=e(g("gainval", "1")), initial=e(g("InitialCondition", "0")),
                                  sample_time=e(g("SampleTime", "1")),
                                  method="backward_euler" if "Backward" in g("IntegratorMethod", "") else "forward_euler")  # fmt: skip
    if btype == "DiscreteTransferFcn":
        return DiscreteTransferFunction(numerator=e(g("Numerator", "[1]")), denominator=e(g("Denominator", "[1 0.5]")),
                                        sample_time=e(g("SampleTime", "1")))  # fmt: skip
    if btype == "Saturate":
        return Saturation(upper=e(g("UpperLimit", "0.5")), lower=e(g("LowerLimit", "-0.5")))
    if btype == "DeadZone":
        return DeadZone(start=e(g("LowerValue", "-0.5")), end=e(g("UpperValue", "0.5")))
    if btype == "RateLimiter":
        return RateLimiter(rising_rate=e(g("RisingSlewLimit", "1")), falling_rate=e(g("FallingSlewLimit", "-1")))
    if btype == "Relay":
        return Relay(on_point=e(g("OnSwitchValue", "eps")), off_point=e(g("OffSwitchValue", "eps")),
                     on_value=e(g("OnOutputValue", "1")), off_value=e(g("OffOutputValue", "0")))  # fmt: skip
    if btype == "Quantizer":
        return Quantizer(interval=e(g("QuantizationInterval", "0.5")))
    if btype == "Abs":
        return Abs()
    if btype == "Bias":
        return Bias(bias=e(g("Bias", "0")))
    if btype == "MinMax":
        return MinMax(function=g("Function", "min"), num_inputs=_count(g("Inputs", "1")))
    if btype == "RelationalOperator":
        return RelationalOperator(operator=g("Operator", ">=").replace("~=", "!="))
    if btype == "Logic":
        op = g("Operator", "AND").upper()
        return LogicalOperator(operator=op, num_inputs=1 if op == "NOT" else _count(g("Inputs", "2")))
    if btype == "Switch":
        crit = g("Criteria", "u2 >= Threshold")
        criterion = (
            "u1 != 0" if "~=" in crit else "u1 > threshold" if ">" in crit and ">=" not in crit else "u1 >= threshold"
        )
        return Switch(criterion=criterion, threshold=e(g("Threshold", "0")))
    if btype == "Mux":
        return Mux(num_inputs=_count(g("Inputs", "2")))
    if btype == "Demux":
        return Demux(num_outputs=_count(g("Outputs", "2")))
    if btype == "Lookup_n-D":
        dims = g("NumberOfTableDimensions", "2")
        if dims == "1":
            return Lookup1D(breakpoints=e(g("BreakpointsForDimension1", "[1:3]")), table=e(g("Table", "[4 5 6]")))
        if dims == "2":
            return Lookup2D(row_breakpoints=e(g("BreakpointsForDimension1", "[1:3]")),
                            column_breakpoints=e(g("BreakpointsForDimension2", "[1:3]")),
                            table=e(g("Table", "[4 5 6; 16 19 20; 10 18 23]")))  # fmt: skip
        return None
    if btype == "Lookup":  # the old 1-D lookup table
        return Lookup1D(breakpoints=e(g("InputValues", "[-5:5]")), table=e(g("Table", "tanh([-5:5])")))
    if btype == "DataTypeConversion":
        dtype = g("OutDataTypeStr", "Inherit: auto").strip()
        return DataTypeConversion(output_type="inherit" if dtype.startswith("Inherit") else dtype)
    if btype == "Scope":
        return Scope(num_inputs=int(g("NumInputPorts", "1") or 1))
    if btype == "Terminator":
        return Terminator()
    if btype == "ToWorkspace":
        return ToWorkspace(variable=g("VariableName", "simout"))
    if btype == "CompareToConstant":
        return CompareToConstant(operator=g("relop", "<=").replace("~=", "!="), constant=e(g("const", "3")))
    return None


def _port_number(p: dict[str, str], where: str) -> int:
    text = p.get("Port", "1").strip()
    if not text.isdigit() or int(text) < 1:
        raise NervusError(f"{where}: port number {text!r} is not a positive integer; the .slx file is damaged")
    return int(text)


def _not_imported(btype: str, p: dict[str, str]) -> list[str]:
    """Settings of a translated block that the Nervus block does not have: notes for the report (the block keeps
    the Nervus behaviour, which may differ)."""
    notes = []
    if btype == "DiscreteIntegrator":
        method = p.get("IntegratorMethod", "")
        if method not in ("", "Integration: Forward Euler", "Integration: Backward Euler"):
            notes.append(f"integrator method {method!r} not imported: it integrates with Euler and the sample time "
                         "(Integration: Forward/Backward Euler); check the block")  # fmt: skip
        if p.get("LimitOutput", "off") == "on":
            notes.append("output limits not imported; set the block's upper and lower limits")
        if p.get("ExternalReset", "none") != "none":
            notes.append(f"external reset {p['ExternalReset']!r} not imported")
    if btype == "Lookup_n-D":
        extrap = p.get("ExtrapMethod", "")
        if extrap != "Clip":
            notes.append(f"extrapolation {extrap or '(Simulink default)'!r} not imported: the Nervus table clips at "
                         "its ends; check the block's extrapolation")  # fmt: skip
        interp = p.get("InterpMethod", "")
        if interp not in ("", "Linear", "Linear point-slope"):
            notes.append(f"interpolation {interp!r} not imported: the Nervus table interpolates linearly")
    if btype == "Lookup" and p.get("LookUpMeth", "") != "Interpolation-Use End Values":
        method = p.get("LookUpMeth", "") or "(Simulink default)"
        notes.append(f"lookup method {method!r} not imported: the Nervus table interpolates linearly and clips at "
                     "its ends; check the block")  # fmt: skip
    return notes


def _placeholder(n_in: int, n_out: int, btype: str) -> Subsystem:
    """An empty subsystem with the block's ports, for a block that is not translated (its outputs are 0)."""
    inner = Diagram(btype)
    for k in range(n_in):
        inner.connect(inner.add(Inport(port=k + 1), name=f"in{k + 1}"), inner.add(Terminator(), name=f"unused{k + 1}"))
    for k in range(n_out):
        inner.connect(inner.add(Ground(), name=f"zero{k + 1}"), inner.add(Outport(port=k + 1), name=f"out{k + 1}"))
    sub = Subsystem(system=inner)
    sub.mask_icon = f"Simulink\\n{btype}"
    sub.mask_description = f"A Simulink {btype} block: not translated by the import (its outputs are 0)."
    return sub


# ---------------------------------------------------------------------------- systems


def _parameters_used(block: Block) -> set[str]:
    names: set[str] = set()
    for value in block.expressions.values():
        names |= _names(str(value))
    return names


def _build(archive: Any, system: ET.Element, d: Diagram, path: str, report: ImportReport,
           used: set[str]) -> None:  # fmt: skip
    by_sid: dict[str, Block] = {}
    for el in system.findall("Block"):
        btype, name, sid = el.get("BlockType", ""), el.get("Name", ""), el.get("SID", "")
        p = _params(el)
        block: Block | None
        if btype in ("EnablePort", "TriggerPort", "ActionPort"):
            report.notes.append(f"{path}{name}: {btype} — the subsystem's enable/trigger is not translated")
            continue
        if btype == "Inport":
            block = Inport(port=_port_number(p, f"{path}{name}"))
        elif btype == "Outport":
            block = Outport(port=_port_number(p, f"{path}{name}"))
        elif btype == "SubSystem" and p.get("SFBlockType", "") == "Chart":
            block = _chart(archive, f"{path}{name}", name, _ports(p), report)
        elif btype == "SubSystem" and p.get("SFBlockType", "") not in ("", "NONE"):
            block = _placeholder(*_ports(p), p["SFBlockType"])
            report.unsupported.append(f"{path}{name} ({p['SFBlockType']})")
        elif btype == "SubSystem":
            ref = el.find("System")
            if ref is None or ref.get("Ref") is None:
                block = _placeholder(*_ports(p), "SubSystem")
                report.unsupported.append(f"{path}{name} (SubSystem without contents)")
            else:
                inner = Diagram(name)
                sub = Subsystem(system=inner)
                for k, v in _mask(el).items():
                    expr = matlab_expr(v)
                    try:
                        sub.mask.add(Variable(k, float(parse_value(expr))))
                    except (ValueError, TypeError, NervusError):
                        sub.mask.add(Variable(k, 1.0, f"from Simulink: {v}"))
                        used |= _names(expr)
                block = sub
                ref_name = str(ref.get("Ref"))
                if ref_name in archive.open_refs:
                    raise NervusError(
                        f"{path}{name}: the subsystem contains itself ({ref_name}); the .slx file is damaged"
                    )
                archive.open_refs.add(ref_name)
                _build(archive, archive.system(ref_name), inner, f"{path}{name}/", report, used)
                archive.open_refs.discard(ref_name)
                used -= set(sub.mask)  # the mask's own parameters
        else:
            try:
                block = _make(btype, p, p.get("SourceBlock", ""))
            except (ValueError, NervusError) as exc:
                report.notes.append(f"{path}{name}: {exc}")
                block = None
            if block is None:
                block = _placeholder(
                    *_ports(p), p.get("SourceBlock", btype).split("/")[-1] if btype == "Reference" else btype
                )
                report.unsupported.append(f"{path}{name} ({p.get('SourceBlock', btype)})")
            else:
                used |= _parameters_used(block)
                report.notes += [f"{path}{name}: {note}" for note in _not_imported(btype, p)]
        report.blocks += 1
        pos = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", p.get("Position", ""))]
        if len(pos) == 4:
            block.meta["position"] = [math.floor(pos[0] / 10 + 0.5) * 10.0, math.floor(pos[1] / 10 + 0.5) * 10.0]
        if p.get("Orientation", "right") == "left":
            block.meta["flipped"] = True
        d.add(block, name=_unique(d, name))
        by_sid[sid] = block
    for line in system.findall("Line"):
        _connect(d, by_sid, line, None, path, report)


def _chart(archive: Any, block_path: str, name: str, ports: tuple[int, int], report: ImportReport) -> Block:
    """The Stateflow chart of the block at ``block_path`` as a State Chart (a placeholder if it cannot be read)."""
    from nervus.stateflow import convert_chart

    where = block_path
    try:
        xml = _chart_xml(archive, block_path, name)
        result = convert_chart(xml, name)
    except (NervusError, ET.ParseError) as exc:
        report.unsupported.append(f"{where} (Stateflow chart: {str(exc).splitlines()[0]})")
        return _placeholder(*ports, "Stateflow chart")
    block = StateChart(definition=result.definition, state_output=False, sample_time=result.sample_time)
    block.meta["chart_layout"] = result.layout
    report.notes += [f"{where}: {n}" for n in dict.fromkeys(result.notes)]
    report.charts.append(where)
    return block


def _chart_xml(archive: Any, block_path: str, name: str) -> bytes:
    """``simulink/stateflow/chart_<id>.xml`` of the chart block: machine.xml maps block paths to chart ids."""
    machine = archive.read("simulink/stateflow/machine.xml")
    charts = sorted(n for n in archive.names if re.fullmatch(r"simulink/stateflow/chart_\d+\.xml", n))
    if machine is not None:
        root = ET.fromstring(machine)
        for inst in root.iter("instance"):
            p = _params(inst)
            if p.get("name", "").replace("\n", " ") == block_path.replace("\n", " "):
                data = archive.read(f"simulink/stateflow/chart_{p.get('chart', '')}.xml")
                if data is not None:
                    return data
    for part in charts:  # no instance: the chart with the block's name
        data = archive.read(part)
        if data is not None and re.search(rf'<P Name="name">{re.escape(name)}</P>', data.decode("utf-8", "replace")):
            return data
    raise NervusError("the chart is not in the model file (a chart in a library or an older .mdl file)")


def _unique(d: Diagram, name: str) -> str:
    base = re.sub(r"\s+", "_", name.strip()) or "block"
    base = base.replace("/", "_")
    out, k = base, 1
    names = {b.name for b in d.blocks}
    while out in names:
        k += 1
        out = f"{base}_{k}"
    return out


def _end(text: str) -> tuple[str, str, int] | None:
    m = re.match(r"^(\d+(?::\d+)*)#(in|out|enable|trigger):?(\d*)$", text.strip())
    if not m:
        return None
    return m.group(1), m.group(2), int(m.group(3) or 1)


def _connect(d: Diagram, by_sid: dict[str, Block], line: ET.Element, src: tuple[Block, int] | None, path: str,
             report: ImportReport) -> None:  # fmt: skip
    p = _params(line)
    if "Src" in p:
        end = _end(p["Src"])
        if end is None or end[0] not in by_sid:
            return
        src = (by_sid[end[0]], end[2] - 1)
    if src is None:
        return
    if "Dst" in p:
        end = _end(p["Dst"])
        if end is not None and end[0] in by_sid and end[1] == "in":
            try:
                d.connect(src, (by_sid[end[0]], end[2] - 1))
            except (IndexError, NervusError) as exc:
                report.notes.append(f"{path}: line {p.get('Src', '')} → {p['Dst']} not connected ({exc})")
    for branch in line.findall("Branch"):
        _connect(d, by_sid, branch, src, path, report)


# ---------------------------------------------------------------------------- the .mdl text format


@dataclass
class _Section:
    kind: str
    params: dict[str, str] = field(default_factory=dict)
    children: list[_Section] = field(default_factory=list)


def _unquote(text: str) -> str:
    """A value: one or more adjacent "strings" joined (MATLAB splits long strings), or a bare word or array."""
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', text)
    if not parts:
        return text.strip()
    return "".join(parts).replace('\\"', '"').replace("\\n", "\n")


def _parse_mdl(text: str) -> _Section:
    """The nested ``Name { key value ... }`` sections of an .mdl file, one key and value per line; a line that is
    only a string continues the previous value."""
    root = _Section("root")
    stack = [root]
    last: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("{"):
            sec = _Section(line[:-1].strip())
            stack[-1].children.append(sec)
            stack.append(sec)
            last = None
        elif line == "}":
            if len(stack) > 1:
                stack.pop()
            last = None
        elif line.startswith('"') and last is not None:
            stack[-1].params[last] += _unquote(line)
        else:
            parts = line.split(None, 1)  # .mdl files separate the key and the value with tabs
            key, rest = parts[0], (parts[1] if len(parts) > 1 else "")
            stack[-1].params[key] = _unquote(rest)
            last = key
    return root


class _MdlArchive:
    """The .mdl file's systems as the XML elements the .slx import reads."""

    def __init__(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"^\s*(Model|Library)\s*\{", text, re.M):
            raise NervusError(f"{path.name} is not a Simulink .mdl file")
        model = next((c for c in _parse_mdl(text).children if c.kind in ("Model", "Library")), None)
        system = next((c for c in model.children if c.kind == "System"), None) if model else None
        if system is None:
            raise NervusError(f"{path.name} has no System")
        self.systems: dict[str, ET.Element] = {}
        self._sid = 0
        self.open_refs: set[str] = set()
        """The systems being read (see `_Archive`)."""
        self.names: set[str] = set()
        """No parts: the classic .mdl keeps Stateflow in its own section (not read)."""
        self.systems["system_root"] = self._convert(system)

    def system(self, ref: str) -> ET.Element:
        return self.systems[ref]

    def read(self, name: str) -> bytes | None:
        return None  # the classic .mdl keeps Stateflow in its own section (not read)

    def _convert(self, sec: _Section) -> ET.Element:
        el = ET.Element("System")
        sids: dict[str, str] = {}
        for blk in (c for c in sec.children if c.kind == "Block"):
            self._sid += 1
            sid = str(self._sid)
            name = blk.params.get("Name", f"block{sid}")
            sids[name] = sid
            b = ET.SubElement(el, "Block", BlockType=blk.params.get("BlockType", ""), Name=name, SID=sid)
            for k, v in blk.params.items():
                if k not in ("Name", "BlockType", "SID"):
                    ET.SubElement(b, "P", Name=k).text = v
            names = [n for n in re.split(r"\|", blk.params.get("MaskNames", "")) if n]
            values = re.split(r"\|", blk.params.get("MaskValueString", ""))
            if names:
                mask = ET.SubElement(b, "Mask")
                for n, v in zip(names, values, strict=False):
                    mp = ET.SubElement(mask, "MaskParameter", Name=n)
                    ET.SubElement(mp, "Value").text = v
            inner = next((c for c in blk.children if c.kind == "System"), None)
            if inner is not None:
                ref = f"system_{sid}"
                ET.SubElement(b, "System", Ref=ref)
                self.systems[ref] = self._convert(inner)
        for line in (c for c in sec.children if c.kind == "Line"):
            el.append(self._line(line, sids))
        return el

    def _line(self, sec: _Section, sids: dict[str, str]) -> ET.Element:
        out = ET.Element("Line" if sec.kind == "Line" else "Branch")
        p = sec.params
        if "SrcBlock" in p and p["SrcBlock"] in sids:
            ET.SubElement(out, "P", Name="Src").text = f"{sids[p['SrcBlock']]}#out:{p.get('SrcPort', '1')}"
        if "DstBlock" in p and p["DstBlock"] in sids:
            port = p.get("DstPort", "1")
            kind = port if port in ("enable", "trigger") else "in"
            ET.SubElement(out, "P", Name="Dst").text = f"{sids[p['DstBlock']]}#{kind}:{port if kind == 'in' else ''}"
        for branch in (c for c in sec.children if c.kind == "Branch"):
            out.append(self._line(branch, sids))
        return out


def read_model(path: str | Path) -> Diagram:
    """Read a Simulink model: ``.slx`` or ``.mdl``."""
    return read_mdl(path) if Path(path).suffix.lower() == ".mdl" else read_slx(path)


def read_mdl(path: str | Path) -> Diagram:
    """Read a Simulink ``.mdl`` model (the text format). The import report is in ``model.meta["simulink_report"]``."""
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    if "__MWOPC_PACKAGE_BEGIN__" in text:
        return _read(_TextPackage(text), p)
    return _read(_MdlArchive(p), p)


def read_slx(path: str | Path) -> Diagram:
    """Read a Simulink ``.slx`` model. The import report is in ``model.meta["simulink_report"]``."""
    p = Path(path)
    return _read(_Archive(p), p)


def _settings(archive: Any, d: Diagram, report: ImportReport) -> None:
    """Stop time, solver and fixed step from the active configuration set."""
    data = archive.read("simulink/configSet0.xml")
    if data is None:
        return
    p: dict[str, str] = {}
    for el in ET.fromstring(data).iter("P"):
        p.setdefault(el.get("Name", ""), el.text or "")

    def number(key: str) -> float | None:
        try:
            v = float(p.get(key, "").strip())
        except ValueError:
            return None
        return v if math.isfinite(v) else None

    s = d.settings
    start, stop = number("StartTime"), number("StopTime")
    if start is not None:
        s.t_start = start
    if stop is not None and stop >= s.t_start:
        s.t_final = stop
    solver = p.get("SolverName", p.get("Solver", ""))
    if p.get("SolverType", "") == "Fixed-step" or solver.startswith("FixedStep") or solver in ("ode1", "ode4"):
        s.solver = {"ode1": "euler", "FixedStepDiscrete": "euler"}.get(solver, "rk4")
        s.step = number("FixedStep")
    text = f"Simulation: {s.t_start:g} to {s.t_final:g} s, solver {s.solver}"
    report.notes.append(text + (f", step {s.step:g} s" if s.step else ""))


def _read(archive: Any, p: Path) -> Diagram:
    root = archive.system("system_root")
    d = Diagram(re.sub(r"\W", "_", p.stem))
    report = ImportReport()
    used: set[str] = set()
    _build(archive, root, d, "", report, used)
    _settings(archive, d, report)
    for name in sorted(used):
        if name not in d.workspace:
            d.workspace.add(Variable(name, 1.0, "from the Simulink model: give it its value"))
            report.variables.append(name)
    d.meta["simulink_report"] = str(report)
    d.meta["simulink_unsupported"] = list(report.unsupported)
    return d
