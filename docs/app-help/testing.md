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

## Test suites as files

**Export…** in the Test Manager saves the selected test cases (or all of them) to a `.nervtest` file, and
**Import…** adds the test cases of such a file to the open model. Use it to share a test suite between
model variants, or to keep the tests of a component in its own file next to the library.

## Test report

After a test run, **Report…** saves a self-contained HTML page with every test case, its parameters and every
check with its result, plus the model coverage when it was measured. It works in light and dark mode and can
be attached to a review or archived with a release.

```python
from nervus.testing import load_suite, run_tests, save_html_report, save_suite

save_suite(model.tests, "throttle_tests.nervtest")
results = run_tests(model, load_suite("throttle_tests.nervtest"))
save_html_report(results, "report.html", "Throttle controller tests")
```

## Parameter sweeps and Monte Carlo runs

To see how a design behaves over a range of parameters, or with production tolerances, run it many times
from Python and collect a few numbers (metrics) per run:

```python
from nervus.sweep import monte_carlo, sweep

# Every combination: 3 × 2 = 6 runs.
table = sweep(
    model,
    {"Kp_stft": [0.05, 0.1, 0.2], "n_exh": [8, 20]},  # the lambda control example
    metrics={"lambda_min": lambda r: r["lambda_cyl"].min()},
)
print(table.summary())

# Tolerances: 100 runs with random parameters (normal, uniform or choice). Here, for the lambda control
# example: injectors that deliver up to a few percent more or less fuel than their nominal flow.
table = monte_carlo(
    model,
    {"injector_error": ("normal", 0.0, 0.02), "tau_sensor": ("uniform", 0.08, 0.12)},
    runs=100,
    metrics={"ltft_end": lambda r: r["ECU/ltft_pct"][-1]},
    seed=1,
)
table.to_csv("monte_carlo.csv")  # one row per run: parameters, metrics, error
lowest = table.column("ltft_end").min()
```

A metric is any function of the result that returns one number. Runs that fail (for example a parameter
value that makes the model invalid) are kept with their error message, so they show up in the table.

## Data Inspector

**Simulation → Data Inspector** (⌘I / Ctrl+I) lists the recent runs, including test results. Check runs
and signals to overlay them; with two runs it shows the largest difference, and *Difference to first run*
plots the deviation. *Save run…* creates a baseline file for `baseline` checks; *Export* writes CSV or `.mat`.
