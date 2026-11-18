# Control

## PID Controller

`control.pid` · Control

Continuous PID controller (parallel form) with a filtered derivative:

$$ u = P\,e + I \int e\,dt + D \frac{N s}{s + N} e $$

The input is the control error *e*. The output is limited to [*lower*, *upper*]. When the output saturates,
the integral term keeps growing ("winds up") and causes overshoot. *anti_windup* prevents that:

- ``clamping`` stops integrating while the output is saturated and the error would push it further out.
- ``back_calculation`` feeds the excess ``Kb·(y - u_unsat)`` back into the integrator. It is smooth, which
  variable-step solvers handle well.

!!! note
    ``clamping`` switches abruptly. With variable-step solvers it can make the simulation very slow,
    until zero-crossing detection is implemented. Prefer ``back_calculation``, or use a fixed-step solver.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `P` | `1.0` |  | Proportional gain |
| `I` | `0.0` | 1/s | Integral gain |
| `D` | `0.0` | s | Derivative gain |
| `N` | `100.0` | rad/s | Derivative filter coefficient |
| `initial_integrator` | `0.0` |  | Initial value of the integral term |
| `upper` | inf |  | Output upper limit |
| `lower` | -inf |  | Output lower limit |
| `anti_windup` | `'none'` |  | Anti-windup method used while the output is saturated — one of `none`, `clamping`, `back_calculation` |
| `Kb` | `1.0` | 1/s | Back-calculation gain |

*Direct feedthrough:* yes

---

## Discrete PID Controller

`control.discrete_pid` · Control

Discrete PID controller (parallel form), as it would run on an ECU every *sample_time* seconds.

The integral and the derivative filter use forward Euler:

$$ u[k] = P\,e[k] + x_i[k] + D N (e[k] - x_f[k]) $$
$$ x_i[k+1] = x_i[k] + I\,T\,e[k], \qquad x_f[k+1] = x_f[k] + N\,T\,(e[k] - x_f[k]) $$

The derivative filter is stable only when ``N·T < 2``. See `PID` for the anti-windup options;
``clamping`` works well here because the controller is discrete.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `P` | `1.0` |  | Proportional gain |
| `I` | `0.0` | 1/s | Integral gain |
| `D` | `0.0` | s | Derivative gain |
| `N` | `100.0` | rad/s | Derivative filter coefficient |
| `initial_integrator` | `0.0` |  | Initial value of the integral term |
| `upper` | inf |  | Output upper limit |
| `lower` | -inf |  | Output lower limit |
| `anti_windup` | `'none'` |  | Anti-windup method used while the output is saturated — one of `none`, `clamping`, `back_calculation` |
| `Kb` | `1.0` | 1/s | Back-calculation gain |
| `sample_time` | `0.01` | s | Sample period |

*Direct feedthrough:* yes

---
