# Semiconductors

## Diode

`semiconductors.diode` · Semiconductors

A diode with the Shockley equation, like SPICE's diode model:

$$ i = I_s\left(e^{v/(N V_T)} - 1\right) - I_{BV}\, e^{-(v + BV)/(N V_T)} $$

The second term is the reverse breakdown (a **Zener** diode): set *BV* to the Zener voltage. Ports ``p``
(anode) and ``n`` (cathode). Typical values:

| Device | Is [A] | N | BV [V] |
|---|---|---|---|
| 1N4148 small-signal | 2.5e-9 | 1.75 | 100 |
| 1N4007 rectifier | 7e-9 | 1.8 | 1000 |
| red LED (≈ 1.9 V at 20 mA) | 1e-18 | 1.9 | 5 |
| Zener 5.1 V | 1e-14 | 1 | 5.1 |

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `Is` | `1e-14` | A | Saturation current |
| `N` | `1.0` |  | Emission coefficient |
| `BV` | inf | V | Reverse breakdown voltage (Zener voltage) |
| `IBV` | `0.001` | A | Current at the breakdown voltage |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Bipolar Transistor

`semiconductors.bjt` · Semiconductors

A bipolar transistor (Ebers-Moll transport model), NPN or PNP. Ports ``c`` (collector), ``b`` (base),
``e`` (emitter):

$$ I_C = I_s\left(e^{V_{BE}/V_T} - e^{V_{BC}/V_T}\right) - \frac{I_s}{\beta_R}\left(e^{V_{BC}/V_T} - 1\right),
   \qquad I_B = \frac{I_s}{\beta_F}\left(e^{V_{BE}/V_T} - 1\right) + \frac{I_s}{\beta_R}\left(e^{V_{BC}/V_T} - 1\right) $$

In the active region the collector current is β_F times the base current; as a switch (a relay driver)
the transistor saturates with a small collector-emitter voltage. A small NPN like the 2N2222: Is = 1e-14,
β_F = 200.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `type` | `'NPN'` |  | Polarity — one of `NPN`, `PNP` |
| `Is` | `1e-14` | A | Saturation current |
| `BF` | `100.0` |  | Forward current gain β_F |
| `BR` | `1.0` |  | Reverse current gain β_R |

*Direct feedthrough:* yes · no inputs, no outputs

---

## MOSFET

`semiconductors.mosfet` · Semiconductors

A MOSFET (SPICE level 1, square law), N- or P-channel. Ports ``d`` (drain), ``g`` (gate), ``s`` (source);
no current flows into the gate:

$$ I_D = \begin{cases} 0 & V_{GS} \le V_{th} \\ K\left((V_{GS} - V_{th})V_{DS} - V_{DS}^2/2\right)(1 + \lambda V_{DS}) & V_{DS} < V_{GS} - V_{th} \\
   \frac{K}{2}(V_{GS} - V_{th})^2 (1 + \lambda V_{DS}) & \text{saturation} \end{cases} $$

*K* = μC_ox·W/L. A logic-level switch like a 2N7000: Vth = 2 V, K = 0.1 A/V²; a power MOSFET driving a
motor: Vth = 3 V, K = 20 A/V². The device is symmetric: with V_DS < 0 drain and source swap roles.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `type` | `'N'` |  | Channel — one of `N`, `P` |
| `K` | `0.1` | A/V² | Transconductance parameter μCox·W/L |
| `Vth` | `2.0` | V | Threshold voltage (positive for both types) |
| `lam` | `0.0` | 1/V | Channel-length modulation λ |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Op-Amp

`semiconductors.opamp` · Semiconductors

An operational amplifier: high gain, and the output limited to its supply rails:

$$ v_{out} = v_{mid} + v_{half} \tanh\left(\frac{A\,(v_+ - v_-)}{v_{half}}\right) $$

with $v_{mid} = (V_{pos} + V_{neg})/2$ and $v_{half} = (V_{pos} - V_{neg})/2$.

No current flows into the inputs ``plus`` and ``minus``; the output ``out`` is referenced to ground and can
deliver any current. With negative feedback it is an amplifier or an active filter; without, a comparator.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `A` | `100000.0` |  | Open-loop gain |
| `Vpos` | `15.0` | V | Positive output rail |
| `Vneg` | `-15.0` | V | Negative output rail |

*Direct feedthrough:* yes · no inputs, no outputs

---
