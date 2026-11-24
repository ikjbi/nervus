"""The nervus command without the editor's packages explains how to install them."""

import builtins
from typing import Any

import pytest

from nervus import cli


def test_missing_pyside6_gives_instructions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "PySide6":
            raise ImportError("No module named 'PySide6'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert cli.main([]) == 1
    assert "uv sync --extra gui" in capsys.readouterr().err
