"""Checks that an imported filing keeps its original file next to the Markdown.

The Markdown is what the Brain retrieves from, but a PDF's financial tables do
not survive text extraction, so the untouched original is uploaded beside it and
linked from the front matter. Three things have to hold: the pair is findable,
the reading copy never costs us the indexed source, and the folder sync does not
index the same document a second time.
"""

import brain_agent
import drive_indexer
from brain_agent import DownloadedDocument, keeps_original_upload
from drive_indexer import AGENT_UPLOAD_PROPERTY, is_agent_managed_upload

PDF_BYTES = b"%PDF-1.4 pretend this is a half-year report"


class FakeStore:
    def __init__(self):
        self.sources = {}
        self.chunks = {}

    def get_file_source_by_identity(self, identity):
        return self.sources.get(identity)

    def upsert_file_source(self, *, title, body, tags, metadata, force=False):
        source = {"id": 1, "title": title, "body": body, "tags": tags, "metadata": metadata}
        self.sources[metadata["fileIdentity"]] = source
        return source, True

    def add_chunks(self, source_id, chunks):
        self.chunks[source_id] = chunks
        return chunks

    def counts(self):
        return {"sources": len(self.sources), "chunks": sum(len(c) for c in self.chunks.values())}


class FakeDrive:
    """Records uploads. fail_on names an app-property value that must blow up."""

    instances = []

    def __init__(self, store=None, fail_on=None):
        self.store = store
        self.uploads = []
        self.fail_on = fail_on
        FakeDrive.instances.append(self)

    def ensure_folder(self, parent_id, name):
        return {"id": f"{parent_id}/{name}"}

    def upload_file(self, *, name, data, mime_type, folder_id=None, description=None, app_properties=None):
        kind = (app_properties or {}).get(AGENT_UPLOAD_PROPERTY)
        if self.fail_on and kind == self.fail_on:
            raise RuntimeError("Google said no")
        self.uploads.append({
            "name": name,
            "data": data,
            "mimeType": mime_type,
            "folderId": folder_id,
            "appProperties": app_properties,
        })
        return {
            "id": f"drive-{len(self.uploads)}",
            "name": name,
            "mimeType": mime_type,
            "webViewLink": f"https://drive.google.com/file/d/drive-{len(self.uploads)}/view",
        }


def run_import(*, extension=".pdf", mime_type="application/pdf", fail_on=None, **kwargs):
    FakeDrive.instances = []
    document = DownloadedDocument(
        url="https://espiebi.pap.pl/download/attachment/735217/report" + extension,
        final_url="https://espiebi.pap.pl/download/attachment/735217/report" + extension,
        filename="WAWEL raport polroczny" + extension,
        extension=extension,
        mime_type=mime_type,
        data=PDF_BYTES,
    )
    real_client, real_folder, real_extract = (
        brain_agent.GoogleDriveClient,
        brain_agent.parse_drive_folder_id,
        brain_agent.extract_drive_file_text,
    )
    brain_agent.GoogleDriveClient = lambda store=None: FakeDrive(store=store, fail_on=fail_on)
    brain_agent.parse_drive_folder_id = lambda value=None: value or "root-folder"
    brain_agent.extract_drive_file_text = lambda data, ext, **_: (
        "WYBRANE DANE FINANSOWE\nPrzychody netto 302 427,00", {"extraction": "fake"}
    )
    try:
        result = brain_agent.import_document_into_brain(FakeStore(), document, **kwargs)
    finally:
        brain_agent.GoogleDriveClient = real_client
        brain_agent.parse_drive_folder_id = real_folder
        brain_agent.extract_drive_file_text = real_extract
    return result, (FakeDrive.instances[0] if FakeDrive.instances else None)


# --- which formats keep an original -----------------------------------------
for extension in (".pdf", ".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt"):
    assert keeps_original_upload(extension), extension
    assert keeps_original_upload(extension.upper()), extension
for extension in (".html", ".htm", ".txt", ".md", ".csv", ".json", ""):
    # The Markdown is strictly more readable than these, so a copy buys nothing.
    assert not keeps_original_upload(extension), extension


# --- the happy path: two files, same stem, linked ---------------------------
result, drive = run_import()
assert len(drive.uploads) == 2, drive.uploads
original, markdown = drive.uploads
assert original["name"] == "WAWEL raport polroczny.pdf", original["name"]
assert markdown["name"] == "WAWEL raport polroczny.md", markdown["name"]
# Same stem so the two sort next to each other in the Drive folder listing.
assert original["name"][:-4] == markdown["name"][:-3]
assert original["data"] == PDF_BYTES, "the original must be byte-identical"
assert original["mimeType"] == "application/pdf"
assert original["appProperties"] == {AGENT_UPLOAD_PROPERTY: "original"}
assert markdown["appProperties"] == {AGENT_UPLOAD_PROPERTY: "markdown"}
assert original["folderId"] == markdown["folderId"] == "root-folder/Agent Downloads"

# The original goes up first precisely so the Markdown can point at it.
body = markdown["data"].decode("utf-8")
assert "original_file_drive_url" in body, body[:400]
assert "https://drive.google.com/file/d/drive-1/view" in body, body[:600]
assert "- Original file kept on Drive:" in body

metadata = result["source"]["metadata"]
assert metadata["originalKept"] is True
assert metadata["originalDriveFileId"] == "drive-1"
assert metadata["originalWebViewLink"].endswith("/drive-1/view")
assert metadata["originalUploadError"] is None
assert metadata["driveFileId"] == "drive-2", "the indexed artifact stays the Markdown"
assert result["document"]["original"]["keptOnDrive"] is True
assert result["document"]["original"]["bytes"] == len(PDF_BYTES)
assert result["status"] == "indexed"
assert result["chunks"], "the text must still be chunked and indexed"


# --- losing the reading copy must not lose the source ----------------------
result, drive = run_import(fail_on="original")
assert len(drive.uploads) == 1, "only the Markdown should have gone up"
assert drive.uploads[0]["appProperties"] == {AGENT_UPLOAD_PROPERTY: "markdown"}
assert result["status"] == "indexed", "a failed convenience copy must not fail the import"
metadata = result["source"]["metadata"]
assert metadata["originalKept"] is False
assert "Google said no" in metadata["originalUploadError"]
assert "original_file_drive_url" not in drive.uploads[0]["data"].decode("utf-8")

# --- losing the Markdown is fatal, because that is the indexed artifact ----
try:
    run_import(fail_on="markdown")
except RuntimeError as exc:
    assert "file-write permission" in str(exc), exc
else:
    raise AssertionError("a failed Markdown upload must raise")

# --- opting out, and formats that never keep one --------------------------
result, drive = run_import(keep_original=False)
assert len(drive.uploads) == 1 and result["document"]["original"]["keptOnDrive"] is False

result, drive = run_import(extension=".html", mime_type="text/html")
assert len(drive.uploads) == 1, "HTML keeps no second copy"

result, drive = run_import(upload_to_drive=False)
# No Drive client is even constructed when the caller does not want an upload.
assert drive is None, drive
assert result["document"]["original"]["keptOnDrive"] is False
assert result["source"]["metadata"]["driveFileId"] is None if "driveFileId" in result["source"]["metadata"] else True


# --- the folder sync must not index these a second time -------------------
assert is_agent_managed_upload({"name": "x.pdf", "appProperties": {AGENT_UPLOAD_PROPERTY: "original"}})
assert is_agent_managed_upload({"name": "x.md", "appProperties": {AGENT_UPLOAD_PROPERTY: "markdown"}})
# Uploads made before the property existed are caught by the folder name.
assert is_agent_managed_upload({"relativePath": "Agent Downloads/WAWEL raport.md"})
assert is_agent_managed_upload({"relativePath": "Research/agent downloads/deep/x.pdf"})
# A document the owner put in Drive by hand is still indexed.
assert not is_agent_managed_upload({"relativePath": "Filings/WAWEL raport.pdf"})
assert not is_agent_managed_upload({"name": "notes.md", "relativePath": "notes.md"})
# A file merely *named* like the folder is not in it.
assert not is_agent_managed_upload({"relativePath": "Agent Downloads.pdf"})
assert not is_agent_managed_upload({"name": "x.pdf", "appProperties": {AGENT_UPLOAD_PROPERTY: " "}})
assert not is_agent_managed_upload({"name": "x.pdf", "appProperties": "not-a-dict"})

# The sync's file listing has to ask Google for appProperties, or the exact
# signal above is invisible and only the folder-name fallback ever fires.
import inspect
assert "appProperties" in inspect.getsource(drive_indexer.GoogleDriveClient.list_children)

print("Agent original-upload checks passed.")
