import numpy as np
import pytest

from nervus import Diagram, simulate
from nervus.blocks import Gain, Inport, Lookup2D, Outport, Scope, ZeroOrderHold
from nervus.codegen import CodegenError, generate_c
from nervus.core import Variable
from nervus.core.errors import ParameterError
from nervus.io import dumps, loads

SPEED = [800.0, 1500.0, 3000.0, 6000.0]
LOAD = [0.2, 0.5, 1.0]
MAP = [[10.3, 8.1, 5.0], [20.2, 16.4, 10.7], [30.9, 25.3, 18.1], [35.2, 30.6, 22.8]]


def ignition_model() -> Diagram:
    d = Diagram("ign")
    ws = d.workspace
    ws.add(Variable("speed_axis", SPEED, "Engine speed axis", "rpm", data_type="uint16"))
    ws.add(Variable("load_axis", LOAD, "Load axis", "-", data_type="fixdt(0,16,15)"))
    ws.add(Variable("ign_map", MAP, "Ignition advance", "°", data_type="fixdt(1,16,7)"))
    ws.add(Variable("k_trim", 1.05, "Global trim (fixed in ROM)", "-", calibratable=False))
    rpm, load = d.add(Inport(port=1), name="rpm"), d.add(Inport(port=2), name="load")
    z1, z2 = d.add(ZeroOrderHold(sample_time=0.01)), d.add(ZeroOrderHold(sample_time=0.01))
    m = d.add(Lookup2D(row_breakpoints="speed_axis", column_breakpoints="load_axis", table="ign_map"), name="map")
    trim = d.add(Gain(gain="k_trim"), name="trim")
    d.chain(rpm, z1)
    d.chain(load, z2)
    d.connect(z1, (m, 0))
    d.connect(z2, (m, 1))
    d.chain(m, trim, d.add(Outport(port=1), name="advance"))
    return d


def test_simulation_uses_the_stored_values() -> None:
    d = ignition_model()
    ns = d.workspace.namespace()
    assert ns["ign_map"][0][0] == round(10.3 * 128) / 128  # fixdt(1,16,7): steps of 1/128
    assert ns["load_axis"][1] == round(0.5 * 2**15) / 2**15
    r = simulate(d, 0.0, inputs={"rpm": 1500.0, "load": 0.5})
    assert r["map"][-1] == pytest.approx(ns["ign_map"][1][1])


def test_typed_and_const_params_in_c_and_a2l(tmp_path) -> None:  # type: ignore[no-untyped-def]
    code = generate_c(ignition_model())
    h, c, a2l = code.files["ign.h"], code.files["ign.c"], code.files["ign.a2l"]
    assert "int16_T ign_map[12];" in h and "uint16_T speed_axis[4];" in h and "uint16_T load_axis[3];" in h
    assert "extern const ign_C_t ign_C;" in h and "real_T k_trim[1];" in h
    assert "const ign_C_t ign_C = {" in c
    assert str(round(10.3 * 128)) in c  # stored integers
    assert "RL_SWORD" in a2l and "COEFFS_LINEAR 0.0078125 0.0" in a2l and "k_trim" not in a2l
    from nervus.codegen.sil import back_to_back, find_compiler

    if find_compiler() is not None:
        k = np.arange(80)
        res = back_to_back(
            ignition_model(), {"rpm": 700 + 80.0 * k, "load": 0.1 + 0.012 * k}, 80, tolerance=1e-12, folder=tmp_path
        )
        assert res.passed, res.summary()


def test_matrix_parameter_must_be_double() -> None:
    d = Diagram("m")
    d.workspace.add(Variable("K", [[1.0, 2.0], [3.0, 4.0]], data_type="int16"))
    u = d.add(Inport(port=1), name="u")
    g = d.add(Gain(gain="K", multiplication="matrix"), name="g")
    d.chain(u, d.add(ZeroOrderHold(sample_time=0.01)), g, d.add(Outport(port=1), name="y"))
    d.block("u").set_param("value", [0.0, 0.0])
    with pytest.raises(CodegenError, match="double parameter"):
        generate_c(d)


def test_variable_attributes_roundtrip_and_validation() -> None:
    d = ignition_model()
    again = loads(dumps(d)).workspace
    assert again.variable("ign_map").data_type == "fixdt(1,16,7)"
    assert again.variable("k_trim").calibratable is False
    with pytest.raises(ParameterError):
        Variable("x", 1.0, data_type="int17")
    d.add(Scope())
