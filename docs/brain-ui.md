# The Brain As An Editor, Not A Dashboard

The Brain page had grown the way feature-by-feature pages do: a chat column on
the left and a right column of stacked cards — saved threads, library stats,
Drive controls, source search, an SEC filing finder, files by date, ingestion
coverage, self-build. Nine surfaces competing on one screen, each permanently
visible whether or not it had anything to say. The conversation, which is the
actual product, occupied about half the width and none of the attention.

Editors solved this problem a long time ago. VS Code, Cursor and Codex all use
the same four zones, and the reason is that they map onto four different kinds
of information:

| Zone | Holds | Why it is that zone |
| --- | --- | --- |
| Rail | What you have open | Navigation, so it is always there and always narrow |
| Editor | The work | Everything else defers to it |
| Panel | Tools you summon | Only relevant while you are using it, so it closes |
| Status bar | State | One line, never a card |

The Brain now has exactly those four.

## The conversation is the surface

The transcript is the full width of the window minus the rail, and it scrolls in
its own pane — the page itself no longer scrolls, so the composer and the status
bar never move.

Answers lost their card. An assistant message is a green rule down the left and
the prose itself, the way an editor renders output rather than a widget; user
messages keep a small bubble so the turns stay distinguishable when scanning.
The retrieval line — how many semantic hits, frameworks, full files, live
positions — moved under the answer with the timing, because it describes where
an answer came from and is read after it, not before.

## Context is attached in the composer

The reference layer, full-document context and system prompt were three rows in
a card three hundred pixels to the right of the box you type in. They are now
chips inside the composer, showing their own count, dimmed when empty and lit
when they carry something:

```text
[ Reference 2 ] [ Full files 1 ] [ Prompt ] [ Tools ]
```

This is the Cursor/Codex arrangement, and it is not just tidier. Those three
settings change what the next question is answered from. Showing them attached
to the question makes that relationship legible; showing them in a sidebar made
them look like configuration.

## Everything else is a panel

`Index`, `Search`, `Filings`, `Drive` and `Code` are tabs in a right panel that
is **closed by default** and opens from the header, from the status bar, or from
the command palette. Nothing was removed — the SEC finder, URL import, coverage
report, files-by-date and self-build all still exist, and each is now full height
instead of a card in a queue.

## State goes in the status bar

Backend health, source count, index coverage, position count, gross exposure,
Drive autosave and the last notice occupy one 28-pixel line at the bottom. They
used to be four badges in the header plus a card. The counts are buttons: they
open the panel that explains them.

The notice line matters more than it looks. Every failure in this file reports
through it, and it is now always visible instead of being pushed off-screen by a
long answer.

## Keyboard

| Key | Action |
| --- | --- |
| `⌘K` / `Ctrl+K` | Command palette |
| `⌘B` / `Ctrl+B` | Toggle the thread rail |
| `⌘N` / `Ctrl+N` | New thread |
| `Enter` | Send · `Shift+Enter` for a newline |

The palette lists every Brain action with its current state as the subtitle — the
reference layer shows which files are in it, the prompt shows its first line,
embedding shows how many passages are missing. It is the fastest route to a
feature whose panel you have not opened.

## Smaller changes worth naming

- **The thread list loads with the page.** It used to need a click on "Load
  conversation history from Drive". Navigation that has to be requested is not
  navigation.
- **The composer starts empty.** It was pre-filled with a long question the owner
  had to select and delete before typing. The empty state offers openers instead.
- **Bullets render as bullets.** `MarkdownAnswer` set `marker:` colours but never
  `list-disc`, and Tailwind's reset strips markers, so every list in every answer
  had been rendering flush.
- **The completion notice no longer prints `undefined`** when a response omits
  the model name — it sits permanently in the status bar now, so a missing field
  is visible rather than transient.

## When a question fails

`fetch` rejects with a bare `TypeError` for every network-level failure alike —
"Failed to fetch" in Chrome, "Load failed" in Safari. A dropped connection, a
server process killed mid-request, a refused preflight and a phone changing
network all produce the same three words, and the owner is left with nothing to
act on.

The Brain now answers the question the message does not. On a network-level
failure it probes `/api/brain/status` and reports which of two different problems
it hit:

- **the backend answers the probe** — the service is up, so this one request was
  killed rather than the service. That is a question too heavy or too slow for
  the host to hold open, and the Render logs will say whether it was a restart or
  an out-of-memory kill.
- **the probe fails too** — the backend restarted, went to sleep, or the
  connection is gone. Waiting and retrying is the fix.

Both messages carry the elapsed time, because a failure at two seconds and one at
a hundred are not the same event, and both name the full-document count when one
is set: whole files are the most expensive setting the Brain has, and the first
thing to reduce when requests start dying.

The client's own timeout is reported separately, since giving up is not the same
as being cut off.

Both paths were reproduced in a browser against a backend that accepts the
request and then drops the connection, with and without the service surviving.

## What was checked

The page was driven in a real browser against a mock backend: empty state, a full
question and answer, the evidence disclosure, each panel tab, the palette, the
offline state, and a 430px viewport. Rail and panel become overlay drawers below
`lg` and `xl` respectively; the transcript, composer and status bar stay usable at
phone width.
