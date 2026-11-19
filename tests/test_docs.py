"""Keep the GitHub docs and the in-app help complete and consistent."""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
HELP = ROOT / "src" / "nervus" / "gui" / "resources" / "help"
NAV = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")


def help_pages() -> set[str]:
    source = (ROOT / "src" / "nervus" / "gui" / "views" / "help_browser.py").read_text(encoding="utf-8")
    block = source[source.index("HELP_PAGES = [") : source.index("]", source.index("HELP_PAGES = ["))]
    return set(re.findall(r'\("([a-z_]+)",', block))


def test_every_help_file_is_in_the_help_window() -> None:
    files = {p.stem for p in HELP.glob("*.md")}
    assert files == help_pages(), f"missing in HELP_PAGES: {files - help_pages()}, no file: {help_pages() - files}"


def test_every_page_is_in_the_github_navigation() -> None:
    pages = [p.relative_to(ROOT / "docs").as_posix() for p in (ROOT / "docs").glob("*.md")]
    pages += [p.relative_to(ROOT / "docs").as_posix() for p in (ROOT / "docs" / "tutorials").glob("*.md")]
    pages += [f"app-help/{p.name}" for p in HELP.glob("*.md")]
    missing = [p for p in pages if p not in NAV]
    assert not missing, f"not in mkdocs.yml nav: {missing}"


def test_help_pages_have_no_broken_links() -> None:
    for page in HELP.glob("*.md"):
        text = page.read_text(encoding="utf-8")
        assert "](images/" not in text and "](../images/" not in text, f"{page.name}: screenshots are not bundled"
        links = re.findall(r"\]\((?!https?:|figures/)([^)]+)\)", text)
        assert not links, f"{page.name}: links to other files do not work in the app: {links}"
        for fig in re.findall(r"\]\(figures/([^)]+)\)", text):
            assert (ROOT / "src" / "nervus" / "gui" / "resources" / "figures" / fig).exists(), f"{page.name}: {fig}"


def test_every_example_is_documented() -> None:
    getting_started = (HELP / "getting_started.md").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "getting-started.md").read_text(encoding="utf-8")
    for model in (ROOT / "examples").glob("*.nervus"):
        assert model.name in getting_started, f"{model.name} missing in the in-app Getting started page"
        script = model.with_suffix(".py").name
        assert script in docs or model.stem in docs, f"{model.name} missing in docs/getting-started.md"
