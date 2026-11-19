# Verification: coverage and the Model Advisor

## Model coverage

Passing tests only say something if they exercise the model. **Model coverage** measures which *decision
outcomes* the tests reached:

| Block | Outcomes |
|---|---|
| Switch | input 0 passed, input 2 passed |
| Relational Operator, Compare To Constant, Logical Operator | true, false |
| Saturation, Dead Zone | below, within, above |
| Integrator, PID (with limits) | at upper limit, at lower limit, between limits |
| Relay | on, off |
| Rate Limiter | rising limited, falling limited, not limited |
| 1-D Lookup Table | each interval between breakpoints, below and above the range |
| State Chart | every state, every transition |

The **Test Manager** measures coverage on every run and shows it next to the buttons (*Coverage 50 %*).
**Coverage report** opens an HTML report listing every block with its outcomes, exercised (green, with
counts) or never reached (red). A red outcome usually means a missing test case. For example, the idle speed
example's tests never drive the controller to its upper limit, so no test checks full-throttle authority.

From Python:

```python
from nervus import load
from nervus.coverage import Coverage
from nervus.testing import run_tests

model = load("examples/idle_speed_control.nervus")
cov = Coverage()
run_tests(model, coverage=cov)
print(cov.summary())  # Decision coverage: 4/8 outcomes (50 %) ...
cov.save_html("coverage.html")
```

`simulate(model, coverage=cov)` measures a single run. One `Coverage` object can collect several runs.

## Model Advisor

**Analysis → Model Advisor** (⇧⌘A / Ctrl+Shift+A) checks the model for practices that often cause bugs in
ECU software. Click a finding to open the block.

| Rule | Checks for |
|---|---|
| `float-equality` | `==` / `!=` on floating-point signals |
| `division` | Product blocks that divide (possible division by zero) |
| `antiwindup` | PI controllers with output limits but no anti-windup, or an integral term without limits |
| `implicit-sampling` | discrete blocks that read a continuous signal without a Zero-Order Hold |
| `chart-unreachable` | chart states that can never become active |
| `chart-shadowed` | chart transitions that come after an always-true transition |
| `lookup-extrapolation` | lookup tables that extrapolate linearly beyond the calibrated range |
| `workspace-docs` | workspace variables without a unit or description (they end up in the A2L file) |
| `workspace-unused` | workspace variables no block uses |
| `default-names` | blocks inside subsystems that still have default names |

```python
from nervus.advisor import advise

for finding in advise(model):
    print(finding)
```
