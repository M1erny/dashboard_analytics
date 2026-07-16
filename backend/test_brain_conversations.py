"""Checks for durable, idempotent Brain conversation transcripts."""

from brain_conversations import autosave_brain_conversation
from drive_indexer import is_brain_conversation_transcript


class FakeDriveClient:
    def __init__(self):
        self.files = {}
        self.thread_files = {}
        self.next_id = 1
        self.update_calls = 0

    def ensure_folder(self, parent_id, name):
        return {"id": f"{parent_id}/{name}", "name": name}

    def find_file_by_app_property(self, _parent_id, _key, value):
        file_id = self.thread_files.get(value)
        return self.files.get(file_id)

    def upload_file(self, *, name, data, mime_type, folder_id, description, app_properties):
        file_id = f"file-{self.next_id}"
        self.next_id += 1
        item = {
            "id": file_id,
            "name": name,
            "mimeType": mime_type,
            "webViewLink": f"https://drive.google.com/file/d/{file_id}/view",
            "data": data,
            "folderId": folder_id,
            "description": description,
            "appProperties": app_properties,
        }
        self.files[file_id] = item
        self.thread_files[app_properties["brainThreadId"]] = file_id
        return item

    def update_file(self, file_id, *, name, data, mime_type, description, app_properties):
        self.update_calls += 1
        item = self.files[file_id]
        item.update({
            "name": name,
            "data": data,
            "mimeType": mime_type,
            "description": description,
            "appProperties": app_properties,
        })
        return item

    def download_file(self, file, *, max_bytes):
        assert len(file["data"]) <= max_bytes
        return file["data"], ".md", {"downloadMode": "download"}


client = FakeDriveClient()
assert is_brain_conversation_transcript({"relativePath": "Investment Brain/Conversations/thread.md"}) is True
assert is_brain_conversation_transcript({"relativePath": "Company Research/META.md"}) is False
base = {
    "client": client,
    "root_folder_id": "root",
    "thread_id": "thread-12345678",
    "title": "Should I own META?",
    "model": "gemini-test",
    "embedding_model": "embedding-test",
    "system_prompt": "Challenge the thesis and cite evidence.",
    "retrieval": {
        "semanticHits": 4,
        "keywordHits": 2,
        "expandedFiles": 1,
        "marketDataAvailable": True,
    },
    "context": {
        "retrieved": [{
            "sourceId": 7,
            "title": "META annual report chunk 12",
            "body": "Advertising evidence.",
            "source": {
                "id": 7,
                "title": "META annual report",
                "webUrl": "https://drive.google.com/file/d/meta/view",
            },
        }],
        "deepSources": [],
        "references": [],
        "fullDocuments": [],
        "portfolio": {
            "dataAsOf": "2026-07-15",
            "marketDataAvailable": True,
            "positions": [{"ticker": "META", "side": "Long", "currentWeight": 0.10}],
        },
    },
    "timings": {"generationMs": 1250.0},
}

first = autosave_brain_conversation(
    **base,
    exchange_id="exchange-0001",
    question="What does the evidence say?",
    answer="The evidence is mixed.",
)
assert first["status"] == "saved"
assert first["exchangeCount"] == 1
assert first["format"] == "markdown+yaml+json"
assert first["webViewLink"].startswith("https://drive.google.com/")

file = client.files[first["fileId"]]
markdown = file["data"].decode("utf-8")
assert "schema: investment-brain-thread/v1" in markdown
assert "exchange_count: 1" in markdown
assert "<!-- brain-exchange:exchange-0001 -->" in markdown
assert "### You" in markdown and "### Investment Brain" in markdown
assert "[META annual report](https://drive.google.com/file/d/meta/view)" in markdown
assert '"schema": "investment-brain-exchange/v1"' in markdown
assert '"systemPromptSha256"' in markdown
assert '"memories"' in markdown
assert "System prompt snapshot" in markdown
assert "Challenge the thesis and cite evidence." in markdown

second = autosave_brain_conversation(
    **base,
    exchange_id="exchange-0002",
    question="What would change the conclusion?",
    answer="A durable improvement in monetization.",
)
assert second["status"] == "saved"
assert second["fileId"] == first["fileId"]
assert second["exchangeCount"] == 2
assert client.update_calls == 1
markdown = client.files[first["fileId"]]["data"].decode("utf-8")
assert "exchange_count: 2" in markdown
assert markdown.count("<!-- brain-exchange:") == 2
assert markdown.count("<!-- system-prompt:") == 1

duplicate = autosave_brain_conversation(
    **base,
    exchange_id="exchange-0002",
    question="What would change the conclusion?",
    answer="A durable improvement in monetization.",
)
assert duplicate["status"] == "unchanged"
assert client.update_calls == 1

print("Brain conversation autosave checks passed.")
