"""L0: turn an uploaded resume file into text plus layout signals."""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import pdfplumber
from docx import Document


MAX_PAGES = 10


class ParseError(ValueError):
    pass


@dataclass
class ParsedDocument:
    text: str
    page_count: int = 1
    hidden_text: list[str] = field(default_factory=list)  # suspicious white / tiny text
    source_type: str = "text"

    @property
    def char_count(self) -> int:
        return len(self.text.strip())


def _is_white(color) -> bool:
    if color is None:
        return False
    if isinstance(color, (int, float)):
        return color >= 0.95  # grayscale
    if isinstance(color, (list, tuple)):
        if len(color) == 1:
            return color[0] >= 0.95
        if len(color) == 3:
            return all(c >= 0.95 for c in color)
        if len(color) == 4:  # CMYK white
            return all(c <= 0.05 for c in color)
    return False


def parse_pdf(data: bytes) -> ParsedDocument:
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ParseError(f"Could not open PDF: {exc}") from exc
    texts, hidden = [], []
    with pdf:
        if len(pdf.pages) > MAX_PAGES:
            raise ParseError(f"Resume has {len(pdf.pages)} pages; the limit is {MAX_PAGES}.")
        for page in pdf.pages:
            texts.append(page.extract_text() or "")
            run: list[str] = []
            for ch in page.chars:
                suspicious = _is_white(ch.get("non_stroking_color")) or ch.get("size", 10) < 4
                off_page = ch["x0"] < 0 or ch["x1"] > page.width or ch["top"] < 0 or ch["bottom"] > page.height
                if suspicious or off_page:
                    run.append(ch["text"])
                elif run:
                    hidden.append("".join(run))
                    run = []
            if run:
                hidden.append("".join(run))
        page_count = len(pdf.pages)
    hidden = [h.strip() for h in hidden if len(h.strip()) >= 3]
    return ParsedDocument(text="\n".join(texts), page_count=page_count, hidden_text=hidden, source_type="pdf")


def parse_docx(data: bytes) -> ParsedDocument:
    try:
        doc = Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ParseError(f"Could not open DOCX: {exc}") from exc
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(c.text for c in row.cells))
    text = "\n".join(parts)
    # rough page estimate: ~550 words per page
    pages = max(1, round(len(text.split()) / 550 + 0.49))
    return ParsedDocument(text=text, page_count=pages, source_type="docx")


def parse_resume(filename: str, data: bytes) -> ParsedDocument:
    name = (filename or "").lower()
    if not data:
        raise ParseError("The uploaded file is empty.")
    if data[:4] == b"%PDF":
        return parse_pdf(data)
    if name.endswith(".pdf"):
        raise ParseError("This file is named .pdf but is not a valid PDF.")
    if name.endswith(".docx"):
        if data[:2] != b"PK":
            raise ParseError("This file is named .docx but is not a valid Word document.")
        return parse_docx(data)
    if name.endswith((".txt", ".md")):
        if b"\x00" in data[:4096]:
            raise ParseError("This text file looks binary.")
        text = data.decode("utf-8", errors="replace")
        return ParsedDocument(text=text, page_count=max(1, round(len(text.split()) / 550 + 0.49)))
    raise ParseError("Unsupported file type. Upload a PDF, DOCX or TXT resume.")
