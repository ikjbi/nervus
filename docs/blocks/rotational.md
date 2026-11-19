# Rotational

## Rotational Reference

`rotational.reference` · Rotational

A fixed point: the port linked to it does not rotate (ω = 0), e.g. a housing.

*Direct feedthrough:* yes · no inputs, no outputs

---

## Inertia

`rotational.inertia` · Rotational

A rotating mass; its speed is a state:

$$ J\,\frac{d\omega}{dt} = \sum \tau, \qquad \omega(0) = \omega_0 $$

The sum of the torques acting on its port accelerates it.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `J` | `0.01` | kg·m² | Moment of inertia |
| `w0` | `0.0` | rad/s | Initial speed |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Rotational Spring

`rotational.spring` · Rotational

A torsion spring between two flanges; its torque is a state:

$$ \frac{d\tau}{dt} = k\,(\omega_a - \omega_b), \qquad \tau(0) = k\,\varphi_0 $$

*phi0* is the initial twist (preload), e.g. a throttle return spring.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `k` | `1.0` | N·m/rad | Stiffness |
| `phi0` | `0.0` | rad | Initial twist (preload) |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Rotational Damper

`rotational.damper` · Rotational

Viscous friction between two flanges: $\tau = d\,(\omega_a - \omega_b)$. Link ``b`` to a Rotational
Reference for bearing friction against the housing.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `d` | `0.01` | N·m·s/rad | Damping |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Torque Source

`rotational.torque_source` · Rotational

A torque on a flange, against the reference: the parameter *tau*, or the input signal when
*controlled* (e.g. a load torque, or an engine's torque).

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `tau` | `1.0` | N·m | Torque (when not controlled) |
| `controlled` | `False` |  | The torque comes from the input signal |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Speed Source

`rotational.speed_source` · Rotational

Drives a flange at a given speed, whatever the torque: the parameter *w* or the input signal.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `w` | `100.0` | rad/s | Speed (when not controlled) |
| `controlled` | `False` |  | The speed comes from the input signal |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Ideal Gear

`rotational.gear` · Rotational

A gear without losses or backlash, ratio *n* = ω_a / ω_b:

$$ \omega_a = n\,\omega_b, \qquad \tau_b = n\,\tau_a $$

For example a throttle's gear train (n = 20: the motor turns 20 times faster than the plate) or a gearbox.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `n` | `10.0` |  | Ratio ω_a / ω_b |

*Direct feedthrough:* yes · no inputs, no outputs

---

## Speed Sensor

`rotational.speed_sensor` · Rotational

Measures the angular velocity of a flange (against the reference) as a signal, in rad/s.

*Direct feedthrough:* yes · no inputs

---

## Angle Sensor

`rotational.angle_sensor` · Rotational

Measures the angle of a flange (the integral of its speed) as a signal, in rad. *phi0*: the angle at
the start.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `phi0` | `0.0` | rad | Angle at the start |

*Direct feedthrough:* yes · no inputs

---

## Torque Sensor

`rotational.torque_sensor` · Rotational

Measures the torque transmitted through it from ``a`` to ``b`` (a stiff shaft between the two).

*Direct feedthrough:* yes · no inputs

---
