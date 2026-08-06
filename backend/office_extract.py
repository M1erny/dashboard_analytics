"""Text extraction for OOXML office formats using only the standard library.

.docx, .xlsx and .pptx are ZIP archives of XML, so pulling their text needs
zipfile and ElementTree and nothing else. Keeping this dependency-free matters:
backend/requirements.txt is outside the self-build agent's write allowlist, so an
extractor that needs no new package is one the Brain can extend on its own later.

Every function takes `max_chars`, where 0 or less means "no limit". Unlimited is
the default here because a partly read document answers questions from the part
it happened to read, without ever saying so.
"""

import io
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
SHEET_NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
DRAWING_NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}

MAX_CELL_CHARS = 4000


def _open_archive(source: bytes | str | Path) -> zipfile.ZipFile:
    if isinstance(source, (bytes, bytearray)):
        return zipfile.ZipFile(io.BytesIO(source))
    return zipfile.ZipFile(source)


class _Budget:
    """Tracks a character allowance where 0 or less means unlimited."""

    def __init__(self, max_chars: int):
        self.limit = int(max_chars) if max_chars and max_chars > 0 else None
        self.used = 0
        self.truncated = False

    @property
    def exhausted(self) -> bool:
        return self.limit is not None and self.used >= self.limit

    def take(self, text: str) -> str | None:
        """Return as much of text as fits, or None when nothing fits."""
        if self.limit is None:
            self.used += len(text)
            return text
        remaining = self.limit - self.used
        if remaining <= 0:
            self.truncated = True
            return None
        if len(text) > remaining:
            self.truncated = True
            self.used = self.limit
            return text[:remaining]
        self.used += len(text)
        return text


def _sorted_parts(archive: zipfile.ZipFile, prefix: str, suffix: str = ".xml") -> list[str]:
    """Return archive members under prefix, ordered by their trailing number.

    slide10.xml must sort after slide9.xml, which plain string ordering gets wrong.
    """
    names = [
        name
        for name in archive.namelist()
        if name.startswith(prefix) and name.endswith(suffix) and "/_rels/" not in name
    ]

    def ordinal(name: str) -> tuple[int, str]:
        stem = name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        digits = "".join(character for character in stem if character.isdigit())
        return (int(digits) if digits else 0, name)

    return sorted(names, key=ordinal)


def extract_docx(source: bytes | str | Path, *, max_chars: int = 0) -> tuple[str, dict[str, Any]]:
    budget = _Budget(max_chars)
    paragraphs: list[str] = []

    with _open_archive(source) as archive:
        with archive.open("word/document.xml") as document:
            tree = ElementTree.parse(document)

    for paragraph in tree.findall(".//w:p", WORD_NS):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", WORD_NS)).strip()
        if not text:
            continue
        allowed = budget.take(text)
        if allowed is None:
            break
        paragraphs.append(allowed)

    return "\n\n".join(paragraphs), {
        "paragraphs": len(paragraphs),
        "extractor": "docx-xml",
        "truncated": budget.truncated,
        "maxExtractedChars": max_chars,
    }


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    with archive.open("xl/sharedStrings.xml") as handle:
        tree = ElementTree.parse(handle)
    strings: list[str] = []
    for item in tree.findall("s:si", SHEET_NS):
        # A styled cell splits its text across several <t> runs.
        strings.append("".join(node.text or "" for node in item.findall(".//s:t", SHEET_NS)))
    return strings


def _sheet_names(archive: zipfile.ZipFile) -> list[str]:
    if "xl/workbook.xml" not in archive.namelist():
        return []
    try:
        with archive.open("xl/workbook.xml") as handle:
            tree = ElementTree.parse(handle)
    except (KeyError, ElementTree.ParseError):
        return []
    return [str(sheet.get("name") or "") for sheet in tree.findall(".//s:sheets/s:sheet", SHEET_NS)]


def extract_xlsx(source: bytes | str | Path, *, max_chars: int = 0) -> tuple[str, dict[str, Any]]:
    """Flatten a workbook to tab-separated rows, one sheet after another."""
    budget = _Budget(max_chars)
    lines: list[str] = []
    rows_read = 0
    sheets_read = 0

    with _open_archive(source) as archive:
        strings = _shared_strings(archive)
        names = _sheet_names(archive)
        sheet_parts = _sorted_parts(archive, "xl/worksheets/sheet")

        for index, part in enumerate(sheet_parts):
            if budget.exhausted:
                break
            try:
                with archive.open(part) as handle:
                    tree = ElementTree.parse(handle)
            except (KeyError, ElementTree.ParseError):
                continue

            label = names[index] if index < len(names) else part.rsplit("/", 1)[-1]
            header = budget.take(f"[Sheet: {label}]")
            if header is None:
                break
            lines.append(header)
            sheets_read += 1

            for row in tree.findall(".//s:sheetData/s:row", SHEET_NS):
                values: list[str] = []
                for cell in row.findall("s:c", SHEET_NS):
                    values.append(_cell_text(cell, strings))
                if not any(value.strip() for value in values):
                    continue
                allowed = budget.take("\t".join(values).rstrip())
                if allowed is None:
                    break
                lines.append(allowed)
                rows_read += 1
            if budget.exhausted:
                break

    return "\n".join(lines), {
        "sheets": sheets_read,
        "rows": rows_read,
        "extractor": "xlsx-xml",
        "truncated": budget.truncated,
        "maxExtractedChars": max_chars,
    }


def _cell_text(cell: ElementTree.Element, strings: list[str]) -> str:
    cell_type = cell.get("t")
    if cell_type == "s":
        value = cell.find("s:v", SHEET_NS)
        if value is None or not (value.text or "").strip():
            return ""
        try:
            return strings[int(value.text)][:MAX_CELL_CHARS]
        except (ValueError, IndexError):
            return ""
    if cell_type == "inlineStr":
        inline = cell.find("s:is", SHEET_NS)
        if inline is None:
            return ""
        return "".join(node.text or "" for node in inline.findall(".//s:t", SHEET_NS))[:MAX_CELL_CHARS]
    if cell_type == "str":
        # A formula cell carries its cached result in <v>. The formula itself is
        # not the number the owner reads, so the cached value is what we keep.
        value = cell.find("s:v", SHEET_NS)
        return (value.text or "")[:MAX_CELL_CHARS] if value is not None else ""

    value = cell.find("s:v", SHEET_NS)
    return (value.text or "")[:MAX_CELL_CHARS] if value is not None else ""


def extract_pptx(source: bytes | str | Path, *, max_chars: int = 0) -> tuple[str, dict[str, Any]]:
    """Pull slide text and speaker notes, slide by slide."""
    budget = _Budget(max_chars)
    parts: list[str] = []
    slides_read = 0
    notes_read = 0

    with _open_archive(source) as archive:
        slide_parts = _sorted_parts(archive, "ppt/slides/slide")
        note_parts = {
            name.rsplit("/", 1)[-1].replace("notesSlide", "slide"): name
            for name in _sorted_parts(archive, "ppt/notesSlides/notesSlide")
        }

        for part in slide_parts:
            if budget.exhausted:
                break
            text = _drawing_text(archive, part)
            slide_number = slides_read + 1
            if text.strip():
                allowed = budget.take(f"[Slide {slide_number}]\n{text.strip()}")
                if allowed is None:
                    break
                parts.append(allowed)
            slides_read += 1

            note_part = note_parts.get(part.rsplit("/", 1)[-1])
            if not note_part:
                continue
            note_text = _drawing_text(archive, note_part)
            if not note_text.strip():
                continue
            allowed = budget.take(f"[Slide {slide_number} notes]\n{note_text.strip()}")
            if allowed is None:
                break
            parts.append(allowed)
            notes_read += 1

    return "\n\n".join(parts), {
        "slides": slides_read,
        "notes": notes_read,
        "extractor": "pptx-xml",
        "truncated": budget.truncated,
        "maxExtractedChars": max_chars,
    }


def _drawing_text(archive: zipfile.ZipFile, part: str) -> str:
    try:
        with archive.open(part) as handle:
            tree = ElementTree.parse(handle)
    except (KeyError, ElementTree.ParseError):
        return ""
    lines: list[str] = []
    for paragraph in tree.findall(".//a:p", DRAWING_NS):
        text = "".join(node.text or "" for node in paragraph.findall(".//a:t", DRAWING_NS)).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)
