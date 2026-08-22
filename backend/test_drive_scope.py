"""Checks that the Drive status tells the truth about write permission.

Requesting a scope is not holding it. A refresh token authorised before
drive.file was requested keeps indexing happily and fails only when the agent
tries to upload, so the status has to distinguish three states: write granted,
write refused, and not yet known.
"""

import drive_indexer
from drive_indexer import DRIVE_FILE_SCOPE, DRIVE_READONLY_SCOPE, GoogleDriveClient


class FakeStore:
    def __init__(self, settings=None):
        self.settings = dict(settings or {})

    def get_setting(self, key):
        return self.settings.get(key)

    def set_setting(self, key, value):
        self.settings[key] = value


def client(settings=None):
    return GoogleDriveClient(store=FakeStore(settings))


# Nothing recorded yet: unknown, not "read only". Claiming saving is broken on
# the strength of a missing record would send the owner reconnecting for nothing.
fresh = client().scope_status()
assert fresh["grantedScope"] is None, fresh
assert fresh["writeScope"] is None, fresh
assert fresh["requestedScope"] == drive_indexer.DRIVE_SCOPES, fresh

# A token granted before drive.file existed reads but cannot write.
read_only = client({drive_indexer.GRANTED_SCOPE_SETTING: DRIVE_READONLY_SCOPE}).scope_status()
assert read_only["writeScope"] is False, read_only

# Both scopes granted, in either order, and tolerating extra scopes Google adds.
for granted in (
    f"{DRIVE_READONLY_SCOPE} {DRIVE_FILE_SCOPE}",
    f"{DRIVE_FILE_SCOPE} {DRIVE_READONLY_SCOPE}",
    f"openid {DRIVE_FILE_SCOPE} {DRIVE_READONLY_SCOPE} email",
):
    status = client({drive_indexer.GRANTED_SCOPE_SETTING: granted}).scope_status()
    assert status["writeScope"] is True, granted

# A scope that merely starts with the same text must not count as the write scope.
lookalike = client({drive_indexer.GRANTED_SCOPE_SETTING: DRIVE_FILE_SCOPE + ".metadata"}).scope_status()
assert lookalike["writeScope"] is False, lookalike

# Recording keeps the last thing Google said, and an empty answer never erases it.
recorder = client()
recorder._record_granted_scope(f"{DRIVE_READONLY_SCOPE} {DRIVE_FILE_SCOPE}")
assert recorder.scope_status()["writeScope"] is True
recorder._record_granted_scope("")
assert recorder.scope_status()["writeScope"] is True, "an empty scope must not wipe the record"
recorder._record_granted_scope(DRIVE_READONLY_SCOPE)
assert recorder.scope_status()["writeScope"] is False, "a narrowed grant must be visible"

# A store that refuses to write must not break a token refresh.
class BrokenStore(FakeStore):
    def set_setting(self, key, value):
        raise RuntimeError("store is down")

    def get_setting(self, key):
        raise RuntimeError("store is down")


broken = GoogleDriveClient(store=BrokenStore())
broken._record_granted_scope(DRIVE_FILE_SCOPE)
assert broken.scope_status()["writeScope"] is None

# The full status carries the same fields, so the UI reads one shape.
full = client({drive_indexer.GRANTED_SCOPE_SETTING: DRIVE_READONLY_SCOPE}).status("folder123")
assert full["writeScope"] is False, full
assert full["grantedScope"] == DRIVE_READONLY_SCOPE, full

print("Drive scope reporting checks passed.")
