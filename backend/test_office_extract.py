"""Checks for the stdlib OOXML extractors and the unlimited-extraction contract.

The fixtures are hand-built ZIP archives rather than files produced by a library,
so these tests pin the actual XML shapes the parsers claim to handle: shared
strings, inline strings, formula cells, multi-run text, speaker notes, and
double-digit slide ordering.
"""

import io
import zipfile

import office_extract


def build_archive(members: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in members.items():
            archive.writestr(name, body)
    return buffer.getvalue()


# --- docx ------------------------------------------------------------------

DOCX = build_archive(
    {
        "word/document.xml": """<?xml version="1.0"?>
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:body>
            <w:p><w:r><w:t>Moat analysis</w:t></w:r></w:p>
            <w:p><w:r><w:t>Pricing power is </w:t></w:r><w:r><w:t>durable.</w:t></w:r></w:p>
            <w:p><w:r><w:t>   </w:t></w:r></w:p>
          </w:body>
        </w:document>""",
    }
)

text, meta = office_extract.extract_docx(DOCX)
assert "Moat analysis" in text
assert "Pricing power is durable." in text, "runs inside one paragraph must join"
assert meta["paragraphs"] == 2, "the whitespace-only paragraph should be dropped"
assert meta["truncated"] is False
assert meta["extractor"] == "docx-xml"


# --- xlsx ------------------------------------------------------------------

XLSX = build_archive(
    {
        "xl/workbook.xml": """<?xml version="1.0"?>
        <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
          <sheets><sheet name="Positions"/><sheet name="Notes"/></sheets>
        </workbook>""",
        "xl/sharedStrings.xml": """<?xml version="1.0"?>
        <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
          <si><t>Ticker</t></si>
          <si><t>Weight</t></si>
          <si><t>NVDA</t></si>
          <si><t>Split </t><t>run</t></si>
        </sst>""",
        "xl/worksheets/sheet1.xml": """<?xml version="1.0"?>
        <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
          <sheetData>
            <row><c t="s"><v>0</v></c><c t="s"><v>1</v></c></row>
            <row><c t="s"><v>2</v></c><c><v>0.084</v></c></row>
            <row><c t="inlineStr"><is><t>MSFT</t></is></c><c t="str"><v>0.061</v></c></row>
            <row><c/><c/></row>
            <row><c t="s"><v>3</v></c></row>
          </sheetData>
        </worksheet>""",
        "xl/worksheets/sheet2.xml": """<?xml version="1.0"?>
        <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
          <sheetData><row><c t="inlineStr"><is><t>Rebalanced in March</t></is></c></row></sheetData>
        </worksheet>""",
    }
)

text, meta = office_extract.extract_xlsx(XLSX)
assert "[Sheet: Positions]" in text and "[Sheet: Notes]" in text
assert "Ticker\tWeight" in text, "shared strings must resolve by index"
assert "NVDA\t0.084" in text, "numeric cells must survive"
assert "MSFT\t0.061" in text, "inline and formula-result cells must survive"
assert "Split run" in text, "multi-run shared strings must join"
assert "Rebalanced in March" in text, "every sheet must be read, not just the first"
assert meta["sheets"] == 2
assert meta["rows"] == 5, f"empty rows should be skipped, got {meta['rows']}"
assert meta["truncated"] is False

# A workbook with no sharedStrings.xml must not raise.
bare = build_archive(
    {
        "xl/worksheets/sheet1.xml": """<?xml version="1.0"?>
        <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
          <sheetData><row><c><v>42</v></c></row></sheetData>
        </worksheet>""",
    }
)
text, meta = office_extract.extract_xlsx(bare)
assert "42" in text and meta["rows"] == 1

# A shared-string index pointing past the table must degrade to empty, not crash.
broken = build_archive(
    {
        "xl/sharedStrings.xml": """<?xml version="1.0"?>
        <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>only</t></si></sst>""",
        "xl/worksheets/sheet1.xml": """<?xml version="1.0"?>
        <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
          <sheetData><row><c t="s"><v>0</v></c><c t="s"><v>99</v></c></row></sheetData>
        </worksheet>""",
    }
)
text, _ = office_extract.extract_xlsx(broken)
assert "only" in text


# --- pptx ------------------------------------------------------------------

SLIDE_TEMPLATE = """<?xml version="1.0"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree>
    <p:sp><p:txBody><a:p><a:r><a:t>{title}</a:t></a:r></a:p>
      <a:p><a:r><a:t>{body}</a:t></a:r></a:p></p:txBody></p:sp>
  </p:spTree></p:cSld>
</p:sld>"""

NOTES_TEMPLATE = """<?xml version="1.0"?>
<p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
         xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree><p:sp><p:txBody>
    <a:p><a:r><a:t>{note}</a:t></a:r></a:p>
  </p:txBody></p:sp></p:spTree></p:cSld>
</p:notes>"""

members = {
    f"ppt/slides/slide{n}.xml": SLIDE_TEMPLATE.format(title=f"Slide {n} title", body=f"Body {n}")
    for n in range(1, 11)
}
members["ppt/notesSlides/notesSlide1.xml"] = NOTES_TEMPLATE.format(note="Lead with the downside case")
PPTX = build_archive(members)

text, meta = office_extract.extract_pptx(PPTX)
assert meta["slides"] == 10
assert meta["notes"] == 1
assert "Slide 1 title" in text and "Body 1" in text
assert "Lead with the downside case" in text, "speaker notes carry the actual argument"
assert "[Slide 1 notes]" in text
# slide10 must come after slide9, which plain string sorting gets wrong.
assert text.index("Slide 9 title") < text.index("Slide 10 title")
assert meta["truncated"] is False


# --- The unlimited contract ------------------------------------------------

# max_chars=0 is the default and must never truncate.
big = build_archive(
    {
        "word/document.xml": "<?xml version='1.0'?><w:document "
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
        + "".join(f"<w:p><w:r><w:t>{'word ' * 200}</w:t></w:r></w:p>" for _ in range(200))
        + "</w:body></w:document>",
    }
)
text, meta = office_extract.extract_docx(big)
assert meta["truncated"] is False
assert len(text) > 150_000, f"unlimited extraction returned only {len(text)} characters"

# An explicit positive cap must still be honoured, and must say so.
text, meta = office_extract.extract_docx(big, max_chars=5_000)
assert meta["truncated"] is True
assert len(text) <= 5_200

for extractor, fixture in ((office_extract.extract_xlsx, XLSX), (office_extract.extract_pptx, PPTX)):
    _, unlimited_meta = extractor(fixture)
    assert unlimited_meta["truncated"] is False
    _, capped_meta = extractor(fixture, max_chars=20)
    assert capped_meta["truncated"] is True, f"{extractor.__name__} ignored an explicit cap"

# Negative and None-ish caps mean unlimited too.
assert office_extract._Budget(0).limit is None
assert office_extract._Budget(-1).limit is None
assert office_extract._Budget(10).limit == 10

print("OOXML extraction checks passed.")
