# Logic and Bit Operations

## Relational Operator

`logic.relational` · Logic and Bit Operations

Compares input 0 with input 1: ``y = (u0 OP u1)``, giving 1 when true and 0 when false.

$$ y = \begin{cases} 1 & \text{if } u_0 \ \mathrm{op}\ u_1 \\ 0 & \text{otherwise} \end{cases} $$

Avoid ``==`` and ``!=`` on computed floating-point signals; compare against a tolerance instead.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `operator` | `'<='` |  | Comparison — one of `==`, `!=`, `<`, `<=`, `>`, `>=` |

*Direct feedthrough:* yes

---

## Compare To Constant

`logic.compare_to_constant` · Logic and Bit Operations

Compares the input with a constant: ``y = (u OP constant)``, 1 when true, 0 when false.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `operator` | `'>='` |  | Comparison — one of `==`, `!=`, `<`, `<=`, `>`, `>=` |
| `constant` | `0.0` |  | Constant to compare with |

*Direct feedthrough:* yes

---

## Logical Operator

`logic.logical` · Logic and Bit Operations

Boolean logic. Inputs are true when non-zero. The output is 1 (true) or 0 (false).

| operator | output is true when |
|---|---|
| AND | all inputs are true |
| OR | any input is true |
| NOT | the (single) input is false |
| XOR | an odd number of inputs is true |
| NAND | not all inputs are true |
| NOR | no input is true |

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `operator` | `'AND'` |  | Operation — one of `AND`, `OR`, `NOT`, `XOR`, `NAND`, `NOR` |
| `num_inputs` | `2` |  | Number of inputs (NOT has 1) |

*Direct feedthrough:* yes

---
