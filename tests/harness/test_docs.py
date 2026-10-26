import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_technical_note_is_within_the_word_limit() -> None:  # covers: R19
    note = ROOT / "docs" / "TECHNICAL_NOTE.md"
    assert note.exists(), "docs/TECHNICAL_NOTE.md is a deliverable"
    words = re.findall(
        r"\b[\w'-]+\b", re.sub(r"```.*?```", "", note.read_text("utf-8"), flags=re.S)
    )
    assert len(words) <= 500, f"{len(words)} words"


def test_readme_documents_limitations_and_external_dependencies() -> None:  # covers: R20
    text = (ROOT / "README.md").read_text("utf-8")
    assert "## Limitations and external dependencies" in text
    for must in ("Claude Code", "not implemented", "Synthetic data"):
        assert must in text


def test_architecture_doc_has_diagrams() -> None:  # covers: R19
    text = (ROOT / "docs" / "ARCHITECTURE.md").read_text("utf-8")
    assert text.count("```mermaid") >= 2
