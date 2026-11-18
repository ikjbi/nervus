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
