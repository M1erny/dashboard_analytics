"""Focused checks for the Research Agent's canonical Markdown artifacts."""

import brain_agent
from brain_agent import DownloadedDocument, _canonical_markdown_document, _markdown_filename


document = DownloadedDocument(
    url="https://example.com/results.pdf",
    final_url="https://cdn.example.com/q4-results.pdf",
    filename="Q4 Results.pdf",
    extension=".pdf",
    mime_type="application/pdf",
    data=b"raw-pdf-bytes",
)

assert _markdown_filename(document.filename, document.extension) == "Q4 Results.md"

markdown = _canonical_markdown_document(
    document,
    title="Example Q4 Results",
    source_url=document.url,
    retrieved_at="2026-07-13T12:00:00+00:00",
    extracted_text="[Page 1]\nRevenue grew 10%.\n\n[Page 2]\nMargin expanded.",
    agent_task="Review results",
).decode("utf-8")

assert markdown.startswith("---\n")
assert 'original_extension: ".pdf"' in markdown
assert "resolved_url:" in markdown
assert "## Page 1" in markdown
assert "## Page 2" in markdown
assert "<https://example.com/results.pdf>" in markdown
assert "raw-pdf-bytes" not in markdown


class FakeStore:
    def __init__(self):
        self.metadata = None

    def get_file_source_by_identity(self, _identity):
        return None

    def counts(self):
        return {"sources": 1, "chunks": 1}

    def upsert_file_source(self, **kwargs):
        self.metadata = kwargs["metadata"]
        return {"id": 1, "title": kwargs["title"]}, True

    def add_chunks(self, _source_id, chunks):
        return chunks


class FakeDriveClient:
    upload = None

    def __init__(self, *, store):
        self.store = store

    def ensure_folder(self, parent_id, name):
        assert parent_id == "folder-id"
        assert name == "Agent Downloads"
        return {"id": "agent-downloads"}

    def upload_file(self, **kwargs):
        FakeDriveClient.upload = kwargs
        return {
            "id": "drive-file-id",
            "name": kwargs["name"],
            "mimeType": kwargs["mime_type"],
            "webViewLink": "https://drive.example/file",
        }


store = FakeStore()
real_drive_client = brain_agent.GoogleDriveClient
real_text_extractor = brain_agent.extract_drive_file_text
brain_agent.GoogleDriveClient = FakeDriveClient
brain_agent.extract_drive_file_text = lambda _data, _extension: ("[Page 1]\nRevenue grew 10%.", {"extractor": "test"})
try:
    result = brain_agent.import_document_into_brain(
        store,
        document,
        title="Example Q4 Results",
        upload_to_drive=True,
        drive_folder_id="folder-id",
    )
finally:
    brain_agent.GoogleDriveClient = real_drive_client
    brain_agent.extract_drive_file_text = real_text_extractor

assert result["document"]["convertedToMarkdown"] is True
assert FakeDriveClient.upload["name"] == "Q4 Results.md"
assert FakeDriveClient.upload["mime_type"] == "text/markdown; charset=utf-8"
assert FakeDriveClient.upload["data"].startswith(b"---\n")
assert store.metadata["originalExtension"] == ".pdf"
assert store.metadata["canonicalExtension"] == ".md"

print("Research Agent Markdown conversion checks passed.")
