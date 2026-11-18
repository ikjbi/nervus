# Test cases and the Data Inspector

A **test case** is a reproducible simulation saved with the model: input signals, parameter overrides or
a parameter set (calibration), a stop time, and **checks** that decide pass/fail.

## Test Manager

Open the **Test Manager** tab next to Diagnostics.

- **New / Edit…** opens the test case editor.
- **Run selected / Run all** runs tests in the background (⌘T / Ctrl+T runs all).
- ✓ / ✗ shows the outcome. *Details* says which check failed and why.
- Double-click a result to see it in the Data Inspector.

Test cases are part of the model: they are saved with it, and editing them can be undone.

## Inputs

Each top-level In block gets a row. Enter `time: value` pairs, e.g. `0: 5, 0.2: 60, 1.2: 20`.
`hold` makes steps, `linear` makes ramps. Leave the row empty to use the block's own value.

## Checks

| Check | Arguments | Passes when |
|---|---|---|
| bounds | lower, upper, t_from, t_to | the signal stays within the bounds |
| final_value | value, tolerance | the last value is value ± tolerance |
| reaches | value, before, direction=below | the value is reached before the time |
| max / min | value | the maximum / minimum respects the value |
| baseline | path, tolerance | the signal matches a saved result |

Write arguments as `name=value, name=value`. Signals use result names such as `ECU/throttle_pi`.

## Data Inspector

**Simulation → Data Inspector** (⌘I / Ctrl+I) lists the recent runs, including test results. Check runs
and signals to overlay them; with two runs it shows the largest difference, and *Difference to first run*
plots the deviation. *Save run…* creates a baseline file for `baseline` checks; *Export* writes CSV or `.mat`.
