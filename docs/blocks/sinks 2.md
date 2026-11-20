# Sinks

## Scope

`sinks.scope` · Sinks

Plots its input signals. In scripts, read the data with ``result.inputs("scope_name")``.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `num_inputs` | `1` |  | Number of inputs |

*Direct feedthrough:* no · no outputs

---

## To Workspace

`sinks.to_workspace` · Sinks

Saves its input in the simulation result under *variable*, so ``result[variable]`` returns it.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `variable` | `'simout'` |  | Name in the result |

*Direct feedthrough:* no · no outputs

---

## Terminator

`sinks.terminator` · Sinks

Terminates an unused output, so the diagram has no unconnected-output warnings.

*Direct feedthrough:* no · no outputs

---

## Stop Simulation

`sinks.stop` · Sinks

Stops the simulation at the first major time step where the input is non-zero (true).

Use it to end a run when something happens, e.g. when the engine stalls or a test scenario is complete.
The result contains everything up to that point.

*Direct feedthrough:* no · no outputs

---

## Assertion

`sinks.assertion` · Sinks

Fails the simulation with an error if the input is zero (false) at a major time step.

Connect a condition that must always hold, e.g. ``engine_speed < 7000`` from a Compare To Constant block.
The error message names the block and the time.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `message` | `'assertion failed'` |  | Error message |

*Direct feedthrough:* no · no outputs

---
