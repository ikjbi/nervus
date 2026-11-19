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

From Python: `nervus.analysis.linearize`, `trim` and `LinearModel.bode()` / `.margins()`.
