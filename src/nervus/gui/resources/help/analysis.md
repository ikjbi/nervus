# Linear analysis

**Analysis → Linear Analysis…** (⌘L / Ctrl+L) linearizes the model from a top-level **In** block to an
**Out** block.

1. Add an In block where the input of the system is (e.g. the throttle command) and an Out block at the
   output (e.g. engine speed).
2. Choose the operating point: the **initial states**, or the **steady state** (trim) for the In blocks'
   values.
3. Press **Linearize**.

You get the transfer function, the poles (and whether the system is stable), the DC gain, a **Bode plot**,
the **gain and phase margins**, and the step response.

The margins treat G(s) as the *open loop* of a unity-feedback system. To analyse a control loop, put the In
block at the controller input (the error), the Out block at the plant output, and leave the loop open.
A rule of thumb for a robust loop: a phase margin of at least 45° and a gain margin of at least 6 dB.

The **Step response** tab shows G and the closed loop G / (1 + G). **Nyquist** draws G(jω) (solid for
positive, dashed for negative frequencies): for a stable open loop, the closed loop is stable when the curve
does not encircle −1. **Root locus** shows the closed-loop poles of k·G(s) as k grows from 0: from the
open-loop poles (×) to the zeros (○) or infinity.

## PID tuning

The **PID Tuning** tab needs no In or Out blocks. Choose a PID Controller (or Discrete PID) block, PI or PID,
and a phase margin, then press **Tune**. Nervus opens the loop at the block's output, linearizes the plant
the controller sees, and shapes the loop: a PI has its zero at ωc/4 (Ti = 4/ωc), a PID also a derivative with
Td = Ti/4 filtered at 10·ωc. It picks the fastest crossover ωc that keeps the phase margin, at least 6 dB gain
margin and a stable closed loop, limited to 2π/(20·Ts) for a discrete controller; spare margin is used for
faster integral action. The plot compares the closed-loop step responses with the current and tuned gains.

**Apply to Block** writes the gains; a gain given as a workspace variable (`P = Kp`) changes the variable. The
tuned gains are a robust starting point. Discrete blocks with state (filters, delays) cut the loop while the
plant is linearized.

From Python: `nervus.analysis.linearize`, `trim`, `LinearModel.bode()` / `.margins()` / `.nyquist()` /
`.root_locus()`, and `plant_at` + `tune_pid` for PID tuning.
