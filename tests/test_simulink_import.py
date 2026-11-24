"""Importing Simulink .slx models."""

import zipfile
from pathlib import Path

import numpy as np
import pytest

from nervus import simulate
from nervus.simulink import matlab_expr, read_slx

ROOT_SYSTEM = """<?xml version="1.0" encoding="utf-8"?>
<System>
  <P Name="Location">[-1, -8, 1921, 1033]</P>
  <Block BlockType="Step" Name="Step" SID="1">
    <P Name="Position">[30, 85, 60, 115]</P>
    <P Name="Time">0</P>
  </Block>
  <Block BlockType="Sum" Name="Sum" SID="2">
    <P Name="Ports">[2, 1]</P>
    <P Name="Position">[100, 90, 120, 110]</P>
    <P Name="IconShape">round</P>
    <P Name="Inputs">|+-</P>
  </Block>
  <Block BlockType="Gain" Name="Controller Gain" SID="3">
    <P Name="Position">[160, 85, 190, 115]</P>
    <P Name="Gain">Kp</P>
  </Block>
  <Block BlockType="TransferFcn" Name="Plant" SID="4">
    <P Name="Position">[230, 82, 290, 118]</P>
    <P Name="Denominator">[tau 1]</P>
  </Block>
  <Block BlockType="Outport" Name="y" SID="5">
    <P Name="Position">[360, 93, 390, 107]</P>
  </Block>
  <Block BlockType="SubSystem" Name="Scaled" SID="6">
    <P Name="Ports">[1, 1]</P>
    <P Name="Position">[230, 160, 290, 200]</P>
    <Mask>
      <MaskParameter Name="K" Type="edit"><Prompt>Gain</Prompt><Value>2^2</Value></MaskParameter>
    </Mask>
    <System Ref="system_6"/>
  </Block>
  <Block BlockType="Outport" Name="y4" SID="9">
    <P Name="Position">[360, 173, 390, 187]</P>
    <P Name="Port">2</P>
  </Block>
  <Block BlockType="S-Function" Name="Legacy driver" SID="10">
    <P Name="Ports">[1, 1]</P>
    <P Name="Position">[160, 240, 220, 270]</P>
  </Block>
  <Block BlockType="Terminator" Name="Terminator" SID="11">
    <P Name="Position">[260, 245, 280, 265]</P>
  </Block>
  <Line>
    <P Name="Src">1#out:1</P>
    <P Name="Dst">2#in:1</P>
  </Line>
  <Line>
    <P Name="Src">2#out:1</P>
    <P Name="Dst">3#in:1</P>
  </Line>
  <Line>
    <P Name="Src">3#out:1</P>
    <P Name="Dst">4#in:1</P>
  </Line>
  <Line>
    <P Name="Src">4#out:1</P>
    <Branch><P Name="Dst">5#in:1</P></Branch>
    <Branch><P Name="Dst">2#in:2</P></Branch>
    <Branch><P Name="Dst">6#in:1</P></Branch>
    <Branch><P Name="Dst">10#in:1</P></Branch>
  </Line>
  <Line>
    <P Name="Src">6#out:1</P>
    <P Name="Dst">9#in:1</P>
  </Line>
  <Line>
    <P Name="Src">10#out:1</P>
    <P Name="Dst">11#in:1</P>
  </Line>
</System>
"""

SUB_SYSTEM = """<?xml version="1.0" encoding="utf-8"?>
<System>
  <Block BlockType="Inport" Name="u" SID="7"><P Name="Position">[20, 40, 50, 55]</P></Block>
  <Block BlockType="Gain" Name="Gain" SID="8"><P Name="Position">[90, 35, 120, 65]</P><P Name="Gain">K</P></Block>
  <Block BlockType="Outport" Name="v" SID="12"><P Name="Position">[160, 40, 190, 55]</P></Block>
  <Line><P Name="Src">7#out:1</P><P Name="Dst">8#in:1</P></Line>
  <Line><P Name="Src">8#out:1</P><P Name="Dst">12#in:1</P></Line>
</System>
"""


def _slx(tmp_path: Path) -> Path:
    path = tmp_path / "loop.slx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("simulink/blockdiagram.xml", "<ModelInformation/>")
        z.writestr("simulink/systems/system_root.xml", ROOT_SYSTEM)
        z.writestr("simulink/systems/system_6.xml", SUB_SYSTEM)
    return path


def test_import_and_simulate(tmp_path: Path) -> None:
    d = read_slx(_slx(tmp_path))
    names = {b.name for b in d.blocks}
    assert {"Step", "Sum", "Controller_Gain", "Plant", "y", "Scaled", "Legacy_driver"} <= names
    assert d.block("Sum").params["signs"] == "+-" and d.block("Controller_Gain").param_source("gain") == "Kp"
    assert d.block("Plant").param_source("denominator") == "[tau 1]"
    assert d.block("Step").meta["position"] == [30.0, 90.0]  # snapped to the grid
    report = d.meta["simulink_report"]
    assert "Legacy driver (S-Function)" in report and "Kp" in report and "tau" in report
    assert d.block("Scaled").mask["K"] == 4.0  # 2^2 in the mask
    # Give the workspace variables their values: a first-order loop, y(t) = Kp/(1+Kp) (1 - exp(-(1+Kp) t / tau)).
    d.workspace["Kp"] = 3.0
    d.workspace["tau"] = 0.5
    res = simulate(d, 2.0)
    y = np.ravel(res["y"])
    expected = 0.75 * (1 - np.exp(-4 * res.t / 0.5))
    assert np.max(np.abs(y - expected)) < 1e-3
    assert np.ravel(res["y4"])[-1] == pytest.approx(4 * 0.75, abs=1e-3)  # the masked subsystem: K = 4


@pytest.mark.parametrize(("matlab", "nervus"), [
    ("2^3", "2**3"), ("a.*b./c", "a*b/c"), ("x.^2", "x**2"), ("[0:0.5:2]", "[0 0.5 1 1.5 2]"),
    ("[1:3]", "[1 2 3]"), ("[1 2; 3 4]", "[1 2; 3 4]"), ("K*pi", "K*pi"),
])  # fmt: skip
def test_matlab_expressions(matlab: str, nervus: str) -> None:
    assert matlab_expr(matlab) == nervus


def test_not_an_slx(tmp_path: Path) -> None:
    from nervus.core.errors import NervusError

    bad = tmp_path / "model.mdl"
    bad.write_text('Model { Name "x" }')
    with pytest.raises(NervusError, match=r"not an \.slx file"):
        read_slx(bad)
