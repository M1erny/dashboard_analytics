"""Polish regulatory filings: ESPI and EBI, as published by PAP.

The SEC has an API. Poland does not. Issuer disclosures reach the public through
ESPI (statutory reports, supervised by KNF) and EBI (NewConnect), and the
machine-readable-ish front door is PAP's listing at espiebi.pap.pl, whose search
endpoint is addressed by date rather than by company.

Two consequences shape this module:

- **A day is the unit of retrieval.** "What did my book disclose this week" is a
  cheap question; "find LPP's 2025 annual report" is a scan. The digest is
  therefore the primary shape and per-company lookup is built on top of it.
- **Issuers are named, not keyed.** A filing carries `Skrócona nazwa emitenta`,
  a human abbreviation, where the portfolio carries `LPP.WA`. Nothing in either
  artefact links them, so the join is name matching and it has to be explicit
  about when it is unsure.

Nothing here guesses a company name. Names are resolved from the market data
provider the dashboard already uses and cached; this module only decides whether
two names denote the same issuer.
"""

from __future__ import annotations

import re
import time
import unicodedata
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlencode

PAP_BASE = "https://espiebi.pap.pl"
PAP_SEARCH_PATH = "/wyszukiwarka"

# Official or exchange-operated sources for Polish issuer disclosures. Kept
# separate from the SEC set so the two jurisdictions can be reasoned about
# independently.
POLISH_OFFICIAL_DOMAINS = {
    "espiebi.pap.pl",
    "biznes.pap.pl",
    "gpw.pl",
    "www.gpw.pl",
    "newconnect.pl",
    "www.newconnect.pl",
    "knf.gov.pl",
    "www.knf.gov.pl",
}

# Legal-form noise. An ESPI abbreviation drops these; a provider's long name
# keeps them, so neither side can be compared until both are stripped.
_LEGAL_FORMS = (
    "spolka akcyjna",
    "spolka z ograniczona odpowiedzialnoscia",
    "s a",
    "sa",
    "sp z oo",
    "spzoo",
    "n v",
    "nv",
    "b v",
    "bv",
    "se",
    "asi",
    "plc",
    "inc",
    "ltd",
    "group",
    "grupa",
)

_ESPI = "ESPI"
_EBI = "EBI"

# NFKD decomposes accents but not struck or ligatured letters, so "ł" survives
# decomposition and is then dropped as non-ASCII: "spółka" becomes "spoka" and
# stops matching the legal form it is. These have to be transliterated first.
_NON_DECOMPOSING = str.maketrans({
    "ł": "l", "Ł": "L",
    "ø": "o", "Ø": "O",
    "đ": "d", "Đ": "D",
    "ß": "ss",
    "æ": "ae", "Æ": "AE",
    "œ": "oe", "Œ": "OE",
    "ı": "i",
})


def _fold(text: str) -> str:
    """Lower-case ASCII, with diacritics and struck letters flattened."""
    folded = str(text or "").translate(_NON_DECOMPOSING)
    folded = unicodedata.normalize("NFKD", folded)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return folded.lower()


def search_page_url(day: date, page: int = 0) -> str:
    """The listing URL for one calendar day.

    `enddate` carries a time because the endpoint treats a bare date as midnight,
    which would return an empty day.
    """
    stamp = day.isoformat()
    return (
        f"{PAP_BASE}{PAP_SEARCH_PATH}"
        f"?created={stamp}&enddate={stamp}+23%3A59&page={int(page)}"
    )


def search_url(
    query: str | None = None,
    start: date | None = None,
    end: date | None = None,
    page: int = 0,
) -> str:
    """One builder for both shapes the listing supports.

    The form takes `created`, `enddate`, `search` and `page` together, so a
    portfolio digest (a date window) and a company lookup (a phrase) are the same
    request with different parameters filled in. `enddate` carries a time because
    the endpoint reads a bare date as midnight, which returns an empty day.
    """
    params: list[tuple[str, str]] = []
    if start is not None:
        params.append(("created", start.isoformat()))
    if end is not None:
        params.append(("enddate", f"{end.isoformat()} 23:59"))
    clean_query = _clean(query)
    if clean_query:
        params.append(("search", clean_query))
    if not params:
        raise ValueError("A listing request needs a date window, a query, or both")
    params.append(("page", str(int(page))))
    return f"{PAP_BASE}{PAP_SEARCH_PATH}?{urlencode(params)}"


def node_url(node_id: str | int) -> str:
    """The permalink for a single report."""
    clean = str(node_id).strip().lstrip("/")
    if clean.startswith("node/"):
        clean = clean[len("node/"):]
    if not clean.isdigit():
        raise ValueError(f"Not a PAP node id: {node_id!r}")
    return f"{PAP_BASE}/node/{clean}"


def absolute_url(href: str) -> str:
    """Resolve a listing's relative href against the PAP host."""
    clean = (href or "").strip()
    if not clean:
        raise ValueError("Empty href")
    if clean.startswith(("http://", "https://")):
        return clean
    return f"{PAP_BASE}/{clean.lstrip('/')}"


def normalise_issuer_name(name: str) -> str:
    """Reduce an issuer name to something two sources can be compared on.

    Diacritics, case, punctuation and legal form all differ between an ESPI
    abbreviation and a data provider's long name while denoting one company.
    What survives is the distinguishing part: `CD PROJEKT S.A.` and `CDPROJEKT`
    both reduce to `cdprojekt`.
    """
    text = re.sub(r"[^a-z0-9]+", " ", _fold(name)).strip()
    if not text:
        return ""
    # Strip legal forms as whole words, longest first so "spolka akcyjna" is not
    # eaten piecemeal by "sa".
    for form in sorted(_LEGAL_FORMS, key=len, reverse=True):
        text = re.sub(rf"(?:^|\s){re.escape(form)}(?=\s|$)", " ", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def issuer_matches(filing_name: str, company_name: str) -> bool:
    """Whether a filing's issuer name denotes the same company as `company_name`.

    Deliberately strict: equality after normalisation, or one being a prefix of
    the other with at least four characters of agreement. A looser rule would
    match `AGORA` to `AGROTON`, and a wrong issuer on a regulatory filing is
    worse than a missed one.
    """
    left = normalise_issuer_name(filing_name)
    right = normalise_issuer_name(company_name)
    if not left or not right:
        return False
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    return len(shorter) >= 4 and longer.startswith(shorter)


def match_ticker(filing_name: str, names_by_ticker: dict[str, str]) -> str | None:
    """The portfolio ticker a filing belongs to, or None when it is not ours.

    Returns None on an ambiguous match rather than picking one, because two
    issuers answering to the same abbreviation is exactly the case where a guess
    would file a report under the wrong holding.
    """
    hits = [
        ticker
        for ticker, company in (names_by_ticker or {}).items()
        if issuer_matches(filing_name, company)
    ]
    if len(hits) == 1:
        return hits[0]
    return None


def classify_source(badge: str) -> str:
    """ESPI or EBI, from the listing's badge text."""
    text = str(badge or "").strip().upper()
    if _ESPI in text:
        return _ESPI
    if _EBI in text:
        return _EBI
    return "UNKNOWN"


PERIODIC_REPORT_PATTERNS = (
    r"\braport\s+(?:roczny|polroczny|kwartalny|okresowy)\b",
    r"\bskonsolidowany\s+raport\b",
    r"\bsprawozdanie\s+finansowe\b",
    r"\bwyniki\s+(?:finansowe|za)\b",
)


def is_periodic_report(title: str) -> bool:
    """Whether a filing title looks like results rather than a current report.

    ESPI does not label periodic and current reports distinguishably in the
    listing, so this reads the title. It is a filter for convenience, never a
    claim about the filing's statutory class.
    """
    text = _fold(title)
    return any(re.search(pattern, text) for pattern in PERIODIC_REPORT_PATTERNS)


# ─── Parsing ────────────────────────────────────────────────────────────────
# The saved pages are malformed: two <head> elements, one of them before <html>,
# and duplicated `colspan='2' colspan='2'` attributes. html.parser tolerates all
# of it, which a stricter parser would not, and it costs no dependency.


class EspiParseError(RuntimeError):
    """A selector that the page was expected to have did not appear.

    Raised rather than returning nothing, because an empty list reads as "no
    filings" — a claim the owner would act on — where a raise reads as "the page
    changed", which is the truth.
    """


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def split_title(title: str) -> tuple[str | None, str]:
    """An entry title is `ISSUER - SUBJECT`; split on the first separator only.

    Subjects contain their own dashes — "…art. 69 ustawy o ofercie publicznej -
    zmiana udziału…" — so splitting on the last, or on every, separator moves
    half the subject into the issuer.
    """
    text = _clean(title)
    if not text:
        return None, ""
    parts = text.split(" - ", 1)
    if len(parts) == 1:
        return None, text
    issuer = _clean(parts[0])
    subject = _clean(parts[1])
    return (issuer or None), subject


def parse_polish_number(value: str) -> float | None:
    """`302 427,00` -> 302427.0, `-28 632,00` -> -28632.0.

    Space-grouped thousands (ordinary or non-breaking) and a comma decimal mark.
    float() would reject every one of them.
    """
    text = str(value or "").replace(" ", " ").strip()
    if not text:
        return None
    text = text.replace(" ", "").replace(",", ".")
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return None
    return float(text)


class _TextCapture:
    """Accumulate the text of one element, tolerating nested tags inside it."""

    def __init__(self, tag: str):
        self.tag = tag
        self.depth = 1
        self.parts: list[str] = []

    def text(self) -> str:
        return _clean("".join(self.parts))


def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
    for key, value in attrs:
        if key == "class":
            return set((value or "").split())
    return set()


def _attr(attrs: list[tuple[str, str | None]], name: str) -> str:
    for key, value in attrs:
        if key == name:
            return value or ""
    return ""


# A results page carries these whether or not it found anything. They are what
# lets "PAP found nothing" be told apart from "the page we got is not a results
# page at all" - the empty search renders no `ul.newsList` whatsoever, so the
# absence of the list cannot carry that distinction on its own.
SEARCH_PAGE_MARKERS = ("view-id-wszukiwarka", "path-wyszukiwarka")


class _ListingParser(HTMLParser):
    """Pull `li.news` entries out of a /wyszukiwarka results page.

    The day comes from `h2.date` in the page rather than from the query, which is
    what makes `search=` mode work: a query without dates returns several
    `div.day` blocks, and every entry under each carries that block's date.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.entries: list[dict] = []
        self.saw_news_list = False
        self.saw_search_page = False
        self.list_items = 0
        self._news_list_depth = 0
        self._day: str | None = None
        self._entry: dict | None = None
        self._capture: _TextCapture | None = None
        self._field: str | None = None

    # -- capture plumbing --
    def _start_capture(self, tag: str, field: str) -> None:
        self._capture = _TextCapture(tag)
        self._field = field

    def handle_starttag(self, tag, attrs):
        if self._capture is not None:
            if tag == self._capture.tag:
                self._capture.depth += 1
            return

        classes = _classes(attrs)
        if not self.saw_search_page and classes.intersection(SEARCH_PAGE_MARKERS):
            self.saw_search_page = True
        if tag == "h2" and "date" in classes:
            self._start_capture(tag, "day")
        elif tag == "ul" and "newsList" in classes:
            self.saw_news_list = True
            self._news_list_depth = 1
        elif tag == "ul" and self._news_list_depth:
            self._news_list_depth += 1
        elif tag == "li" and self._news_list_depth:
            # Counted regardless of class. Distinguishing "quiet day" from
            # "layout changed" needs to know whether there were items at all,
            # and the class is the very thing a layout change would rename.
            self.list_items += 1
        if tag == "li" and "news" in classes:
            self._entry = {"date": self._day, "hours": [], "badge": "", "title": "", "href": ""}
        elif self._entry is not None and tag == "div" and "badge" in classes:
            self._start_capture(tag, "badge")
        elif self._entry is not None and tag == "div" and "hour" in classes:
            self._start_capture(tag, "hour")
        elif self._entry is not None and tag == "a":
            self._entry["href"] = _attr(attrs, "href")
            self._start_capture(tag, "title")

    def handle_endtag(self, tag):
        if self._capture is not None and tag == self._capture.tag:
            self._capture.depth -= 1
            if self._capture.depth > 0:
                return
            text = self._capture.text()
            field = self._field
            self._capture = None
            self._field = None
            if field == "day":
                self._day = text or None
                if self._entry is not None:
                    self._entry["date"] = self._day
            elif field == "badge" and self._entry is not None:
                self._entry["badge"] = text
            elif field == "hour" and self._entry is not None:
                self._entry["hours"].append(text)
            elif field == "title" and self._entry is not None:
                self._entry["title"] = text
            return

        if tag == "ul" and self._news_list_depth:
            self._news_list_depth -= 1
        if tag == "li" and self._entry is not None:
            self._finish_entry()

    def handle_data(self, data):
        if self._capture is not None:
            self._capture.parts.append(data)

    def _finish_entry(self) -> None:
        entry, self._entry = self._entry, None
        if not entry or not entry.get("href"):
            return
        href = entry["href"]
        match = re.search(r"/node/(\d+)", href)
        if not match:
            return
        issuer, subject = split_title(entry["title"])
        hours = [h for h in entry["hours"]]
        # Two `div.hour` elements: the publication time and the issuer's report
        # number. The second is legitimately empty on periodic reports, so it is
        # read positionally and allowed to be blank.
        self.entries.append({
            "date": entry.get("date"),
            "time": hours[0] if hours else "",
            "number": hours[1] if len(hours) > 1 else "",
            "source": classify_source(entry["badge"]),
            "issuer": issuer,
            "subject": subject,
            "title": entry["title"],
            "nodeId": match.group(1),
            "url": absolute_url(href),
        })


def parse_listing(html: str) -> list[dict]:
    """Entries from a /wyszukiwarka page, newest first as the page presents them."""
    text = str(html or "")
    if not text.strip():
        raise EspiParseError("Empty document: expected a /wyszukiwarka page")
    parser = _ListingParser()
    parser.feed(text)
    parser.close()
    if not parser.saw_news_list:
        if parser.saw_search_page:
            # A search that matches nothing renders the form and no list at all.
            # Raising here reported "the layout changed" for the ordinary case of
            # a phrase with no filings, which sent the owner hunting a bug in the
            # parser instead of correcting their query.
            return []
        raise EspiParseError(
            "Selector 'ul.newsList' not found and this is not a /wyszukiwarka results page: "
            "the layout changed, or the request was redirected"
        )
    if parser.list_items and not parser.entries:
        # The list held items and none of them parsed. A quiet day renders an
        # empty list, so this is a layout change, and returning [] here would
        # read as "no filings" — a claim the owner would act on.
        raise EspiParseError(
            f"'ul.newsList' held {parser.list_items} items but none parsed as entries: "
            "the 'li.news' / 'div.badge' / 'div.hour' / 'a' layout changed"
        )
    return parser.entries


ATTACHMENT_PREFIX = "/download/attachment/"
FINANCIALS_HEADING = "WYBRANE DANE FINANSOWE"


class _ReportParser(HTMLParser):
    """Pull the identity, type, attachments and selected financials from a node page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.canonical = ""
        self.fields: dict[str, str] = {}
        self.attachments: list[dict] = []
        self.tables: list[dict] = []
        self._table_stack: list[dict] = []
        self._row: list[str] | None = None
        self._capture: _TextCapture | None = None
        self._field: str | None = None
        self._pending_field: str | None = None
        self._attachment_href: str | None = None

    def handle_starttag(self, tag, attrs):
        # Hrefs are recorded even mid-capture: an attachment link lives inside a
        # table cell whose text is being accumulated.
        if tag == "a":
            href = _attr(attrs, "href")
            if ATTACHMENT_PREFIX in href:
                self._attachment_href = href
        if tag == "link" and _attr(attrs, "rel") == "canonical":
            self.canonical = _attr(attrs, "href")

        if self._capture is not None:
            if tag == self._capture.tag:
                self._capture.depth += 1
            return

        classes = _classes(attrs)
        if tag == "div":
            for name in ("field--name-field-report-source", "field--name-field-report-type"):
                if name in classes:
                    self._pending_field = name
            if "field__item" in classes and self._pending_field:
                self._capture = _TextCapture(tag)
                self._field = self._pending_field
        elif tag == "table":
            table = {"classes": classes, "rows": []}
            self._table_stack.append(table)
            self.tables.append(table)
        elif tag == "tr" and self._table_stack:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._capture = _TextCapture(tag)
            self._field = "cell"

    def handle_endtag(self, tag):
        if self._capture is not None and tag == self._capture.tag:
            self._capture.depth -= 1
            if self._capture.depth > 0:
                return
            text = self._capture.text()
            field = self._field
            self._capture = None
            self._field = None
            if field == "cell" and self._row is not None:
                self._row.append(text)
                if self._attachment_href:
                    self._record_attachment(self._attachment_href, text)
                    self._attachment_href = None
            elif field:
                self.fields[field] = text
                self._pending_field = None
            return

        if tag == "tr" and self._row is not None:
            if self._table_stack:
                self._table_stack[-1]["rows"].append(self._row)
            self._row = None
        elif tag == "table" and self._table_stack:
            self._table_stack.pop()
        # Deliberately no reset on </a>: the anchor closes before the cell that
        # holds it, so clearing here loses every attachment. It is cleared when
        # the cell is recorded, and overwritten by the next anchor.

    def handle_data(self, data):
        if self._capture is not None:
            self._capture.parts.append(data)

    def _record_attachment(self, href: str, label: str) -> None:
        name = href.rsplit("/", 1)[-1]
        # The correction section carries `/download/attachment/{node}/path` — an
        # empty placeholder, not a file. Anything without a suffix is not a document.
        if "." not in name:
            return
        url = absolute_url(href)
        for existing in self.attachments:
            if existing["url"] == url:
                if label and not existing["label"]:
                    existing["label"] = label
                return
        self.attachments.append({"url": url, "fileName": name, "label": label})


def _key_value_rows(rows: list[list[str]]) -> dict[str, str]:
    pairs = {}
    for row in rows:
        if len(row) == 2 and row[0]:
            pairs[row[0]] = row[1]
    return pairs


def _parse_financials(tables: list[dict]) -> dict:
    """The `WYBRANE DANE FINANSOWE` block: line items with period and comparative."""
    for table in tables:
        header = None
        for row in table["rows"]:
            if any(_clean(cell).upper() == FINANCIALS_HEADING for cell in row):
                header = [cell for cell in (_clean(c) for c in row) if cell]
                break
        if header is None:
            continue
        currencies = [cell for cell in header if re.fullmatch(r"[A-Z]{3}", cell)]
        units = next((cell for cell in header if cell.lower().startswith("w tys")), "")
        items = []
        for row in table["rows"]:
            cells = [cell for cell in (_clean(c) for c in row) if cell]
            if len(cells) != 5:
                continue
            values = [parse_polish_number(cell) for cell in cells[1:]]
            if any(value is None for value in values):
                continue
            items.append({
                "item": cells[0],
                "current": values[0],
                "previous": values[1],
                "currentSecondary": values[2],
                "previousSecondary": values[3],
            })
        if items:
            return {
                "units": units,
                "currency": currencies[0] if currencies else "",
                "secondaryCurrency": currencies[1] if len(currencies) > 1 else "",
                "items": items,
            }
    return {"units": "", "currency": "", "secondaryCurrency": "", "items": []}


def parse_report(html: str) -> dict:
    """Identity, type, attachments and selected financials from a PAP node page."""
    text = str(html or "")
    if not text.strip():
        raise EspiParseError("Empty document: expected a PAP node page")
    parser = _ReportParser()
    parser.feed(text)
    parser.close()

    identity_table = next((t for t in parser.tables if "nDokument" in t["classes"]), None)
    if identity_table is None:
        raise EspiParseError(
            "Selector 'table.nDokument' not found: the report layout changed, or this is not a report page"
        )
    identity = _key_value_rows(identity_table["rows"])
    node_match = re.search(r"/node/(\d+)", parser.canonical or "")
    return {
        "nodeId": node_match.group(1) if node_match else "",
        "url": parser.canonical or "",
        "source": classify_source(parser.fields.get("field--name-field-report-source", "")),
        "reportType": parser.fields.get("field--name-field-report-type", ""),
        "issuerName": identity.get("Nazwa emitenta", ""),
        "issuerSymbol": identity.get("Symbol Emitenta", ""),
        "preparedOn": identity.get("Data sporządzenia", ""),
        "sector": identity.get("Sektor", ""),
        "website": identity.get("adres www", ""),
        "attachments": parser.attachments,
        "financials": _parse_financials(parser.tables),
    }


# ─── Fetching ───────────────────────────────────────────────────────────────

DEFAULT_LISTING_TIMEOUT = 20.0
# A day carries roughly ninety filings across the whole market, three pages of
# thirty. Walking a week of that is twenty-odd requests and would still truncate
# silently, so a digest queries `search=` per holding instead: fewer requests,
# each small, and nothing dropped without saying so.
DEFAULT_MAX_PAGES = 3
USER_AGENT = "dashboard-analytics-brain/1.0 (portfolio research; contact via repository)"


# Markers of an interstitial served instead of the page that was asked for. PAP
# sits behind Imperva, and its challenge answers 200 with a body that is not the
# site - so the status code cannot be what tells us, and "no ul.newsList" on its
# own reads as a layout change when the real answer is "we never got the page".
CHALLENGE_MARKERS = (
    "_Incapsula_Resource",
    "incap_ses",
    "visid_incap",
    "Request unsuccessful",
    "Incident ID",
    "Imperva",
    "cf-browser-verification",
    "Just a moment",
    "captcha",
)


def page_fingerprint(text: str) -> dict:
    """Enough about a page to say what it is without printing the whole thing.

    Every failure so far has been diagnosed from a saved browser page, which by
    definition already passed the bot check. This is the equivalent taken from
    wherever the request actually ran.
    """
    body = text or ""
    title = ""
    match = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
    if match:
        title = _clean(re.sub(r"\s+", " ", match.group(1)))[:200]
    challenge = next((marker for marker in CHALLENGE_MARKERS if marker in body), None)
    return {
        "bytes": len(body),
        "title": title,
        "isResultsPage": any(marker in body for marker in SEARCH_PAGE_MARKERS),
        "hasNewsList": "newsList" in body,
        "challengeMarker": challenge,
        # First non-empty text, which is what a challenge page usually says.
        "snippet": _clean(re.sub(r"<[^>]+>", " ", body))[:300],
    }


def _get(url: str, timeout: float) -> str:
    import httpx

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return response.text


def fetch_page_diagnostics(url: str, timeout: float = DEFAULT_LISTING_TIMEOUT) -> dict:
    """What this host receives for `url`, without parsing or raising on status.

    Deliberately separate from `_get`: the point is to report a refusal, so it
    must not turn one into an exception.
    """
    import httpx

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url, headers={"User-Agent": USER_AGENT})
    except Exception as exc:
        return {
            "requestedUrl": url,
            "reached": False,
            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
        }

    return {
        "requestedUrl": url,
        "reached": True,
        "status": response.status_code,
        "finalUrl": str(response.url),
        "redirected": str(response.url) != url,
        "contentType": response.headers.get("content-type", ""),
        "server": response.headers.get("server", ""),
        # Imperva names itself in a response header more reliably than in the body.
        "setCookieNames": sorted({
            cookie.split("=", 1)[0].strip()
            for cookie in response.headers.get_list("set-cookie")
        })[:10],
        "userAgentSent": USER_AGENT,
        **page_fingerprint(response.text),
    }


def fetch_listing(
    query: str | None = None,
    start: date | None = None,
    end: date | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    timeout: float = DEFAULT_LISTING_TIMEOUT,
    get: object = None,
) -> dict:
    """Entries for one query, following pagination up to `max_pages`.

    `get` is injectable so the paging and truncation logic can be tested without
    reaching the network.

    Returns the entries plus `truncated`, because a caller that cannot tell a
    complete answer from a capped one will present a capped one as complete.
    """
    fetcher = get or (lambda url: _get(url, timeout))
    pages = max(1, int(max_pages))

    def collect(phrase: str | None) -> tuple[list[dict], int, bool]:
        entries: list[dict] = []
        seen: set[str] = set()
        pages_read = 0
        truncated = False
        for page in range(pages):
            url = search_url(query=phrase, start=start, end=end, page=page)
            body = fetcher(url)
            try:
                page_entries = parse_listing(body)
            except EspiParseError as error:
                # Say what came back instead. "The layout changed" was a guess
                # that sent the owner after a parser bug when the page had never
                # arrived, and the evidence was sitting in the response body.
                fingerprint = page_fingerprint(body)
                if fingerprint["challengeMarker"]:
                    raise EspiParseError(
                        f"{PAP_BASE} answered with a bot-protection interstitial rather than the page "
                        f"(marker '{fingerprint['challengeMarker']}', title {fingerprint['title']!r}, "
                        f"{fingerprint['bytes']} bytes). The request never reached the listing."
                    ) from error
                raise EspiParseError(f"{error} [received {fingerprint}]") from error
            pages_read += 1
            # Deduplication and end-of-results are separate questions. Stopping on
            # "no new entries" would conflate them, and a repeated page would then
            # look like the end while the cap was the real reason.
            for entry in page_entries:
                if entry["nodeId"] not in seen:
                    seen.add(entry["nodeId"])
                    entries.append(entry)
            if not page_entries:
                break
            if page == pages - 1:
                # Stopped because of the cap while the page still had content, so
                # there is probably more behind it. Say so: a caller that cannot
                # tell a capped answer from a complete one will present it as complete.
                truncated = True
        return entries, pages_read, truncated

    entries, pages_read, truncated = collect(query)

    # PAP's search appears to match case-sensitively: `search=xtb` returns nothing
    # while `search=XTB` returns six pages, and ESPI titles carry issuer names in
    # the form the issuer files under. So one retry in upper case, and only when
    # the first attempt found nothing - it can add hits, never remove them.
    retried_query = None
    clean_query = _clean(query)
    if not entries and clean_query and clean_query != clean_query.upper():
        retried_query = clean_query.upper()
        entries, retry_pages, truncated = collect(retried_query)
        pages_read += retry_pages

    return {
        "entries": entries,
        "pagesRead": pages_read,
        "truncated": truncated,
        "retriedQuery": retried_query if entries else None,
    }


def fetch_report(node_id: str | int, timeout: float = DEFAULT_LISTING_TIMEOUT, get: object = None) -> dict:
    """One report page, parsed."""
    url = node_url(node_id)
    fetcher = get or (lambda u: _get(u, timeout))
    report = parse_report(fetcher(url))
    if not report.get("url"):
        report["url"] = url
    return report


# Candidate machine-readable sources, cheapest and most official first. The site
# is Drupal 11 with a view named `wszukiwarka`, and Drupal core ships JSON:API and
# can expose a view as a feed - so an endpoint that returns data rather than a
# page may already exist. Probing beats guessing, and a real API would remove the
# scraping and the bot check together.
FEED_CANDIDATES = (
    ("jsonapi", "/jsonapi"),
    ("jsonapi_node", "/jsonapi/node/report"),
    ("node_json", "/node/733373?_format=json"),
    ("rss_root", "/rss.xml"),
    ("view_rss", "/wyszukiwarka/rss"),
    ("view_feed", "/wyszukiwarka/feed"),
    ("view_xml", "/wyszukiwarka.xml"),
    ("sitemap", "/sitemap.xml"),
)


def probe_feed_candidates(timeout: float = DEFAULT_LISTING_TIMEOUT) -> list[dict]:
    """Ask each candidate what it is. Read-only, one request each, no parsing."""
    results = []
    for name, path in FEED_CANDIDATES:
        info = fetch_page_diagnostics(f"{PAP_BASE}{path}", timeout=timeout)
        content_type = str(info.get("contentType") or "")
        results.append({
            "name": name,
            "path": path,
            "status": info.get("status"),
            "contentType": content_type,
            "bytes": info.get("bytes"),
            "challengeMarker": info.get("challengeMarker"),
            # A structured answer is the whole point; an HTML page is not one.
            "structured": any(
                kind in content_type
                for kind in ("json", "xml", "rss", "atom")
            ),
            "title": info.get("title"),
            "snippet": str(info.get("snippet") or "")[:160],
            "error": info.get("error"),
        })
    return results


def digest_for_holdings(
    names_by_ticker: dict[str, str],
    start: date,
    end: date,
    max_pages: int = 1,
    timeout: float = DEFAULT_LISTING_TIMEOUT,
    get: object = None,
    deadline_seconds: float | None = None,
    now: object = None,
) -> dict:
    """Filings from the book's own issuers over a window.

    One `search=` per holding rather than one walk of the whole market: a week of
    every issuer's filings is twenty-odd pages and would truncate, where a per
    holding query returns a handful. The search narrows and `match_ticker`
    confirms, so an issuer whose name merely contains the query is dropped.
    """
    clock = now or time.monotonic
    started = clock()
    per_ticker: dict[str, list[dict]] = {}
    failures: dict[str, str] = {}
    truncated = False
    queried: list[str] = []
    for ticker, company in sorted((names_by_ticker or {}).items()):
        query = _clean(company)
        if not query:
            continue
        if deadline_seconds is not None and (clock() - started) >= float(deadline_seconds):
            # Stop short and say which issuers were never asked, rather than let
            # the whole digest be abandoned and every completed query discarded.
            failures[ticker] = "not queried: the digest ran out of time"
            continue
        queried.append(ticker)
        try:
            result = fetch_listing(
                query=query, start=start, end=end, max_pages=max_pages, timeout=timeout, get=get
            )
        except Exception as exc:  # one bad issuer must not lose the whole digest
            failures[ticker] = str(exc)[:200]
            continue
        truncated = truncated or result["truncated"]
        matched = []
        for entry in result["entries"]:
            if match_ticker(entry.get("issuer") or "", {ticker: company}) == ticker:
                matched.append({**entry, "matchedTicker": ticker})
        if matched:
            per_ticker[ticker] = matched

    entries = sorted(
        (entry for rows in per_ticker.values() for entry in rows),
        key=lambda e: (e.get("date") or "", e.get("time") or ""),
        reverse=True,
    )
    return {
        "entries": entries,
        "byTicker": {ticker: len(rows) for ticker, rows in per_ticker.items()},
        # The tickers actually asked about, so a caller can tell "nothing filed"
        # from "we never got to it".
        "queriedTickers": sorted(queried),
        "failures": failures,
        "truncated": truncated,
        "deadlineHit": bool(
            deadline_seconds is not None
            and any(reason.startswith("not queried") for reason in failures.values())
        ),
    }


def issuer_candidates(entries: list[dict]) -> list[dict]:
    """Distinct issuers in a listing, with a filing to recognise each one by.

    The raw PAP string is what is returned, not its normalised form: the stored
    name has to be the string `match_ticker` will later compare filings against,
    and `normalise_issuer_name` output would match nothing.
    """
    grouped: dict[str, dict] = {}
    for entry in entries or []:
        issuer = _clean(entry.get("issuer"))
        if not issuer:
            continue
        entry_date = str(entry.get("date") or "")
        candidate = grouped.get(issuer)
        if candidate is None:
            grouped[issuer] = {
                "name": issuer,
                "filings": 1,
                "latestDate": entry_date,
                "sampleSubject": _clean(entry.get("subject")),
                "sampleNodeId": entry.get("nodeId"),
                "sampleUrl": entry.get("url"),
            }
            continue
        candidate["filings"] += 1
        if entry_date and entry_date > str(candidate.get("latestDate") or ""):
            candidate.update({
                "latestDate": entry_date,
                "sampleSubject": _clean(entry.get("subject")),
                "sampleNodeId": entry.get("nodeId"),
                "sampleUrl": entry.get("url"),
            })

    # Most-filed first: a count is evidence, whereas name proximity to a ticker is
    # a hint that would rank a wrong company above a right one.
    return sorted(grouped.values(), key=lambda item: (-item["filings"], item["name"]))


def ticker_root(ticker: str) -> str:
    """The part of a Yahoo ticker worth typing into a search box."""
    return str(ticker or "").strip().upper().split(".")[0]


def candidate_starts_with_root(candidate_name: str, ticker: str) -> bool:
    """Whether this issuer's name literally begins with the ticker root.

    That is all it claims, and the label shown to the owner must say the same
    thing ("starts with SPR"), never "matches the ticker". The distinction is not
    pedantry: SPR.WA is Spyrosoft, but `SPRINT S.A.` also begins with SPR and was
    a real GPW issuer, so a mark reading "matches" would be confidently wrong next
    to a one-click control. It stays a prefix test for the same reason - a
    subsequence test would reach BDX/BUDIMEX and BFT/BENEFIT and produce many more
    such near misses, and a wrong issuer on a regulatory filing is the worst
    outcome available here.
    """
    root = _fold(ticker_root(ticker))
    name = normalise_issuer_name(candidate_name)
    if not root or not name or len(root) < 2:
        return False
    return name.startswith(root)


def merge_issuer_names(cached: dict, resolved: dict, tickers: list[str]) -> dict:
    """The issuer-name map for `tickers`, preferring a cached name over a fresh one.

    A name that has already been recorded — possibly corrected by hand, or taken
    from a report's own `Symbol Emitenta`, which is better than any provider's
    long name — must not be overwritten by a provider lookup. Tickers outside the
    current book are dropped so the cache cannot grow without bound.
    """
    wanted = [t for t in (tickers or []) if t]
    merged: dict[str, str] = {}
    for ticker in wanted:
        name = _clean((cached or {}).get(ticker)) or _clean((resolved or {}).get(ticker))
        if name:
            merged[ticker] = name
    return merged


def polish_tickers(config: dict) -> list[str]:
    """The Warsaw-listed holdings in a portfolio config.

    Country rather than suffix: the suffix is a Yahoo convention and the country
    is the portfolio's own statement about the holding.
    """
    tickers = []
    for ticker, info in (config or {}).items():
        country = str((info or {}).get("country") or "").upper()
        if country == "POL" or str(ticker).upper().endswith(".WA"):
            tickers.append(ticker)
    return sorted(tickers)
