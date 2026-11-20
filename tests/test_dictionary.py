"""The data dictionary: signal objects bound to named block outputs."""

from pathlib import Path

import pytest

from nervus import Diagram, ModelError, ParameterError, load, save, simulate
from nervus.blocks import DataTypeConversion, Gain, Inport, Outport, Ramp, Scope, Subsystem, UnitDelay
from nervus.core.dictionary import SignalObject, named_signals


def _model() -> Diagram:
    d = Diagram("dd")
    d.signals.add(SignalObject("engine_speed", "double", "rpm", 0.0, 7000.0, "Crankshaft speed"))
    d.signals.add(SignalObject("pedal", unit="%", min=0.0, max=100.0))
    ramp = d.add(Ramp(slope=1000.0), name="rpm_source")
    g = d.add(Gain(gain=1.0), name="k")
    d.chain(ramp, g, d.add(Scope(), name="sc"))
    d.name_signal(g, 0, "engine_speed")
    return d


def test_names_results_and_ranges(tmp_path: Path) -> None:
    d = _model()
    assert named_signals(d) == {"engine_speed": ("k", 0)}
    r = simulate(d, 8.0, solver="rk4", step=0.1)
    assert r["engine_speed"][-1] == pytest.approx(8000.0)
    assert any("engine_speed is above its maximum 7000 from t = 7" in w for w in r.stats.warnings or [])
    # Saved and loaded with the model.
    save(d, tmp_path / "m")
    again = load(tmp_path / "m.nervus")
    assert again.signals["engine_speed"].unit == "rpm" and again.signals["pedal"].max == 100.0
    assert named_signals(again) == {"engine_speed": ("k", 0)}
    # Unique names, valid names, removing a name.
    with pytest.raises(ParameterError, match="already used"):
        d.name_signal("rpm_source", 0, "engine_speed")
    with pytest.raises(ParameterError, match="invalid signal name"):
        d.name_signal("k", 0, "2fast")
    d.name_signal("k", 0, None)
    assert named_signals(d) == {}
    with pytest.raises(ParameterError, match="min 5 is above max 1"):
        SignalObject("x", min=5.0, max=1.0)


def test_data_type_is_checked() -> None:
    d = _model()
    d.signals.add(SignalObject("engine_speed", "uint16", "rpm"))
    with pytest.raises(ModelError, match="declares as uint16, but the block outputs double"):
        simulate(d, 0.1)
    conv = d.add(DataTypeConversion(output_type="uint16"), name="to_u16")
    d.connect(d.block("k"), conv)
    d.connect(conv, d.add(Scope()))
    d.name_signal("k", 0, None)
    d.name_signal(conv, 0, "engine_speed")
    assert simulate(d, 0.1)["engine_speed"].dtype is not None


def test_subsystem_output_name() -> None:
    inner = Diagram()
    inner.chain(inner.add(Inport(port=1), name="u"), inner.add(Gain(gain=2.0), name="g"),
                inner.add(Outport(port=1), name="y"))  # fmt: skip
    d = Diagram()
    sub = d.add(Subsystem(system=inner), name="ctrl")
    d.chain(d.add(Ramp(slope=1.0), name="r"), sub, d.add(Scope(), name="sc"))
    d.name_signal(sub, 0, "torque_request")
    r = simulate(d, 1.0, solver="rk4", step=0.1)
    assert r["torque_request"][-1] == pytest.approx(2.0)


def test_named_measurements_in_a2l() -> None:
    from nervus.codegen import generate_c

    d = Diagram("ecu")
    d.signals.add(SignalObject("throttle_cmd", unit="%", min=0.0, max=100.0, description="Throttle command"))
    u = d.add(Inport(port=1), name="u")
    z = d.add(UnitDelay(sample_time=0.01), name="z")
    d.chain(u, z, d.add(Outport(port=1), name="y"))
    d.name_signal(z, 0, "throttle_cmd")
    code = generate_c(d)
    a2l = next(v for k, v in code.files.items() if k.endswith(".a2l"))
    block = a2l[a2l.index("/begin MEASUREMENT throttle_cmd") :]
    assert '"Throttle command"' in block.splitlines()[0]
    assert "0.0 100.0" in block.splitlines()[1] and "CM_" in block.splitlines()[1]
