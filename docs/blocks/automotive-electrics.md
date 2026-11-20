# Automotive Electrics

## Solenoid

`automotive.solenoid` · Automotive Electrics

A solenoid (an actuator coil with an armature): the coil current builds up with τ = L/R; above the
pull-in current the armature moves in, below the drop-out current it is released:

$$ L\,\frac{di}{dt} = v - R\,i, \qquad \tau\,\frac{dx}{dt} = x_{target} - x $$

Output: the armature position x (0 out, 1 in). For example a canister purge valve or a starter solenoid.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `R` | `12.0` | Ω | Coil resistance |
| `L` | `0.01` | H | Coil inductance |
| `I_pull` | `0.6` | A | Pull-in current |
| `I_drop` | `0.3` | A | Drop-out current |
| `tau` | `0.0005` | s | Armature travel time constant |

*Direct feedthrough:* yes · no inputs

---

## Fuel Injector

`automotive.injector` · Automotive Electrics

A solenoid fuel injector: the needle opens when the coil current passes the pull-in current, so the
injector opens a little after the ECU switches it on (the *opening delay*, which the ECU compensates with
the battery voltage) and closes after the current has decayed. Outputs: needle lift (0..1) and fuel flow
(lift × static flow, g/s). Typical port injector: R = 12 Ω, L = 10 mH, 3.5 g/s.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `R` | `12.0` | Ω | Coil resistance |
| `L` | `0.01` | H | Coil inductance |
| `I_pull` | `0.6` | A | Pull-in current |
| `I_drop` | `0.3` | A | Drop-out current |
| `tau` | `0.0005` | s | Armature travel time constant |
| `static_flow` | `3.5` | g/s | Flow when fully open |

*Direct feedthrough:* yes · no inputs

---

## Relay

`automotive.relay` · Automotive Electrics

A relay: a coil (``p``, ``n``) and a normally-open contact (``a``, ``b``) that closes while the armature
is pulled in. Output: 1 while the contact is closed. For example the main relay, the fuel pump relay or a
starter relay.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `R` | `80.0` | Ω | Coil resistance |
| `L` | `0.1` | H | Coil inductance |
| `I_pull` | `0.08` | A | Pull-in current |
| `I_drop` | `0.03` | A | Drop-out current |
| `tau` | `0.002` | s | Armature travel time constant |
| `R_contact` | `0.005` | Ω | Contact resistance when closed |

*Direct feedthrough:* yes · no inputs

---

## Glow Plug

`automotive.glow_plug` · Automotive Electrics

A diesel glow plug: a heater whose resistance rises with its temperature, which limits its current as it
heats up (self-regulating):

$$ R(T) = R_0\,(1 + \alpha\,(T - 20)), \qquad C\,\frac{dT}{dt} = \frac{v^2}{R(T)} - \frac{T - T_{case}}{R_{th}} $$

Ports: ``p``, ``n`` (electrical) and ``case`` (thermal: the cylinder head). Output: the tip temperature.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `R0` | `0.5` | Ω | Resistance at 20 °C |
| `alpha` | `0.006` | 1/K | Temperature coefficient |
| `C` | `3.0` | J/K | Heat capacity of the tip |
| `R_th` | `25.0` | K/W | Thermal resistance to the cylinder head |
| `T0` | `20.0` | °C | Initial temperature |

*Direct feedthrough:* yes · no inputs

---

## Alternator

`automotive.alternator` · Automotive Electrics

An alternator with its voltage regulator, driven by the engine through a belt:

$$ \tau_r\,\frac{dI}{dt} = \min(\max(K\,(V_{set} - v),\ 0),\ I_{max}(n)) - I $$

$$ \tau_{shaft} = \frac{v\,I}{\eta\,\omega} $$

It delivers current *I* out of ``p`` to hold *V_set*; at low speed it can deliver less (zero below the
cut-in speed, *I_rated* from *rated_rpm*). The current it delivers loads the engine: the torque on
``shaft`` (the crankshaft; *ratio* is the pulley ratio) is the electrical power divided by the efficiency.
Output: the current I.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `V_set` | `14.2` | V | Regulated voltage |
| `I_rated` | `120.0` | A | Maximum current at rated speed |
| `cut_in_rpm` | `1000.0` | rpm | Alternator speed where it starts to deliver |
| `rated_rpm` | `6000.0` | rpm | Alternator speed for the full current |
| `ratio` | `2.5` |  | Pulley ratio (alternator speed / engine speed) |
| `K` | `50.0` | A/V | Regulator gain |
| `tau_r` | `0.05` | s | Regulator and field time constant |
| `efficiency` | `0.6` |  | Efficiency |

*Direct feedthrough:* yes · no inputs

---
