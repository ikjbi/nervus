"""The tutorial registry: every tutorial has a page and models, and every topic is covered."""

from pathlib import Path

from nervus.tutorials import CATEGORIES, TUTORIALS, by_slug

ROOT = Path(__file__).parent.parent


def test_registry_is_consistent() -> None:
    slugs = by_slug()
    assert len(slugs) == len(TUTORIALS)
    cats = {c: {s for s, _ in subs} for c, _i, subs in CATEGORIES}
    for t in TUTORIALS:
        assert (ROOT / "docs" / "tutorials" / f"{t.slug}.md").exists(), t.slug
        assert (ROOT / "src/nervus/gui/resources/help" / f"{t.help_page}.md").exists(), t.help_page
        for m in t.models:
            assert (ROOT / "examples" / m).exists(), m
        assert t.subcategory in cats[t.category], (t.slug, t.subcategory)
        assert all(b in slugs for b in t.before), t.slug
        assert t.level in ("beginner", "intermediate", "advanced")
