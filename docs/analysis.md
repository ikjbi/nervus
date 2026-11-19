# Linear analysis

Controller design starts from a linear model of the plant. **Analysis → Linear Analysis…** (⌘L / Ctrl+L)
linearizes the model from a top-level **In** block to an **Out** block and shows:

- the transfer function G(s), its poles and stability, and the DC gain,
- the **Bode plot** (magnitude and phase),
- the **gain and phase margins**, read as if G were the open loop of a unity-feedback system,
- the step response.

![Linear analysis of L(s) = 10 / (s (s+1) (0.1 s+1))](images/analysis.png)

Choose the operating point: the model's **initial states**, or the **steady state** (trim) for the In blocks'
values. Nonlinear models are linearized around that point with central differences.

## In Python

```python
from nervus import load
from nervus.analysis import linearize, trim

model = load("plant.nervus")  # with In and Out blocks
op = trim(model, {"throttle": 5.0})  # steady state for a constant input
lin = linearize(model, x0=op.x, u0=op.u)

lin.A, lin.B, lin.C, lin.D  # state-space matrices
num, den = lin.transfer_function()
lin.poles(), lin.dc_gain(), lin.is_stable()
w, mag_db, phase_deg = lin.bode()
m = lin.margins()  # m.gain_margin_db, m.phase_margin_deg, crossover frequencies
t, y = lin.step_response()
```

### Example: the tank

For a tank with level h, inflow q and outflow $k\sqrt h$:

$$ A \dot h = q - k \sqrt h $$

`trim` finds the level where inflow and outflow balance, $h_0 = (q/k)^2$. `linearize` gives the local
time constant $\tau = 2 A \sqrt{h_0} / k$: the tank reacts more slowly when it is fuller. The test suite
checks exactly this (`tests/test_analysis.py`).

## Limitations

- Inputs and outputs must be scalar; the model's continuous states are linearized and discrete blocks are
  held at their current outputs.
- Margins assume a single-input, single-output loop.
