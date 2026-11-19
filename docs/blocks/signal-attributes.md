# Signal Attributes

## Data Type Conversion

`routing.datatype_conversion` · Signal Attributes

Converts the input to another data type, e.g. a sensor value to ``int16`` or a controller output to
fixed point.

![Converting a signal to int8 and to fixed point](../images/blocks/datatype_conversion.png)

The real-world value is kept as well as the type allows:

$$ Q = \mathrm{round}\left(\frac{u - \mathrm{bias}}{\mathrm{slope}}\right), \qquad y = \mathrm{slope} \cdot Q + \mathrm{bias} $$

*rounding*: ``nearest`` (half away from zero), ``floor``, ``ceil`` or ``zero`` (truncate). *overflow*:
``saturate`` limits to the type's range; ``wrap`` wraps around like C integer arithmetic. For example
``int8`` turns 3.6 into 4, and 200 into 127 (saturate) or -56 (wrap).

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `output_type` | `'int16'` |  | Output data type: inherit, double, single, boolean, int8…uint32, fixdt(signed, bits, fraction) |
| `rounding` | `'nearest'` |  | Rounding — one of `nearest`, `floor`, `ceil`, `zero` |
| `overflow` | `'saturate'` |  | Out-of-range values — one of `saturate`, `wrap` |

*Direct feedthrough:* yes

---
