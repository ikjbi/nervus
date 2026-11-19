# Sources

## Constant

`sources.constant` · Sources

Outputs a constant value (scalar or vector).

**Parameters**

- *value*: the output value.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `value` | `1.0` |  | Output value |
| `sample_time` | inf | s | inf = constant |
| `output_type` | `'double'` |  | Output data type: inherit, double, single, boolean, int8…uint32, fixdt(signed, bits, fraction) |

*Direct feedthrough:* yes · no inputs

---

## Step

`sources.step` · Sources

Steps from *initial* to *final* at *time*.

![Step parameters](../images/blocks/step.png)

$$ y(t) = \begin{cases} \text{initial} & \text{if } t < \text{time} \\
\text{final} & \text{if } t \ge \text{time} \end{cases} $$

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `time` | `1.0` | s | Step time |
| `initial` | `0.0` |  | Value before the step |
| `final` | `1.0` |  | Value after the step |
| `sample_time` | `0.0` | s | 0 = continuous, > 0 = discrete period |

*Direct feedthrough:* yes · no inputs

---

## Ramp

`sources.ramp` · Sources

A ramp starting at *start_time*:

$$ y(t) = \mathrm{initial} + \mathrm{slope} \cdot \max(0,\ t - t_\mathrm{start}) $$

![Ramp parameters](../images/blocks/ramp.png)

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `slope` | `1.0` | 1/s | Slope |
| `start_time` | `0.0` | s | Time the ramp starts |
| `initial` | `0.0` |  | Output before the ramp starts |
| `sample_time` | `0.0` | s | 0 = continuous, > 0 = discrete period |

*Direct feedthrough:* yes · no inputs

---

## Sine Wave

`sources.sine` · Sources

Sine wave:

$$ y(t) = A \sin(\omega t + \varphi) + b $$

with amplitude *A*, angular *frequency* ω, *phase* φ and *bias* b.

![Sine Wave parameters](../images/blocks/sine.png)

*frequency* is in rad/s, as in Simulink. For a frequency *f* in Hz use ``2*pi*f``.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `amplitude` | `1.0` |  | Amplitude |
| `frequency` | `1.0` | rad/s | Angular frequency |
| `phase` | `0.0` | rad | Phase |
| `bias` | `0.0` |  | Offset added to the wave |
| `sample_time` | `0.0` | s | 0 = continuous, > 0 = discrete period |

*Direct feedthrough:* yes · no inputs

---

## Pulse Generator

`sources.pulse` · Sources

Square pulse train. High (*amplitude*) for *duty* percent of each *period*, otherwise 0.
The first pulse starts at *delay*.

![Pulse Generator parameters](../images/blocks/pulse.png)

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `amplitude` | `1.0` |  | Pulse height |
| `period` | `1.0` | s | Period |
| `duty` | `50.0` | % | Pulse width as % of the period |
| `delay` | `0.0` | s | Phase delay |
| `sample_time` | `0.0` | s | 0 = continuous, > 0 = discrete period |

*Direct feedthrough:* yes · no inputs

---

## Clock

`sources.clock` · Sources

Outputs the simulation time *t*.

*Direct feedthrough:* yes · no inputs

---

## From Workspace

`sources.from_workspace` · Sources

Plays back recorded data.

![Linear interpolation vs hold](../images/blocks/from_workspace.png)

Give either *time* and *data* arrays (data has one row per time point, one column per signal element), or a
*csv_file* whose first column is time and remaining columns are data (a header row is skipped automatically).

*interpolation*: ``linear`` interpolates between points; ``hold`` keeps the last value (zero-order hold).
Outside the time range the first/last value is held.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `time` | `[0.0, 1.0]` | s | Time points (increasing) |
| `data` | `[0.0, 1.0]` |  | Values: one row per time point |
| `csv_file` | `''` |  | Optional CSV file (overrides time/data) |
| `interpolation` | `'linear'` |  | Interpolation — one of `linear`, `hold` |
| `sample_time` | `0.0` | s | 0 = continuous, > 0 = discrete period |

*Direct feedthrough:* yes · no inputs

---

## Ground

`sources.ground` · Sources

Outputs zero. Use it to connect an input you do not need, instead of leaving it unconnected.

*Direct feedthrough:* yes · no inputs

---
