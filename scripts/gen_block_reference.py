"""Regenerate docs/blocks/ from the block library. Run: uv run python scripts/gen_block_reference.py"""

from pathlib import Path

from nervus.help import reference_pages

OUT = Path(__file__).parent.parent / "docs" / "blocks"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.md"):
        old.unlink()
    for name, text in reference_pages().items():
        (OUT / name).write_text(text.rstrip() + "\n", encoding="utf-8")
    print(f"wrote {len(list(OUT.glob('*.md')))} pages to {OUT}")


if __name__ == "__main__":
    main()
