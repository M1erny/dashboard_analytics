"""Attaching exact Drive files to a question, and the refactor that made it possible.

The per-file pipeline was lifted out of the folder sync so that a pasted link is
indexed byte for byte the way a synced file is. These checks drive both paths
through a fake Drive client and a real SQLite store: link parsing, the single-file
path's success, reuse and refusal cases, the folder loop after the refactor, and
how attached files enter the full-document context of one question.
"""

import asyncio
import os
import sys
import tempfile

import drive_indexer
from brain_store import BrainStore

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {detail}")
        FAILED.append(name)


TEXT = ("Oura sells a smart ring and a subscription. Gross margin, retention and churn drive the model. " * 60).encode()
FILE_ID = "19fZ1yF_XYGc7TfDK3uOnZPG4wWdqSL5m"


class FakeDrive:
    """Stands in for GoogleDriveClient. Scriptable metadata, counted downloads."""

    files: dict = {}
    downloads = 0
    get_error = None

    def __init__(self, store=None):
        self.store = store

    def get_file(self, file_id):
        if FakeDrive.get_error:
            raise FakeDrive.get_error
        return dict(FakeDrive.files[file_id])

    def download_file(self, file, *, max_bytes=None):
        FakeDrive.downloads += 1
        return TEXT, ".txt", {"downloadMode": "download"}

    def iter_files(self, folder_id, *, limit_files):
        return [dict(f, relativePath=f["name"]) for f in FakeDrive.files.values()]


def http_error(code):
    import httpx
    request = httpx.Request("GET", "https://www.googleapis.com/drive/v3/files/x")
    return httpx.HTTPStatusError("boom", request=request, response=httpx.Response(code, request=request))


def fresh_store():
    path = os.path.join(tempfile.mkdtemp(), "brain.db")
    return BrainStore(db_path=path)


saved_client = drive_indexer.GoogleDriveClient
drive_indexer.GoogleDriveClient = FakeDrive
try:
    print("\n=== Link parsing ===")
    cases = {
        f"https://drive.google.com/file/d/{FILE_ID}/view?usp=drive_link": FILE_ID,
        f"https://drive.google.com/file/u/1/d/{FILE_ID}/view": FILE_ID,
        "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456/edit": "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456",
        "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456/edit#gid=0": "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456",
        f"https://drive.google.com/open?id={FILE_ID}": FILE_ID,
        f"  {FILE_ID}  ": FILE_ID,
        "not a link": None,
        "": None,
        "https://example.com/file/d/short/view": None,
    }
    for value, expected in cases.items():
        check(f"parse {value[:48]!r}", drive_indexer.parse_drive_file_id(value) == expected, str(drive_indexer.parse_drive_file_id(value)))

    print("\n=== Attaching one file ===")
    FakeDrive.files = {FILE_ID: {"id": FILE_ID, "name": "Oura S-1 notes.txt", "mimeType": "text/plain", "size": str(len(TEXT)),
                                 "md5Checksum": "abc", "modifiedTime": "2026-09-20T10:00:00Z", "webViewLink": "https://drive/x",
                                 "parents": ["someOtherFolder"]}}
    store = fresh_store()
    FakeDrive.downloads = 0
    result = drive_indexer.index_single_drive_file(store, f"https://drive.google.com/file/d/{FILE_ID}/view")
    check("a file outside the Brain folder is indexed", result["status"] == "indexed" and result["sourceId"], str(result))
    source = store.get_file_source_by_identity(f"google-drive:{FILE_ID}")
    meta = (source or {}).get("metadata", {})
    check("with the same identity a folder sync would give it", source is not None and meta.get("driveFileId") == FILE_ID)
    check("recording where it lives and that it was attached directly", meta.get("driveFolderId") == "someOtherFolder" and meta.get("attachedDirectly") is True, str(meta.get("driveFolderId")))
    check("its text is chunked", len(store.list_chunks(source_id=source["id"], limit=50)) >= 1)

    again = drive_indexer.index_single_drive_file(store, FILE_ID)
    check("an unchanged file is returned, not downloaded again", again["status"] == "unchanged" and again["sourceId"] == result["sourceId"] and FakeDrive.downloads == 1, f"{again} downloads={FakeDrive.downloads}")
    FakeDrive.files[FILE_ID]["md5Checksum"] = "changed"
    changed = drive_indexer.index_single_drive_file(store, FILE_ID)
    check("a changed file is re-indexed into the same source", changed["status"] == "indexed" and changed["sourceId"] == result["sourceId"] and FakeDrive.downloads == 2, str(changed))
    forced = drive_indexer.index_single_drive_file(store, FILE_ID, force=True)
    check("force re-indexes even when unchanged", forced["status"] == "indexed" and FakeDrive.downloads == 3)

    def refusal(ref, *, files=None, error=None):
        FakeDrive.files = files if files is not None else FakeDrive.files
        FakeDrive.get_error = error
        try:
            drive_indexer.index_single_drive_file(fresh_store(), ref)
            return None, None
        except drive_indexer.DriveFileError as exc:
            return exc.status_code, str(exc)
        finally:
            FakeDrive.get_error = None

    code, text = refusal("nonsense")
    check("a non-link is refused with 400", code == 400, str(code))
    code, text = refusal(FILE_ID, error=http_error(404))
    check("a file Drive cannot find is 404, naming the sharing cause", code == 404 and "shared" in text, text)
    code, text = refusal(FILE_ID, error=http_error(403))
    check("a forbidden file is 403, saying how to fix it", code == 403 and "Share it" in text, text)
    code, _ = refusal(FILE_ID, files={FILE_ID: {"id": FILE_ID, "name": "Research", "mimeType": drive_indexer.FOLDER_MIME_TYPE}})
    check("a folder link is refused with 400", code == 400)
    code, _ = refusal(FILE_ID, files={FILE_ID: {"id": FILE_ID, "name": "photo.jpg", "mimeType": "image/jpeg"}})
    check("an unsupported type is 415", code == 415)
    code, text = refusal(FILE_ID, files={FILE_ID: {"id": FILE_ID, "name": "huge.pdf", "mimeType": "application/pdf", "size": str(10 ** 10)}})
    check("a file over the byte limit is 413, naming the setting", code == 413 and "BRAIN_DRIVE_MAX_BYTES" in text, text)

    print("\n=== The folder sync after the refactor ===")
    FakeDrive.files = {
        "a" * 25: {"id": "a" * 25, "name": "Annual report.txt", "mimeType": "text/plain", "size": "100", "md5Checksum": "1", "modifiedTime": "t"},
        "b" * 25: {"id": "b" * 25, "name": "slides.jpg", "mimeType": "image/jpeg"},
    }
    store = fresh_store()
    FakeDrive.downloads = 0
    run = drive_indexer.index_drive_folder(store, folder_id="c" * 25, limit_files=10, max_bytes=10 ** 7)
    by_name = {r["name"]: r for r in run["results"]}
    check("a supported file is indexed through the shared pipeline", by_name["Annual report.txt"]["status"] == "indexed" and by_name["Annual report.txt"]["chunks"] >= 1, str(by_name["Annual report.txt"]))
    check("an unsupported one is skipped as before", by_name["slides.jpg"]["reason"] == "unsupported file type")
    check("the summary still counts them", run["summary"]["indexed"] == 1 and run["summary"]["skipped"] == 1, str(run["summary"]))
    synced = store.get_file_source_by_identity("google-drive:" + "a" * 25)
    check("a synced file records the sync folder and is not marked attached",
          synced["metadata"].get("driveFolderId") == "c" * 25 and "attachedDirectly" not in synced["metadata"])
    rerun = drive_indexer.index_drive_folder(store, folder_id="c" * 25, limit_files=10, max_bytes=10 ** 7)
    check("a second sync skips the unchanged file without downloading", FakeDrive.downloads == 1 and {r["name"]: r for r in rerun["results"]}["Annual report.txt"]["reason"] == "unchanged")
finally:
    drive_indexer.GoogleDriveClient = saved_client

print("\n=== Attached files in one question's context ===")
import server

check("attached ids are cleaned, deduplicated and capped",
      server._clean_attached_source_ids([3, "4", 3, -1, "x", 0, 5, 6, 7, 8, 9, 10]) == [3, 4, 5, 6, 7, 8][:server.MAX_ATTACHED_SOURCES])
check("the request model accepts attachedSourceIds", "attachedSourceIds" in server.BrainCompanyAnalysisRequest.model_fields)

store = fresh_store()
ids = []
for title in ("Pinned framework", "Attached filing"):
    src = store.add_source(kind="document", title=title, body=title, tags=[], metadata={})
    from brain_ingestion import chunk_text
    store.add_chunks(src["id"], chunk_text((title + " body text ") * 200, source_title=title))
    ids.append(src["id"])
pinned = asyncio.run(server._load_reference_sources(store, [ids[0]]))
attached = asyncio.run(server._load_reference_sources(store, [ids[1]]))
for s_ in attached:
    s_["attachedToQuestion"] = True
docs = asyncio.run(server._build_full_document_context(store, attached + pinned))
check("an attached file is read in full, first", [d["sourceId"] for d in docs] == [ids[1], ids[0]], str([d["sourceId"] for d in docs]))
check("and marked as attached, the pinned one not", docs[0]["attached"] is True and docs[1]["attached"] is False)
prompt = server._format_full_document_context(docs)
check("the model is told the investor attached it to this question", "attached by the investor to this question" in prompt.split("---")[0])
public = server._public_full_document_context(docs)
check("the UI learns which documents were attached", public[0]["attached"] is True)

print("\n=== End to end: an attached file reaches the model ===")
from fastapi.testclient import TestClient


class RecordingModel:
    """A stand-in model client that answers anything and keeps the prompt it got."""

    configured = True
    embedding_model = "fake-embed"
    generation_model = "fake-gen"

    def __init__(self):
        self.prompts = []

    def embed_text(self, *args, **kwargs):
        raise RuntimeError("semantic search is off in this test")

    def generate_text(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return "Answer."

    def status(self):
        return {"configured": True}

    def routing_defaults(self):
        tier = {"model": "fake-gen", "thinkingLevel": "minimal"}
        return {"standard": dict(tier), "important": dict(tier)}

    def __getattr__(self, name):
        # Anything else the route asks the client for (routing labels and the
        # like) is irrelevant here; answer with a harmless default.
        return lambda *a, **k: None


e2e_store = fresh_store()
from brain_ingestion import chunk_text as _chunk
filing = e2e_store.add_source(kind="document", title="Oura prospectus draft", body="preview", tags=[], metadata={})
e2e_store.add_chunks(filing["id"], _chunk("Oura membership revenue grew; hardware attach rate fell. UNIQUEMARKER42 " * 80, source_title="Oura prospectus draft"))
other = e2e_store.add_source(kind="document", title="Unrelated memo", body="preview", tags=[], metadata={})
e2e_store.add_chunks(other["id"], _chunk("Nothing to do with rings. OTHERMARKER77 " * 80, source_title="Unrelated memo"))

model = RecordingModel()
saved_state = (server.brain_store, server.gemini_client)
server.brain_store, server.gemini_client = e2e_store, model
try:
    client = TestClient(server.app)
    body = {"question": "What does the attached file say about hardware?", "useSemantic": False, "autoSave": False,
            "attachedSourceIds": [filing["id"]]}
    response = client.post("/api/brain/analyze-company", json=body)
    check("the route answers", response.status_code == 200, f"{response.status_code} {response.text[:200]}")
    prompt = model.prompts[-1] if model.prompts else ""
    check("the attached file's full text is in the prompt", "UNIQUEMARKER42" in prompt)
    check("labelled as attached by the investor", "attached by the investor to this question" in prompt)
    check("a file that was not attached is not read in full", "OTHERMARKER77" not in prompt)
    docs = (response.json().get("context") or {}).get("fullDocuments") or []
    check("the response reports it as an attached full document",
          len(docs) == 1 and docs[0]["sourceId"] == filing["id"] and docs[0]["attached"] is True, str(docs)[:200])

    model.prompts.clear()
    response = client.post("/api/brain/analyze-company", json={**body, "attachedSourceIds": []})
    # Retrieval may still surface passages from the same file (the question names
    # "hardware"); what an attachment adds is the whole document, labelled.
    plain_docs = (response.json().get("context") or {}).get("fullDocuments") or []
    check("without an attachment no full document is read, and none is labelled attached",
          response.status_code == 200 and plain_docs == []
          and "attached by the investor" not in (model.prompts[-1] if model.prompts else ""), str(plain_docs)[:120])
    response = client.post("/api/brain/analyze-company", json={**body, "attachedSourceIds": [987654]})
    check("an attachment that no longer exists is dropped, not fatal", response.status_code == 200, response.text[:200])
    response = client.post("/api/brain/analyze-company", json={**body, "attachedSourceIds": list(range(1, 9))})
    check("more than the limit is refused by the request model", response.status_code == 422)
finally:
    server.brain_store, server.gemini_client = saved_state

print()
if FAILED:
    print(f"FAILED: {len(FAILED)} check(s): {', '.join(FAILED)}")
    sys.exit(1)
print("All Drive attach checks passed.")
