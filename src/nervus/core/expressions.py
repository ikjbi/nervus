"""Safe parsing of parameter values typed by users, e.g. in the GUI property editor.

Accepts numbers, arithmetic (``2*pi``, ``1/0.05``), ``inf``, ``pi``, ``e``, Python-style lists
(``[1, 2, 3]``, ``[[1, 0], [0, 1]]``) and MATLAB-style matrices (``[1 2; 3 4]``). Nothing is executed:
expressions are evaluated from the syntax tree with a small whitelist.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from collections.abc import Callable
from typing import Any

_NAMES = {"pi": math.pi, "e": math.e, "inf": math.inf, "Inf": math.inf, "nan": math.nan, "true": 1.0, "false": 0.0}
_BINOPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}
_FUNCS: dict[str, Callable[[Any], Any]] = {
    "sqrt": math.sqrt,
    "exp": math.exp,
    "log": math.log,
    "sin": math.sin,
    "cos": math.cos,
    "abs": abs,
}


def _matlab_to_python(text: str) -> str:
    """``[1 2; 3 4]`` -> ``[[1, 2], [3, 4]]``. Only applies to a single bracketed literal."""
    s = text.strip()
    if not (s.startswith("[") and s.endswith("]")) or s.count("[") != 1:
        return text
    body = s[1:-1].strip()
    if ";" not in body and "," in body:
        return text
    rows = [r.strip() for r in body.split(";")]
    py_rows = []
    for r in rows:
        items = [x for x in re.split(r"[,\s]+", r) if x]
        py_rows.append("[" + ", ".join(items) + "]")
    if ";" in body:
        return "[" + ", ".join(py_rows) + "]"
    return py_rows[0] if py_rows else "[]"


def _eval(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.Name) and node.id in _NAMES:
        return _NAMES[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        v = _eval(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.List | ast.Tuple):
        return [_eval(e) for e in node.elts]
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FUNCS
        and len(node.args) == 1
        and not node.keywords
    ):
        return _FUNCS[node.func.id](_eval(node.args[0]))
    raise ValueError(f"unsupported expression: {ast.unparse(node)}")


def parse_value(text: str) -> Any:
    """Parse ``text`` into a float or (nested) list of floats. Raises :class:`ValueError` if invalid."""
    text = text.strip()
    if not text:
        raise ValueError("value is empty")
    try:
        tree = ast.parse(_matlab_to_python(text), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"cannot parse {text!r}") from exc
    try:
        return _eval(tree)
    except ZeroDivisionError as exc:
        raise ValueError("division by zero") from exc


def format_value(value: Any) -> str:
    """Format a parameter value for display/editing, so that ``parse_value(format_value(v)) == v``."""
    import numpy as np

    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, float):
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return repr(value) if not value.is_integer() else str(value)
    if isinstance(value, list):
        if value and all(isinstance(r, list) for r in value):
            return "[" + "; ".join(" ".join(format_value(x) for x in r) for r in value) + "]"
        return "[" + ", ".join(format_value(x) for x in value) + "]"
    return str(value)
