# Hydraulic

## Tank

`hydraulic.reference` · Hydraulic

The tank: the port linked to it is at 0 bar (ambient).

*Direct feedthrough:* yes · no inputs, no outputs

---

## Flow Source (Pump)

`hydraulic.flow_source` · Hydraulic

A pump with a given flow from ``a`` (suction) to ``b`` (outlet), whatever the pressure: the parameter
*Q* or the input signal (an electric fuel pump driven by the ECU).

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `Q` | `1.0` | L/min | Flow (when not controlled) |
| `controlled` | `False` |  | The flow comes from the input signal |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Pressure Source

`hydraulic.pressure_source` · Hydraulic

Holds port ``a`` at a pressure above the tank: the parameter *p* or the input signal.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `p` | `4.0` | bar | Pressure (when not controlled) |
| `controlled` | `False` |  | The pressure comes from the input signal |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Orifice

`hydraulic.orifice` · Hydraulic

A restriction with turbulent flow (an injector nozzle, a valve seat, a filter):

$$ q = q_1\,\frac{\Delta p}{\sqrt{|\Delta p| + p_{lam}}} $$

*q_1* is the flow at 1 bar; at high pressure the flow grows with the square root of the pressure drop,
near zero it becomes laminar (linear) below *p_lam*, so the equations stay smooth. A *controlled* orifice
scales its opening with the input (0 closed .. 1 open), e.g. a valve.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `q1` | `1.0` | L/min | Flow at a pressure drop of 1 bar |
| `p_lam` | `0.01` | bar | Laminar pressure range |
| `controlled` | `False` |  | The opening (0..1) comes from the input signal |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Relief Valve

`hydraulic.relief_valve` · Hydraulic

A pressure relief (or pressure regulator) valve: closed below the cracking pressure, then opening in
proportion to the overpressure, like the regulator of a returnless fuel system:

$$ q = k\,\max(\Delta p - p_{crack},\ 0) \quad \text{(smoothed over 0.05 bar)} $$

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `p_crack` | `4.0` | bar | Cracking pressure |
| `k` | `20.0` | L/min/bar | Flow per bar above the cracking pressure |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Hydraulic Volume

`hydraulic.volume` · Hydraulic

A volume of fluid (a fuel rail, an accumulator, a hose): its pressure rises as fluid flows in,

$$ \frac{V}{\beta}\,\frac{dp}{dt} = q_{in} $$

with the bulk modulus β of the fluid (about 15 000 bar for petrol; less with air or a soft hose: the
effective value). Its pressure is a state.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `V` | `0.05` | L | Volume |
| `beta` | `15000.0` | bar | Effective bulk modulus |
| `p0` | `0.0` | bar | Initial pressure |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Pressure Sensor

`hydraulic.pressure_sensor` · Hydraulic

Measures the pressure of a port (above the tank) as a signal, in bar.

*Direct feedthrough:* yes · no inputs

---

## Flow Sensor

`hydraulic.flow_sensor` · Hydraulic

Measures the flow through it from ``a`` to ``b`` as a signal, in L/min.

*Direct feedthrough:* yes · no inputs

---
