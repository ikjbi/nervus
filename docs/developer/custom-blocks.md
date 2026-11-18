# Writing a block

A block is a subclass of `nervus.core.Block`. Here is a first-order low-pass filter
$\tau \dot x = u - x,\ y = x$:

```python
from collections.abc import Sequence

import numpy as np

from nervus.blocks import register
from nervus.core import CONTINUOUS, Block, Param, ParameterError, ParamKind
from nervus.core.types import Array


@register
class LowPass(Block):
    """First-order low-pass filter with time constant *tau*: ``tau·y' = u - y``."""

    type_id = "mylib.low_pass"  # stable id used in model files
    label = "Low-Pass Filter"
    category = "My Blocks"
    DEFAULT_SAMPLE_TIME = CONTINUOUS
    DIRECT_FEEDTHROUGH = False  # y depends only on the state
    PARAMS = (
        Param("tau", 0.1, ParamKind.FLOAT, "Time constant", "s", min=0.0),
        Param("initial", 0.0, ParamKind.FLOAT, "Initial output"),
    )

    def validate_params(self) -> None:
        if self.params["tau"] <= 0:
            raise ParameterError("tau must be > 0")

    def initial_continuous_state(self) -> Array:
        return np.full(self.out_widths[0], self.params["initial"])

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [xc.copy()]

    def derivatives(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        return (u[0] - xc) / self.params["tau"]
```

## Checklist

- **Pure functions.** Never store simulation state on `self`. Use `xc` (continuous) or `xd` (discrete).
- **Direct feedthrough**: set `DIRECT_FEEDTHROUGH = False` only if `outputs` does not read `u`. Getting this
  wrong breaks the execution order.
- **Widths**: override `output_widths` if the output width is not "broadcast of the inputs". Override
  `configure` to validate widths, and raise `ValueError` with a clear message.
- **Discrete blocks** need a `sample_time` parameter (`ParamKind.SAMPLE_TIME`) and implement `update`.
- **Discontinuities**: return their times from `breakpoints()` (like Step) so variable-step solvers hit them.
- **Ports**: set `NUM_INPUTS`/`NUM_OUTPUTS`, or override `num_inputs()`/`num_outputs()` if they depend on
  parameters.
- **Docs**: the class docstring is the help text. Describe the equation, ports and parameters.
- **Tests**: check against an analytical solution.
