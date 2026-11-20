"""Code ▸ Export FMU from the editor."""

from pathlib import Path

import pytest

from nervus.codegen.sil import find_compiler

pytest.importorskip("fmpy")
EXAMPLES = Path(__file__).parent.parent.parent / "examples"


@pytest.mark.skipif(find_compiler() is None, reason="no C compiler")
def test_export_from_the_editor(window, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from fmpy.validation import validate_fmu

    window.files.open(EXAMPLES / "throttle_ecu.nervus")
    window.scene.select_blocks(["ECU"])
    out = window.export_fmu(str(tmp_path / "ecu.fmu"))
    assert out is not None and validate_fmu(str(out)) == []
