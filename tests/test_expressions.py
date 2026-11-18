import math

import numpy as np
import pytest

from nervus.core.expressions import format_value, parse_value


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2", 2.0),
        ("-1.5e3", -1500.0),
        ("2*pi", 2 * math.pi),
        ("1/0.05", 20.0),
        ("inf", math.inf),
        ("-inf", -math.inf),
        ("sqrt(4)", 2.0),
        ("[1, 2, 3]", [1.0, 2.0, 3.0]),
        ("[1 2 3]", [1.0, 2.0, 3.0]),
        ("[1 2; 3 4]", [[1.0, 2.0], [3.0, 4.0]]),
        ("[[1, 0], [0, 1]]", [[1.0, 0.0], [0.0, 1.0]]),
        ("[-1 -2]", [-1.0, -2.0]),
        ("[0.1, 0.05]", [0.1, 0.05]),
    ],
)
def test_parse(text: str, expected: object) -> None:
    assert parse_value(text) == expected


@pytest.mark.parametrize("text", ["", "__import__('os')", "open('x')", "1 +", "x", "1/0", "lambda: 1"])
def test_reject(text: str) -> None:
    with pytest.raises(ValueError):
        parse_value(text)


@pytest.mark.parametrize("value", [1.0, 0.5, math.inf, -math.inf, [1.0, 2.5], [[1.0, 2.0], [3.0, 4.0]]])
def test_roundtrip(value: object) -> None:
    assert parse_value(format_value(value)) == value


def test_format_array() -> None:
    assert format_value(np.array([[1.0, 2.0], [3.0, 4.0]])) == "[1.0 2.0; 3.0 4.0]"
