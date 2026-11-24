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


def test_copy_examples(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:  # type: ignore[no-untyped-def]
    out = tmp_path / "ex"
    assert cli.main(["nervus", "--copy-examples", str(out)]) == 0
    assert (out / "cruise_control.nervus").exists() and (out / "cruise_control.py").exists()
    assert not list(out.rglob("__pycache__"))
    assert cli.main(["nervus", "--copy-examples", str(out)]) == 1  # not into a folder with files
    assert "not empty" in capsys.readouterr().err


def test_version_and_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["nervus", "--version"]) == 0 and capsys.readouterr().out.startswith("nervus ")
    assert cli.main(["nervus", "--help"]) == 0 and "--copy-examples" in capsys.readouterr().out
