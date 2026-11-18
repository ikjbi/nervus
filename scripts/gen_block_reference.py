"""Regenerate generated documentation. Run: uv run python scripts/gen_block_reference.py

- docs/blocks/: the block reference, from the block docstrings and parameter declarations
- docs/app-help/: copies of the in-app help pages (single source: src/nervus/gui/resources/help)
"""

import shutil
from pathlib import Path

from nervus.help import reference_pages

ROOT = Path(__file__).parent.parent
OUT = ROOT / "docs" / "blocks"
HELP_SRC = ROOT / "src" / "nervus" / "gui" / "resources" / "help"
HELP_OUT = ROOT / "docs" / "app-help"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.md"):
        old.unlink()
    for name, text in reference_pages().items():
        (OUT / name).write_text(text.rstrip() + "\n", encoding="utf-8")
    print(f"wrote {len(list(OUT.glob('*.md')))} pages to {OUT}")
    HELP_OUT.mkdir(parents=True, exist_ok=True)
    for page in HELP_SRC.glob("*.md"):
        shutil.copy(page, HELP_OUT / page.name)
    print(f"copied {len(list(HELP_SRC.glob('*.md')))} in-app help pages to {HELP_OUT}")


if __name__ == "__main__":
    main()
