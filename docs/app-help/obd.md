# OBD-II: read live data from a car

Every petrol car since 2001 (EU) / 1996 (US), and every diesel since 2004, has an **OBD-II** diagnostic port,
usually under the dashboard near the steering column. With an **ELM327** adapter (USB or Bluetooth) Nervus can
read the standard live values that SAE J1979 defines as *mode 01 PIDs*: engine speed, vehicle speed,
temperatures, air flow, throttle position, fuel trims and more.

Use it to:

- record a real drive and compare it with your model in the **Data Inspector**;
- replay the recording as the input of a **test case** (for example, real rpm and throttle into your idle
  controller);
- check that your plant model behaves like your car.

**Read-only:**
Nervus only sends standard *read* requests (mode 01). It never writes to or reprograms the car's ECUs.

## Setup

```bash
uv sync --extra obd          # installs pyserial
uv run python -m nervus.obd pids                                 # PIDs Nervus can decode
uv run python -m nervus.obd supported --port /dev/tty.usbserial-1110
uv run python -m nervus.obd record --port /dev/tty.usbserial-1110 \
    --pids rpm,speed,coolant_temp,throttle --duration 120 --out drive.nervres
```

On Windows the port is called `COM3` or similar; on Linux `/dev/ttyUSB0` or `/dev/rfcomm0` for Bluetooth.
Turn the ignition on (or start the engine) before connecting.

Open `drive.nervres` with **File → Open Result** in the Data Inspector, or save it as CSV with
`--out drive.csv`.

## How a PID is decoded

The adapter sends a request such as `010C` (mode 01, PID 0x0C = engine speed). The car answers with
`41 0C A B`, where *A* and *B* are data bytes. Each PID has a formula, for example:

$$ n_{\text{engine}} = \frac{256\,A + B}{4}\ \text{rpm}, \qquad T_{\text{coolant}} = A - 40\ \text{°C} $$

| Name | PID | Unit | Formula |
|---|---|---|---|
| `engine_load` | 04 | % | A·100/255 |
| `coolant_temp` | 05 | °C | A − 40 |
| `stft_b1`, `ltft_b1` | 06, 07 | % | (A − 128)·100/128 |
| `map` | 0B | kPa | A |
| `rpm` | 0C | rpm | (256A + B)/4 |
| `speed` | 0D | km/h | A |
| `timing_advance` | 0E | ° | A/2 − 64 |
| `intake_temp` | 0F | °C | A − 40 |
| `maf` | 10 | g/s | (256A + B)/100 |
| `throttle` | 11 | % | A·100/255 |
| `o2_b1s1` | 14 | V | A/200 |
| `run_time` | 1F | s | 256A + B |
| `fuel_level` | 2F | % | A·100/255 |
| `baro` | 33 | kPa | A |
| `module_voltage` | 42 | V | (256A + B)/1000 |
| `lambda_cmd` | 44 | – | 2(256A + B)/65536 |
| `ambient_temp` | 46 | °C | A − 40 |
| `pedal_d` | 49 | % | A·100/255 |
| `oil_temp` | 5C | °C | A − 40 |
| `fuel_rate` | 5E | L/h | (256A + B)/20 |

Not every car reports every PID; `supported` asks the car which ones it has.

## In Python

```python
from nervus.core import Signal
from nervus.obd import Elm327, SerialTransport, record

elm = Elm327(SerialTransport("/dev/tty.usbserial-1110"))
elm.initialize()
drive = record(elm, ["rpm", "throttle"], duration=60)
drive.save("drive.nervres")

rpm_input = Signal(drive.t, drive["rpm"], "linear")  # use as a test-case input
```

Over an ELM327 each PID takes roughly 30–100 ms, so polling 4 PIDs gives a few samples per second. Planned
next (see the plan, Phase 22): trouble codes and freeze frames, OBD directly over a CAN interface, and a live
recording window in the editor.
