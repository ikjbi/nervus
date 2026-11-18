# Concepts

## Signals

Every signal is a vector of floating-point numbers. A scalar signal has **width 1**. Widths are worked out
automatically when the model is compiled. Most math blocks work elementwise, and a scalar combines with a
vector by **scalar expansion** (a scalar gain of 2 doubles every element).

## Blocks

A block is a small dynamic system with inputs *u*, outputs *y* and optionally states *x*:

| Function | Meaning | Called |
|---|---|---|
| `outputs(t, u, xc, xd)` | output equation $y = g(t, u, x)$ | whenever outputs are needed |
| `derivatives(t, u, xc, xd)` | continuous states $\dot x_c = f(t, u, x_c)$ | by the solver |
| `update(t, u, xc, xd)` | discrete states $x_d[k+1] = f(t, u, x_d[k])$ | at the block's sample hits |

**Direct feedthrough** means that `outputs` uses *u* directly (Gain, Sum). Blocks whose output only
depends on their state (Integrator, Unit Delay) are *not* direct feedthrough.

## Execution order and algebraic loops

Before simulating, Nervus sorts the blocks so that each direct-feedthrough block runs after the blocks
that drive it. A feedback loop made **only** of direct-feedthrough blocks has no valid order. That is an
**algebraic loop**: $y = u - 2y$ defines *y* in terms of itself. Nervus reports these as errors and lists
the blocks involved:

```
AlgebraicLoopError: algebraic loop: s -> g -> s. Every feedback loop needs a block with state ...
```

Put an Integrator (continuous) or a Unit Delay (discrete) in the loop. In a real control system that
delay always exists anyway.

## Sample times

Each block runs at a **sample time**, using the same values as Simulink:

| Value | Meaning |
|---|---|
| `0` | continuous: computed at every solver step |
| `T > 0` | discrete: computed every *T* seconds, held in between |
| `[T, offset]` | discrete with an offset |
| `-1` | inherited from the blocks that drive it |
| `inf` | constant: computed once |

Inherited blocks take the sample time of their inputs: a Gain after a 10 ms Zero-Order Hold also runs every
10 ms. If its inputs have mixed rates it becomes continuous.

Discrete outputs are computed **only at sample hits** and held between them. That is how code on an ECU
behaves: a 10 ms task computes a value and it stays put until the next run.

Use a **Zero-Order Hold** where a continuous signal (a sensor) enters a discrete controller.

## Solvers

| Solver | Type | Use for |
|---|---|---|
| `auto` / `RK45` | variable step | the default; smooth, non-stiff models |
| `RK23` | variable step | low accuracy needs, quick |
| `DOP853` | variable step | high accuracy |
| `Radau`, `BDF`, `LSODA` | variable step, implicit | **stiff** models (very fast and very slow dynamics together) |
| `rk4` | fixed step | models that will become code; deterministic step size |
| `euler` | fixed step | the simplest method; matches simple embedded code |

Variable-step solvers pick their own step size from `rtol`/`atol`, up to `max_step`. They also stop
**exactly** at discontinuities that blocks announce (the time of a Step, the edges of a Pulse), so these are
captured accurately.

Fixed-step solvers use `step` everywhere. The step must divide every discrete sample time. If you don't set
it, Nervus picks one.

!!! note "Discontinuities and zero crossings"
    Switching *inside* a model (a Saturation hitting its limit, a Switch changing input) is not yet detected
    precisely. Variable-step solvers still handle it, but sometimes take many small steps. Zero-crossing
    detection is planned.

## Simulation loop

At each **major step** Nervus (1) computes all outputs, (2) logs them, (3) updates discrete states with a
sample hit, and (4) integrates the continuous states to the next major step. With a variable-step solver,
the major steps are the discrete sample hits and the breakpoints. The solver's own steps in between are
logged too.
