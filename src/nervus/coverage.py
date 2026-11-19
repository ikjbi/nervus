"""Model coverage: which decision outcomes of a model were exercised by simulations or test cases.

Every block that makes a decision lists its possible *outcomes* (a Switch passes input 0 or input 2; a
comparison is true or false; a saturation is below, within or above its limits; a chart is in each state and
takes each transition; a lookup table uses each interval). During a simulation the outcomes that occur are
counted. Coverage is the fraction of outcomes that occurred at least once. Missed outcomes show which
situations the tests never reach, typically a missing test case.

    from nervus.coverage import Coverage
    from nervus.testing import run_tests

    cov = Coverage()
    run_tests(model, coverage=cov)
    print(cov.percent, cov.missed())
    cov.save_html("coverage.html")
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BlockCoverage:
    path: str
    block_type: str
    counts: dict[str, int]

    @property
    def covered(self) -> int:
        return sum(1 for c in self.counts.values() if c > 0)

    @property
    def total(self) -> int:
        return len(self.counts)

    @property
    def missed(self) -> list[str]:
        return [o for o, c in self.counts.items() if c == 0]


@dataclass
class Coverage:
    blocks: dict[str, BlockCoverage] = field(default_factory=dict)
    runs: int = 0

    def register(self, path: str, block_type: str, outcomes: list[str]) -> BlockCoverage:
        bc = self.blocks.get(path)
        if bc is None:
            bc = self.blocks[path] = BlockCoverage(path, block_type, {o: 0 for o in outcomes})
        for o in outcomes:
            bc.counts.setdefault(o, 0)
        return bc

    def hit(self, path: str, outcomes: list[str]) -> None:
        bc = self.blocks[path]
        for o in outcomes:
            bc.counts[o] = bc.counts.get(o, 0) + 1

    @property
    def covered(self) -> int:
        return sum(b.covered for b in self.blocks.values())

    @property
    def total(self) -> int:
        return sum(b.total for b in self.blocks.values())

    @property
    def percent(self) -> float:
        return 100.0 * self.covered / self.total if self.total else 100.0

    def missed(self) -> dict[str, list[str]]:
        return {p: b.missed for p, b in self.blocks.items() if b.missed}

    def summary(self) -> str:
        lines = [
            f"Decision coverage: {self.covered}/{self.total} outcomes ({self.percent:.0f} %) in {self.runs} run(s)"
        ]
        for path, missed in self.missed().items():
            lines.append(f"  {path}: never {', '.join(missed)}")
        return "\n".join(lines)

    def to_html(self, title: str = "Model coverage") -> str:
        rows = []
        for b in sorted(self.blocks.values(), key=lambda b: (b.covered == b.total, b.path)):
            pct = 100.0 * b.covered / b.total if b.total else 100.0
            cells = " ".join(
                f'<span class="{"hit" if c else "miss"}">{html.escape(o)}{f" ×{c}" if c else ""}</span>'
                for o, c in b.counts.items()
            )
            rows.append(
                f"<tr><td>{html.escape(b.path)}</td><td>{html.escape(b.block_type)}</td>"
                f'<td class="num">{pct:.0f} %</td><td>{cells}</td></tr>'
            )
        css = (
            "body{font-family:system-ui,sans-serif;margin:24px;color:#1d1d1b;background:#fcfcfb}"
            "table{border-collapse:collapse}td,th{border:1px solid #dcdbd5;padding:5px 8px;text-align:left;vertical-align:top}"
            ".num{text-align:right}.hit,.miss{display:inline-block;margin:2px;padding:1px 6px;border-radius:4px}"
            ".hit{background:#1baf7a22;border:1px solid #1baf7a}.miss{background:#e3494822;border:1px solid #e34948}"
            "@media (prefers-color-scheme: dark){body{background:#1a1a19;color:#f2f2ef}td,th{border-color:#353532}}"
        )
        return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>{css}</style></head><body><h1>{html.escape(title)}</h1>
<p><b>{self.percent:.0f} %</b> decision coverage: {self.covered} of {self.total} outcomes exercised in {self.runs} run(s).
Green outcomes occurred (×count); red ones never did.</p>
<table><tr><th>block</th><th>type</th><th>coverage</th><th>outcomes</th></tr>{"".join(rows)}</table></body></html>
"""

    def save_html(self, path: str | Path, title: str = "Model coverage") -> Path:
        p = Path(path)
        p.write_text(self.to_html(title), encoding="utf-8")
        return p
