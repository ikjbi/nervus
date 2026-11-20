# User-Defined

## Python Function

`user.python_function` · User-Defined

Runs your own Python function, the equivalent of Simulink's MATLAB Function block.

*code* must define a function ``f(t, u0, u1, ...)`` with one argument per input. It returns one value per
output (a tuple if there are several). Values may be scalars or arrays. ``np`` (NumPy) and ``math`` are
available.

*parameters* is a vector of values the code reads as ``p[0]``, ``p[1]``, ... Like any numeric parameter it
can be an expression of workspace or mask variables, e.g. ``[eta_vol, displacement]``, so the same code can
be reused with different values (and calibrated).

The function must be *stateless*: its output may only depend on ``t`` and the inputs. Use Unit Delay or
Integrator blocks for memory.

!!! warning
    The code runs with full Python privileges. Only open model files from sources you trust.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `code` | *(code)* |  | Python source defining f(t, u0, ...) |
| `num_inputs` | `1` |  | Number of inputs |
| `num_outputs` | `1` |  | Number of outputs |
| `output_width` | `-1` |  | Width of each output (-1 = same as input 0, or 1) |
| `parameters` | `[]` |  | Values available in the code as p[0], p[1], ... |

*Direct feedthrough:* yes

---
