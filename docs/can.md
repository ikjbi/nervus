# CAN communication

ECUs exchange signals over **CAN**. Which bits of a frame carry which signal, and how to convert them to
physical units, is described in a **DBC** file. Nervus reads DBC files (`uv sync --extra can`) and provides
two blocks in the **CAN** library:

| Block | Input | Output |
|---|---|---|
| **CAN Unpack** | the frame's 8 data bytes (a vector of width 8) | one output per signal, in physical units |
| **CAN Pack** | one input per signal, in physical units | the 8 data bytes (`uint8`) |

Set *dbc_file* (relative paths are relative to the model file), choose the *message* from the drop-down, and
optionally list the *signals* to use (empty = all, in DBC order).

![The bit layout of the EngineData message in examples/data/vehicle.dbc](images/blocks/can_frame.png)

## Conversion

Each signal occupies *length* bits starting at *start bit*:

$$ \mathrm{physical} = \mathrm{raw} \cdot \mathrm{factor} + \mathrm{offset} $$

- **Intel** byte order (`@1` in the DBC): the start bit is the signal's least significant bit; bytes are in
  little-endian order.
- **Motorola** byte order (`@0`): the start bit is the signal's most significant bit; bytes are in
  big-endian order.
- Signed signals (`-`) are two's complement.

**CAN Pack** rounds to the nearest raw value (half away from zero) and saturates to the bit field, so an
out-of-range value is sent as the closest representable one.

## Bit-exact and generatable

Packing and unpacking use the same 64-bit integer arithmetic in the simulation and in the generated C code.
The test suite checks the decoding against the `cantools` library for random frames, and checks the
generated C against the simulation with zero tolerance. A typical use is an ECU subsystem with a CAN Unpack
at its inputs and a CAN Pack at its outputs; the generated `step()` function then reads and writes raw frames.

## In Python

```python
from nervus.can import load_dbc, pack, unpack

msgs = load_dbc("examples/data/vehicle.dbc")
engine = msgs["EngineData"]
frame = pack(engine, {"EngineSpeed": 812.3, "CoolantTemp": 90})
unpack(engine.signal("EngineSpeed"), frame)  # 812.25 (0.25 rpm resolution)
```

## Planned

CAN FD (64-byte frames), multiplexed signals, value tables, DBC signals in the workspace, and XCP on CAN for
live measurement and calibration.
