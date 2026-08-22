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
import unicodedata
from datetime import date

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
