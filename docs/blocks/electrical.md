# Electrical

## Electrical Reference

`electrical.reference` · Electrical

Ground: the node it is linked to is at 0 V. Every circuit needs one.

*Direct feedthrough:* yes · no inputs, no outputs

---

## Resistor

`electrical.resistor` · Electrical

An ideal resistor (Ohm's law):

$$ v_p - v_n = R\,i $$

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `R` | `1.0` | Ω | Resistance |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Capacitor

`electrical.capacitor` · Electrical

An ideal capacitor; its voltage is a state:

$$ C\,\frac{dv}{dt} = i, \qquad v = v_p - v_n,\quad v(0) = v_0 $$

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `C` | `1e-06` | F | Capacitance |
| `v0` | `0.0` | V | Initial voltage |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Inductor

`electrical.inductor` · Electrical

An ideal inductor; its current is a state:

$$ L\,\frac{di}{dt} = v_p - v_n, \qquad i(0) = i_0 $$

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `L` | `0.001` | H | Inductance |
| `i0` | `0.0` | A | Initial current |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Voltage Source

`electrical.voltage_source` · Electrical

An ideal voltage source: $v_p - v_n = V$. With *controlled* on, the voltage is the input signal (e.g. from
a controller); otherwise it is the parameter *V* (a battery, a supply).

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `V` | `12.0` | V | Voltage (when not controlled) |
| `controlled` | `False` |  | The voltage comes from the input signal |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Current Source

`electrical.current_source` · Electrical

An ideal current source: the current *I* flows out of its ``p`` port into the circuit (and back in at
``n``). With *controlled* on, the current is the input signal.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `I` | `1.0` | A | Current (when not controlled) |
| `controlled` | `False` |  | The current comes from the input signal |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Voltage Sensor

`electrical.voltage_sensor` · Electrical

Measures the voltage $v_p - v_n$ as a signal (ideal: no current flows into it).

*Direct feedthrough:* yes · no inputs

---

## Current Sensor

`electrical.current_sensor` · Electrical

Measures the current flowing through it from ``p`` to ``n`` as a signal. Put it in series, like an
ammeter (ideal: no voltage across it).

*Direct feedthrough:* yes · no inputs

---

## Switch

`electrical.switch` · Electrical

A switch controlled by a signal: closed (resistance *R_on*) while the input is ≥ 0.5, open (conductance
*G_off*) otherwise. Use it for a relay, a transistor driven as a switch, or a fuse.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `R_on` | `0.001` | Ω | Resistance when closed |
| `G_off` | `1e-08` | S | Conductance when open |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Diode

`electrical.diode` · Electrical

A piecewise-linear diode: conducts from ``p`` (anode) to ``n`` (cathode) when the voltage exceeds the
forward voltage *Vf*:

$$ i = \begin{cases} (v - V_f) / R_{on} & v > V_f \\ G_{off}\, v & \text{otherwise} \end{cases} $$

For example the freewheeling diode across a relay coil or a motor.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `Vf` | `0.6` | V | Forward voltage |
| `R_on` | `0.01` | Ω | Resistance when conducting |
| `G_off` | `1e-08` | S | Conductance when blocking |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Battery

`electrical.battery` · Electrical

A battery: open-circuit voltage from its state of charge, and an internal resistance:

$$ v_p - v_n = \mathrm{OCV}(SOC) - R_i\, i_{out}, \qquad \frac{dSOC}{dt} = -\frac{i_{out}}{3600\, Q} $$

*Q* is the capacity in Ah, *i_out* the current delivered from ``p``. The OCV is a table over SOC (0..1); the
default is a 12 V lead-acid battery. Output: the state of charge (0..1).

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `capacity` | `60.0` | Ah | Capacity Q |
| `R_internal` | `0.01` | Ω | Internal resistance |
| `soc0` | `0.9` |  | Initial state of charge (0..1) |
| `soc_breakpoints` | `[0.0, 0.2, 0.5, 0.8, 1.0]` |  | SOC points of the OCV table |
| `ocv` | `[11.6, 11.9, 12.2, 12.5, 12.8]` | V | Open-circuit voltage at each SOC point |

*Direct feedthrough:* yes · no inputs

---

## H-Bridge (PWM)

`electrical.h_bridge` · Electrical

An H-bridge driving a motor with PWM, as an average model: the output voltage is the duty cycle times
the supply voltage, and the supply delivers the same power (no losses):

$$ v_a - v_b = d\,(v_+ - v_-), \qquad i_{supply} = d\, i_{out}, \qquad -1 \le d \le 1 $$

A negative duty cycle reverses the motor. Ports: ``supply_p``, ``supply_n`` (the battery) and ``a``, ``b``
(the motor). Input: the duty cycle (limited to ±1).

*Direct feedthrough:* yes · no inputs, no outputs

---

## DC Motor

`electrical.dc_motor` · Electrical

A permanent-magnet DC motor: electrical port ``p``/``n``, mechanical port ``shaft``:

$$ L\,\frac{di}{dt} = v_p - v_n - R\,i - k\,\omega, \qquad \tau = k\,i $$

*k* is both the torque constant (N·m/A) and the back-EMF constant (V·s/rad). The torque acts on the shaft
against the reference (the motor housing); add an Inertia for the rotor and a Rotational Damper for its
friction. The armature current is a state.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `R` | `1.0` | Ω | Armature resistance |
| `L` | `0.001` | H | Armature inductance |
| `k` | `0.05` | N·m/A | Torque and back-EMF constant |

*Direct feedthrough:* yes · no inputs, no outputs

---
