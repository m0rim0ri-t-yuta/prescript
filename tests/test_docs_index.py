"""Every file under docs/ is listed in docs/README.md (doc-update.md)."""

from __future__ import annotations

from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"


def test_every_doc_is_indexed() -> None:
    index = (DOCS / "README.md").read_text(encoding="utf-8")
    missing = [p.name for p in DOCS.glob("*.md") if p.name != "README.md" and p.name not in index]
    assert missing == [], f"add to docs/README.md: {missing}"
