"""Checks the refresh job's environment guard.

The job spends a minute and about 1.2 MB fetching before it ever touches the
database, so a DATABASE_URL that cannot connect must be caught before that, and
it must be reported in words. The value that prompted this was the literal
placeholder "postgresql://...", which psycopg reports - after the whole fetch -
as `UnicodeError: label empty or too long` from the IDNA codec.
"""

import os
import sys

import refresh_market_snapshot as job

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {detail}")
        FAILED.append(name)


def with_env(value, body):
    saved = (os.environ.get("DATABASE_URL"), os.environ.get("BRAIN_DATABASE_URL"))
    os.environ.pop("BRAIN_DATABASE_URL", None)
    if value is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = value
    try:
        return body()
    finally:
        for key, restored in zip(("DATABASE_URL", "BRAIN_DATABASE_URL"), saved):
            if restored is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = restored


def rejection(value, require_remote=True):
    """Return the error message for a value, or None if it was accepted."""
    def run():
        try:
            job.check_database_url(require_remote=require_remote)
            return None
        except job.ConfigError as ex:
            return str(ex)
    return with_env(value, run)


print("\n=== Refresh job: DATABASE_URL guard ===")

REAL = "postgresql://postgres.abcdefgh:s3cr%26t@aws-0-eu-west-1.pooler.supabase.com:6543/postgres?sslmode=require"

check("a real Supabase pooler URL is accepted", rejection(REAL) is None, str(rejection(REAL)))
check("postgres:// is accepted too", rejection("postgres://u:p@db.example.com:5432/postgres") is None)

placeholder = rejection("postgresql://...")
check("the literal placeholder is rejected", placeholder is not None)
check(
    "and the message says it is a placeholder, not just that it is invalid",
    placeholder is not None and "placeholder" in placeholder.lower(),
    str(placeholder),
)

missing = rejection(None)
check("an unset variable is rejected under --require-remote", missing is not None)
check(
    "but is allowed otherwise, so a local SQLite run still works",
    rejection(None, require_remote=False) is None,
    str(rejection(None, require_remote=False)),
)
check(
    "an unset variable resolves to None, marking the store as local",
    with_env(None, lambda: job.check_database_url(require_remote=False)) is None,
)
check(
    "a malformed value is rejected even without --require-remote",
    rejection("postgresql://...", require_remote=False) is not None,
    "a placeholder is a mistake in every context",
)
check(
    "and the message shows how to set it on both shells",
    missing is not None and "PowerShell" in missing and "export" in missing,
    str(missing),
)

check("an empty string counts as unset", rejection("   ") is not None)
check("a real URL is returned so the caller can tell remote from local", rejection(REAL) is None and with_env(REAL, lambda: job.check_database_url()) == REAL)
check("a bare word is rejected", rejection("supabase") is not None)
check(
    "the wrong scheme is named",
    (rejection("mysql://u:p@host/db") or "").find("postgresql://") >= 0,
    str(rejection("mysql://u:p@host/db")),
)
check("a URL with no host is rejected", rejection("postgresql:///postgres") is not None)
check("an empty label inside the host is rejected", rejection("postgresql://u:p@host..com/db") is not None)

# The secret must never be echoed back in an error the user may paste anywhere.
for value in ("postgresql://...", "mysql://user:hunter2@host/db", "supabase"):
    message = rejection(value) or ""
    check(f"the message for {value[:24]!r} does not leak a password", "hunter2" not in message)

# BRAIN_DATABASE_URL takes precedence, matching create_brain_store.
def brain_wins():
    os.environ["BRAIN_DATABASE_URL"] = REAL
    try:
        return job.check_database_url()
    finally:
        os.environ.pop("BRAIN_DATABASE_URL", None)


check("BRAIN_DATABASE_URL overrides DATABASE_URL", with_env("postgresql://...", brain_wins) == REAL)

print()
if FAILED:
    print(f"FAILED: {len(FAILED)} check(s): {', '.join(FAILED)}")
    sys.exit(1)
print("All refresh job config checks passed.")
