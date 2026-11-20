"""Requirements traceability: which blocks implement a requirement, and which test cases verify it.

    model.requirements.add(Requirement("IDLE-01", "Idle speed", "The engine idles at 800 ± 50 rpm when warm."))
    model.block("idle_controller").meta["requirements"] = ["IDLE-01"]   # or Diagram.link_requirement
    model.tests[0].requirements = ["IDLE-01"]
    for row in trace(model, results):   # results: test name -> passed
        print(row.requirement.id, row.status)

A requirement's **status**:

================== =================================================================
verified           it has test cases, and all of them passed in the last run
failed             at least one of its test cases failed
not run            it has test cases, but they have not been run
not tested         no test case is linked to it
not implemented    no block is linked to it
================== =================================================================

Requirements come from a requirements tool or a spreadsheet: :func:`read_csv` reads ``id, title, text, source``
columns (a header row names them), :func:`write_report` writes the traceability matrix as HTML.
"""

from __future__ import annotations

import csv
import html
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nervus.core.errors import ParameterError

if TYPE_CHECKING:
    from nervus.core.diagram import Diagram

META_KEY = "requirements"
"""``block.meta["requirements"]``: the ids of the requirements the block implements."""
STATUSES = ("verified", "failed", "not run", "not tested", "not implemented")


@dataclass
class Requirement:
    id: str
    title: str = ""
    text: str = ""
    source: str = ""
    """Where it comes from, e.g. a document and chapter, or a URL into the requirements tool."""

    def __post_init__(self) -> None:
        self.id = str(self.id).strip()
        if not self.id or any(c in self.id for c in ",;\n"):
            raise ParameterError(f"invalid requirement id {self.id!r}: it must not be empty or contain , ; or newlines")

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v or k == "id"}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Requirement:
        return cls(str(d["id"]), str(d.get("title", "")), str(d.get("text", "")), str(d.get("source", "")))


@dataclass
class Requirements:
    """The requirements of a model, in order, by id."""

    _items: dict[str, Requirement] = field(default_factory=dict)

    def __contains__(self, rid: object) -> bool:
        return rid in self._items

    def __iter__(self) -> Iterator[str]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, rid: str) -> Requirement:
        try:
            return self._items[rid]
        except KeyError:
            raise KeyError(f"no requirement {rid!r}") from None

    @property
    def items(self) -> list[Requirement]:
        return list(self._items.values())

    def add(self, req: Requirement) -> Requirement:
        self._items[req.id] = req
        return req

    def remove(self, rid: str) -> Requirement:
        return self._items.pop(rid)

    def copy(self) -> Requirements:
        return Requirements({k: Requirement(**v.__dict__) for k, v in self._items.items()})

    def to_list(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self._items.values()]

    @classmethod
    def from_list(cls, items: list[Mapping[str, Any]]) -> Requirements:
        reqs = cls()
        for d in items:
            reqs.add(Requirement.from_dict(d))
        return reqs


def block_links(diagram: Diagram) -> dict[str, list[str]]:
    """Requirement id → paths of the blocks linked to it."""
    out: dict[str, list[str]] = {}
    for path, b in diagram.walk():
        for rid in b.meta.get(META_KEY, []):
            out.setdefault(str(rid), []).append(path)
    return out


def test_links(diagram: Diagram) -> dict[str, list[str]]:
    """Requirement id → names of the test cases linked to it."""
    out: dict[str, list[str]] = {}
    for case in diagram.tests:
        for rid in getattr(case, "requirements", []):
            out.setdefault(str(rid), []).append(case.name)
    return out


@dataclass
class TraceRow:
    requirement: Requirement
    blocks: list[str]
    tests: list[str]
    status: str


def trace(diagram: Diagram, results: Mapping[str, bool] | None = None) -> list[TraceRow]:
    """The traceability matrix: every requirement with its blocks, tests and status. ``results`` maps test case
    names to passed (e.g. ``{r.case.name: r.passed for r in run_tests(model)}``)."""
    results = results or {}
    blocks, tests = block_links(diagram), test_links(diagram)
    rows = []
    for req in diagram.requirements.items:
        b, t = blocks.get(req.id, []), tests.get(req.id, [])
        if not b:
            status = "not implemented"
        elif not t:
            status = "not tested"
        elif any(results.get(name) is False for name in t):
            status = "failed"
        elif all(results.get(name) is True for name in t):
            status = "verified"
        else:
            status = "not run"
        rows.append(TraceRow(req, b, t, status))
    return rows


def unknown_links(diagram: Diagram) -> list[str]:
    """Messages for blocks and test cases linked to requirement ids that the model does not have."""
    known = diagram.requirements
    out = [f"block {p} is linked to unknown requirement {rid}" for rid, paths in block_links(diagram).items()
           if rid not in known for p in paths]  # fmt: skip
    out += [f"test case {n!r} is linked to unknown requirement {rid}" for rid, names in test_links(diagram).items()
            if rid not in known for n in names]  # fmt: skip
    return out


def read_csv(path: str | Path) -> list[Requirement]:
    """Requirements from a CSV file (comma or semicolon separated, as Excel writes it). A header row with
    ``id`` and optionally ``title``, ``text``, ``source`` (case-insensitive; also ``description`` for text) picks
    the columns; without one the columns are id, title, text, source."""
    raw = Path(path).read_text(encoding="utf-8-sig")
    dialect = csv.Sniffer().sniff(raw.splitlines()[0] if raw.strip() else ",", delimiters=",;\t")
    rows = [r for r in csv.reader(raw.splitlines(), dialect) if any(c.strip() for c in r)]
    if not rows:
        return []
    names = {"id": "id", "title": "title", "name": "title", "text": "text", "description": "text", "source": "source"}
    header = [names.get(c.strip().lower()) for c in rows[0]]
    if "id" in header:
        rows = rows[1:]
    else:
        header = ["id", "title", "text", "source"]
    out = []
    for r in rows:
        values = {k: r[i].strip() for i, k in enumerate(header) if k is not None and i < len(r)}
        if values.get("id"):
            out.append(Requirement(values["id"], values.get("title", ""), values.get("text", ""),
                                   values.get("source", "")))  # fmt: skip
    return out


def write_csv(diagram: Diagram, path: str | Path, results: Mapping[str, bool] | None = None) -> Path:
    """The traceability matrix as CSV (for spreadsheets and requirements tools)."""
    p = Path(path)
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "title", "text", "source", "blocks", "tests", "status"])
        for row in trace(diagram, results):
            r = row.requirement
            w.writerow([r.id, r.title, r.text, r.source, "; ".join(row.blocks), "; ".join(row.tests), row.status])
    return p


_COLORS = {"verified": "#1f8a4c", "failed": "#c0392b", "not run": "#8a6d1f", "not tested": "#8a6d1f",
           "not implemented": "#c0392b"}  # fmt: skip


def write_report(diagram: Diagram, path: str | Path, results: Mapping[str, bool] | None = None) -> Path:
    """The traceability matrix as an HTML page, with a summary by status."""
    rows = trace(diagram, results)
    counts = {s: sum(r.status == s for r in rows) for s in STATUSES}
    e = html.escape
    body = [f"<h1>Requirements traceability: {e(diagram.name)}</h1>",
            "<p>" + " · ".join(f'<b style="color:{_COLORS[s]}">{n}</b> {s}' for s, n in counts.items() if n) + "</p>",
            "<table><tr><th>Id</th><th>Requirement</th><th>Blocks</th><th>Test cases</th><th>Status</th></tr>"]  # fmt: skip
    for row in rows:
        r = row.requirement
        text = f"<b>{e(r.title)}</b><br>{e(r.text)}" + (f"<br><small>{e(r.source)}</small>" if r.source else "")
        tests = "<br>".join(e(n) + {True: " ✓", False: " ✗", None: ""}[(results or {}).get(n)] for n in row.tests)
        body.append(f"<tr><td>{e(r.id)}</td><td>{text}</td><td>{'<br>'.join(e(b) for b in row.blocks)}</td>"
                    f'<td>{tests}</td><td style="color:{_COLORS[row.status]}"><b>{row.status}</b></td></tr>')  # fmt: skip
    body.append("</table>")
    problems = unknown_links(diagram)
    if problems:
        body.append(
            "<h2>Links to unknown requirements</h2><ul>" + "".join(f"<li>{e(m)}</li>" for m in problems) + "</ul>"
        )
    style = (
        "body{font-family:system-ui,sans-serif;margin:2em;color:#222}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccc;padding:6px 8px;vertical-align:top;text-align:left}th{background:#f3f3f3}"
    )
    p = Path(path)
    p.write_text(f"<!doctype html><meta charset='utf-8'><title>Traceability: {e(diagram.name)}</title>"
                 f"<style>{style}</style>" + "\n".join(body), encoding="utf-8")  # fmt: skip
    return p
