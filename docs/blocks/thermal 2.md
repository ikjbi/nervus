# Thermal

## Thermal Mass

`thermal.mass` · Thermal

A body that stores heat; its temperature is a state:

$$ m\,c\,\frac{dT}{dt} = \sum Q, \qquad T(0) = T_0 $$

For example the engine block, the coolant, or a power transistor with its heat sink.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `C` | `1000.0` | J/K | Heat capacity m·c |
| `T0` | `20.0` | °C | Initial temperature |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Thermal Resistance

`thermal.resistance` · Thermal

Heat conduction or convection between two ports: $Q = (T_a - T_b) / R$, with $R = 1/(h A)$ for convection
(heat transfer coefficient *h*, area *A*).

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `R` | `0.1` | K/W | Thermal resistance |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Heat Source

`thermal.heat_source` · Thermal

Heat flowing into a port: the parameter *Q* or the input signal (e.g. a heater, or the losses of a
component computed elsewhere).

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `Q` | `100.0` | W | Heat flow (when not controlled) |
| `controlled` | `False` |  | The heat flow comes from the input signal |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Temperature Source

`thermal.temperature_source` · Thermal

Holds a port at a temperature, whatever the heat flow: the ambient air, a coolant at a fixed
temperature. The parameter *T* or the input signal.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `T` | `20.0` | °C | Temperature (when not controlled) |
| `controlled` | `False` |  | The temperature comes from the input signal |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Temperature Sensor

`thermal.temperature_sensor` · Thermal

Measures the temperature of a port as a signal, in °C.

*Direct feedthrough:* yes · no inputs

---

## Heat Flow Sensor

`thermal.heat_flow_sensor` · Thermal

Measures the heat flowing through it from ``a`` to ``b`` as a signal, in W.

*Direct feedthrough:* yes · no inputs

---
