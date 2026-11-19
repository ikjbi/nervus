# Model workspace and calibrations

Engine control software is **code plus calibration**: the same algorithm runs in many vehicles with
different numbers (gains, maps, limits). Nervus separates the two the same way.

## Workspace variables

The **Model Workspace** panel (next to Diagnostics) lists named variables stored with the model:

| Column | Meaning |
|---|---|
| Name | A Python-style name: letters, digits and `_`, e.g. `Kp`, `fuel_map` |
| Value | A number (`1.5`), a vector or matrix (`[1 2; 3 4]`) or an expression of variables above it (`Kp/Ti`) |
| Unit, Min, Max | Documentation, and range checks: a value outside [min, max] is reported in Diagnostics |
| Description | Free text |

Click **Add** to create a variable, then edit the cells. All changes can be undone.

## Using variables in blocks

Type a variable name or an expression into any numeric block parameter:

| Parameter | Value |
|---|---|
| Gain → gain | `Kp` |
| Discrete PID → I | `Kp/Ti` |
| Zero-Order Hold → sample_time | `Ts` |
| Gain → gain | `1/tau` |

The block shows the expression on the canvas. When a variable changes, every block that uses it updates.
Expressions are evaluated again each time the model is simulated. A variable that is still used by a block
cannot be deleted.

Expressions may use `+ - * / ** %`, the functions `sqrt`, `exp`, `log`, `sin`, `cos`, `abs` and the
constants `pi`, `e`, `inf`, `true` and `false`. Comparisons (`==`, `!=`, `<`, `<=`, `>`, `>=`) and `and`, `or`, `not` give 1 (true)
or 0 (false), so `Kp * (MODE == 2)` works. The MATLAB spellings `~=`, `&&`, `||` and `~` are accepted too.

## Parameter sets (calibrations)

A **parameter set** is a file (`.nervcal`) with values for some or all of the variables:

- **Save set…** writes the current values, e.g. `petrol.nervcal`.
- **Load set…** applies a file's values to the model (one undo step). Values for variables the model does
  not have are ignored and listed in the status bar.

Use them to switch between engine variants or calibration versions, or to share a tuning without changing
the model. The example `throttle_tight.nervcal` is a higher-gain calibration for `throttle_pi.nervus`.

## From Python

```python
from nervus import ParameterSet, load, simulate

d = load("examples/throttle_pi.nervus")
d.workspace["Kp"] = 2.0  # change a variable
res = simulate(d, params={"Ki": 60.0})  # override for one run only
d.workspace.apply(ParameterSet.load("examples/throttle_tight.nervcal").values)
ParameterSet.from_workspace(d.workspace, "my_tune").save("my_tune.nervcal")
```
