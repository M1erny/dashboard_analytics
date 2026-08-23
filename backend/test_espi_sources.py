"""Joining a Polish filing to a holding is name matching, and it must be strict.

The portfolio carries `LPP.WA`. An ESPI filing carries `Skrócona nazwa emitenta`
— a human abbreviation like `CDPROJEKT`. Nothing links them, so the join is name
comparison, and a wrong issuer on a regulatory filing is worse than a missed one.
"""

import os
import sys
from datetime import date

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import espi_sources as espi

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  [PASS] {name}")
    else:
        FAILURES.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  [FAIL] {name} {detail}")


def main():
    print("=" * 70)
    print("ESPI SOURCES")
    print("=" * 70)

    # 1. URLs. The endpoint treats a bare end date as midnight, which returns an
    #    empty day, so the time component is load-bearing.
    url = espi.search_page_url(date(2026, 8, 21))
    check("the search URL carries the day", "created=2026-08-21" in url, url)
    check("and an end time, not just a date", "23%3A59" in url, url)
    check("and a page", url.endswith("page=0"), url)
    check("page 3 is addressable", espi.search_page_url(date(2026, 8, 21), 3).endswith("page=3"))

    check("a node id becomes a permalink", espi.node_url(123456) == "https://espiebi.pap.pl/node/123456")
    check("a node path is accepted too", espi.node_url("/node/99") == "https://espiebi.pap.pl/node/99")
    for bad in ("", "abc", "node/", "../etc/passwd"):
        try:
            espi.node_url(bad)
        except ValueError:
            check(f"a non-numeric node id {bad!r} is refused", True)
        else:
            check(f"a non-numeric node id {bad!r} is refused", False, "no ValueError")

    check("a relative href resolves", espi.absolute_url("/node/5") == "https://espiebi.pap.pl/node/5")
    check("an absolute href is left alone", espi.absolute_url("https://x.test/a") == "https://x.test/a")

    # 2. Normalisation has to survive diacritics, case, punctuation and legal form,
    #    because the two sides of the join differ in all four.
    cases = [
        ("CD PROJEKT S.A.", "cdprojekt"),
        ("CDPROJEKT", "cdprojekt"),
        ("LPP SA", "lpp"),
        ("LPP", "lpp"),
        ("Benefit Systems S.A.", "benefitsystems"),
        ("BENEFITSYSTEMS", "benefitsystems"),
        ("Pepco Group N.V.", "pepco"),
        ("Agora S.A.", "agora"),
        ("Żywiec Spółka Akcyjna", "zywiec"),
        ("Grupa Kęty S.A.", "kety"),
        ("  spyrosoft   s.a.  ", "spyrosoft"),
    ]
    for raw, expected in cases:
        got = espi.normalise_issuer_name(raw)
        check(f"{raw!r} -> {expected!r}", got == expected, f"got {got!r}")
    check("an empty name normalises to empty", espi.normalise_issuer_name("") == "")
    check("a name of only a legal form normalises to empty", espi.normalise_issuer_name("S.A.") == "")

    # 3. Matching across the two naming conventions.
    check("abbreviation matches long name", espi.issuer_matches("CDPROJEKT", "CD Projekt S.A."))
    check("long name matches abbreviation", espi.issuer_matches("Benefit Systems S.A.", "BENEFITSYSTEMS"))
    check("identical short names match", espi.issuer_matches("XTB", "XTB S.A."))
    check("a prefix of four or more matches", espi.issuer_matches("PEPCO", "Pepco Group N.V."))

    # The strictness is the point: these must NOT match.
    check("AGORA does not match AGROTON", not espi.issuer_matches("AGORA", "Agroton Public Ltd"))
    check("LPP does not match a different issuer", not espi.issuer_matches("LPP", "Lubawa S.A."))
    check("a three-letter prefix is not enough", not espi.issuer_matches("BUD", "Budimex SA"))
    check("empty never matches", not espi.issuer_matches("", "LPP"))
    check("empty never matches, either side", not espi.issuer_matches("LPP", ""))

    # 4. Ticker resolution. Names are supplied by the caller — this module never
    #    guesses a company name.
    names = {
        "LPP.WA": "LPP SA",
        "CDR.WA": "CD Projekt S.A.",
        "XTB.WA": "XTB S.A.",
        "BFT.WA": "Benefit Systems S.A.",
        "AGO.WA": "Agora S.A.",
    }
    check("a filing maps to its ticker", espi.match_ticker("CDPROJEKT", names) == "CDR.WA")
    check("and to another", espi.match_ticker("Benefit Systems S.A.", names) == "BFT.WA")
    check("a filing from outside the book maps to nothing", espi.match_ticker("ORLEN", names) is None)
    check("an empty issuer maps to nothing", espi.match_ticker("", names) is None)
    check("an empty book maps to nothing", espi.match_ticker("LPP", {}) is None)

    # Ambiguity returns None rather than a coin flip: two issuers answering to one
    # abbreviation is exactly when a guess files a report under the wrong holding.
    ambiguous = {"AAA.WA": "Kruk S.A.", "BBB.WA": "Kruk Group S.A."}
    check("an ambiguous match is refused", espi.match_ticker("KRUK", ambiguous) is None, str(ambiguous))

    # 5. Badge and title classification.
    check("an ESPI badge is read", espi.classify_source("ESPI") == "ESPI")
    check("an EBI badge is read", espi.classify_source(" ebi ") == "EBI")
    check("an unknown badge is named unknown", espi.classify_source("news") == "UNKNOWN")
    check("a missing badge does not crash", espi.classify_source(None) == "UNKNOWN")

    for title in (
        "Raport roczny za 2025 rok",
        "Skonsolidowany raport kwartalny za III kwartał 2026",
        "Raport półroczny 2026",
        "Sprawozdanie finansowe za 2025",
    ):
        check(f"periodic: {title[:40]!r}", espi.is_periodic_report(title), title)
    for title in (
        "Zawiadomienie o zmianie udziału w ogólnej liczbie głosów",
        "Powołanie członka zarządu",
        "Zawarcie umowy znaczącej",
    ):
        check(f"not periodic: {title[:40]!r}", not espi.is_periodic_report(title), title)

    # 6. The official-domain set is what gates a trusted import, so it must not
    #    quietly include a blog.
    for domain in ("espiebi.pap.pl", "www.gpw.pl", "newconnect.pl", "www.knf.gov.pl"):
        check(f"{domain} is trusted", domain in espi.POLISH_OFFICIAL_DOMAINS)
    for domain in ("bankier.pl", "www.biznesradar.pl", "stockwatch.pl", "example.com"):
        check(f"{domain} is not trusted", domain not in espi.POLISH_OFFICIAL_DOMAINS)

    # ── Against the saved pages, so a PAP layout change fails loudly ──────────
    listing_html = open(os.path.join(FIXTURES, "espi_listing.html"), encoding="utf-8").read()
    rows = espi.parse_listing(listing_html)
    check("the listing yields 30 entries", len(rows) == 30, str(len(rows)))
    check("every entry carries the day from h2.date", all(r["date"] == "2026-08-21" for r in rows))
    check("every entry has a node id", all(r["nodeId"].isdigit() for r in rows))
    check("every entry has an absolute PAP url", all(r["url"].startswith("https://espiebi.pap.pl/node/") for r in rows))

    by_node = {r["nodeId"]: r for r in rows}

    # The badge is mixed case in the markup — the site uppercases it in CSS.
    check("a mixed-case 'EBi' badge classifies as EBI", by_node["735228"]["source"] == "EBI", by_node["735228"]["source"])
    check("an 'ESPI' badge classifies as ESPI", by_node["735230"]["source"] == "ESPI")
    check("both sources appear in the page", {r["source"] for r in rows} == {"ESPI", "EBI"}, str({r["source"] for r in rows}))

    # The second div.hour is legitimately empty on this periodic report.
    wawel = by_node["735217"]
    check("an empty report number is tolerated", wawel["number"] == "", repr(wawel["number"]))
    check("and the time is still read", wawel["time"] == "17:07", wawel["time"])
    check("and the issuer is the ESPI symbol", wawel["issuer"] == "WAWEL SA", str(wawel["issuer"]))
    check("and the subject drops the issuer", wawel["subject"] == "Raport półroczny P", repr(wawel["subject"]))
    check("a populated report number is read", by_node["735230"]["number"] == "17/2026", by_node["735230"]["number"])

    # Title splitting, on the cases from the real page that break a naive split.
    check(
        "a subject containing its own ' - ' is not split twice",
        by_node["735226"]["issuer"] == "SYNEKTIK S.A."
        and by_node["735226"]["subject"].endswith("zmiana udziału w ogólnej liczbie głosów Spółki"),
        f"{by_node['735226']['issuer']!r} | {by_node['735226']['subject']!r}",
    )
    check(
        "a slash inside the issuer survives",
        by_node["735202"]["issuer"] == "Thorium Space/Thorium Space Spółka Akcyjna",
        str(by_node["735202"]["issuer"]),
    )
    check(
        "a double space after the separator is collapsed",
        by_node["735229"]["issuer"] == "BANCO SANTANDER S.A."
        and by_node["735229"]["subject"].startswith("Banco Santander share capital"),
        f"{by_node['735229']['issuer']!r} | {by_node['735229']['subject'][:40]!r}",
    )
    check(
        "an issuer with no legal form is read",
        by_node["735211"]["issuer"] == "RAFAMET",
        str(by_node["735211"]["issuer"]),
    )
    check(
        "a fund name with a code subject is read",
        by_node["735215"]["issuer"] == "EQUES AKUMULACJI MAJĄTKU FIZ"
        and by_node["735215"]["subject"] == "RB_FI_E_30.04.18",
        f"{by_node['735215']['issuer']!r} | {by_node['735215']['subject']!r}",
    )

    # A layout change must raise, not return an empty list that reads as "no filings".
    for label, broken in (
        ("an empty document", ""),
        ("a page with no newsList", "<html><body><p>nothing here</p></body></html>"),
        ("a page whose entry layout changed", listing_html.replace('class="news"', 'class="newsItem"')),
    ):
        try:
            espi.parse_listing(broken)
        except espi.EspiParseError as exc:
            check(f"{label} raises", True)
            named = any(token in str(exc) for token in ("newsList", "li.news", "Empty document"))
            check(f"  and names what was missing ({label})", named, str(exc)[:80])
        else:
            check(f"{label} raises", False, "returned instead of raising")

    # ── The report page ───────────────────────────────────────────────────────
    report_html = open(os.path.join(FIXTURES, "espi_report_periodic.html"), encoding="utf-8").read()
    report = espi.parse_report(report_html)
    check("the node id comes from the canonical link", report["nodeId"] == "735217", report["nodeId"])
    check("the source field is read", report["source"] == "ESPI", report["source"])
    check(
        "the report type is taken from the page, not guessed from the title",
        report["reportType"] == "formularz raportu półrocznego",
        report["reportType"],
    )
    check("the full issuer name is read", report["issuerName"] == "WAWEL SPÓŁKA AKCYJNA", report["issuerName"])
    check(
        "the ESPI symbol is read, and is what listings use",
        report["issuerSymbol"] == "WAWEL SA" and report["issuerSymbol"] == wawel["issuer"],
        f"{report['issuerSymbol']!r} vs listing {wawel['issuer']!r}",
    )
    check("the preparation date is read", report["preparedOn"] == "2026-08-21", report["preparedOn"])
    check("the sector is read", report["sector"].startswith("Spożywczy"), report["sector"])

    names = {"WWL.WA": report["issuerName"]}
    check(
        "the report's own symbol joins to its ticker",
        espi.match_ticker(report["issuerSymbol"], names) == "WWL.WA",
        f"{report['issuerSymbol']} vs {names}",
    )

    # Attachments: three real PDFs, deduplicated across the two tables that list
    # them, with the empty `/path` placeholder from the correction section dropped.
    files = [a["fileName"] for a in report["attachments"]]
    check("three attachments are found", len(files) == 3, str(files))
    check("they are deduplicated", len(files) == len(set(files)), str(files))
    check("all are PDFs", all(f.endswith(".pdf") for f in files), str(files))
    check("the empty '/path' placeholder is not an attachment", "path" not in files, str(files))
    check(
        "attachment urls are absolute and on the trusted host",
        all(a["url"].startswith("https://espiebi.pap.pl/download/attachment/735217/") for a in report["attachments"]),
        str([a["url"] for a in report["attachments"]][:1]),
    )

    # Selected financials — the "wyniki" the owner asked for, without a PDF.
    fin = report["financials"]
    check("the units are read", fin["units"] == "w tys.", fin["units"])
    check("both currencies are read", (fin["currency"], fin["secondaryCurrency"]) == ("PLN", "EUR"), str(fin))
    items = {i["item"]: i for i in fin["items"]}
    check("revenue is parsed", items["Przychody"]["current"] == 302427.0, str(items.get("Przychody")))
    check("and its comparative", items["Przychody"]["previous"] == 328120.0)
    check("and its EUR column", items["Przychody"]["currentSecondary"] == 71122.0)
    check("net profit is parsed", items["Zysk netto z działalności kontynuowanej"]["current"] == 41755.0)
    check(
        "a negative cash flow keeps its sign",
        items["Przepływy pieniężne netto z działalności inwestycyjnej"]["current"] == -28632.0,
        str(items.get("Przepływy pieniężne netto z działalności inwestycyjnej")),
    )
    check("a decimal figure is parsed", items["Zysk (strata) na jedną akcję zwykłą (w zł / EUR)"]["current"] == 32.32)
    check("header and footnote rows are not read as data", "WYBRANE DANE FINANSOWE" not in items, str(list(items)[:3]))

    # Polish number formatting, directly.
    for raw, expected in (("302 427,00", 302427.0), ("-28 632,00", -28632.0), ("32,32", 32.32), ("1 291 846,00", 1291846.0)):
        check(f"{raw!r} -> {expected}", espi.parse_polish_number(raw) == expected, str(espi.parse_polish_number(raw)))
    for raw in ("", "  ", "w tys.", "PLN", "półrocze /", "abc"):
        check(f"{raw!r} is not a number", espi.parse_polish_number(raw) is None, str(espi.parse_polish_number(raw)))

    for label, broken in (
        ("an empty document", ""),
        ("a page with no nDokument table", "<html><body><table><tr><td>a</td></tr></table></body></html>"),
    ):
        try:
            espi.parse_report(broken)
        except espi.EspiParseError:
            check(f"a report page without its identity table raises ({label})", True)
        else:
            check(f"a report page without its identity table raises ({label})", False)

    # ── The unified URL builder ───────────────────────────────────────────────
    check("a query-only request is a search", "search=MIRBUD" in espi.search_url(query="MIRBUD"))
    check("a query-only request sends no dates", "created=" not in espi.search_url(query="MIRBUD"))
    window = espi.search_url(start=date(2026, 8, 21), end=date(2026, 8, 21))
    check("a window request sends both dates", "created=2026-08-21" in window and "enddate=2026-08-21" in window, window)
    check("and the end time, encoded", "23%3A59" in window, window)
    both = espi.search_url(query="LPP", start=date(2026, 1, 1), end=date(2026, 8, 21), page=2)
    check("a query and a window combine", "search=LPP" in both and "created=2026-01-01" in both and "page=2" in both, both)
    check("a phrase is encoded", "search=CD+PROJEKT" in espi.search_url(query="CD PROJEKT"), espi.search_url(query="CD PROJEKT"))
    try:
        espi.search_url()
    except ValueError:
        check("a request with neither dates nor a query is refused", True)
    else:
        check("a request with neither dates nor a query is refused", False)

    # ── Fetching, paging and truncation, with the network injected out ────────
    listing_html = open(os.path.join(FIXTURES, "espi_listing.html"), encoding="utf-8").read()
    empty_page = '<ul class="newsList"></ul>'

    calls = []

    def fake_get(pages):
        def get(url):
            calls.append(url)
            index = int(url.rsplit("page=", 1)[1])
            return pages[index] if index < len(pages) else empty_page
        return get

    calls.clear()
    one = espi.fetch_listing(query="MIRBUD", max_pages=3, get=fake_get([listing_html]))
    check("a full page then an empty one stops paging", len(calls) == 2, str(len(calls)))
    check("and yields that page's entries", len(one["entries"]) == 30, str(len(one["entries"])))
    check("and is not reported truncated", one["truncated"] is False)

    calls.clear()
    capped = espi.fetch_listing(query="X", max_pages=2, get=fake_get([listing_html, listing_html]))
    check("hitting the page cap stops there", len(calls) == 2, str(len(calls)))
    check("and says so, rather than presenting a capped answer as complete", capped["truncated"] is True)

    # The same node on two pages must not be counted twice.
    calls.clear()
    deduped = espi.fetch_listing(query="X", max_pages=3, get=fake_get([listing_html, listing_html, empty_page]))
    check("repeated nodes across pages are deduplicated", len(deduped["entries"]) == 30, str(len(deduped["entries"])))

    calls.clear()
    quiet = espi.fetch_listing(query="NOBODY", max_pages=3, get=fake_get([]))
    check("a quiet query returns nothing without raising", quiet["entries"] == [] and quiet["truncated"] is False)
    check("and stops after one page", len(calls) == 1, str(len(calls)))

    # ── The digest queries per holding and confirms the match ─────────────────
    def digest_get(url):
        return listing_html

    result = espi.digest_for_holdings(
        {"WWL.WA": "WAWEL SPÓŁKA AKCYJNA", "SNK.WA": "Synektik S.A."},
        date(2026, 8, 21),
        date(2026, 8, 21),
        get=digest_get,
    )
    tickers = {e["matchedTicker"] for e in result["entries"]}
    check("the digest matches both holdings", tickers == {"WWL.WA", "SNK.WA"}, str(tickers))
    check("WAWEL's one filing is found", result["byTicker"].get("WWL.WA") == 1, str(result["byTicker"]))
    check("Synektik's two filings are found", result["byTicker"].get("SNK.WA") == 2, str(result["byTicker"]))
    check(
        "and the other 27 issuers on the page are excluded",
        len(result["entries"]) == 3,
        str(len(result["entries"])),
    )
    check("entries are newest first", [e["time"] for e in result["entries"]] == sorted([e["time"] for e in result["entries"]], reverse=True))
    check("the queried tickers are reported", result["queriedTickers"] == ["SNK.WA", "WWL.WA"], str(result["queriedTickers"]))

    # One issuer failing must not lose the digest.
    def flaky_get(url):
        if "WAWEL" in url:
            raise RuntimeError("boom")
        return listing_html

    partial = espi.digest_for_holdings(
        {"WWL.WA": "WAWEL SPÓŁKA AKCYJNA", "SNK.WA": "Synektik S.A."},
        date(2026, 8, 21),
        date(2026, 8, 21),
        get=flaky_get,
    )
    check("a failing issuer is reported, not swallowed", "WWL.WA" in partial["failures"], str(partial["failures"]))
    check("and the rest of the digest survives", partial["byTicker"].get("SNK.WA") == 2, str(partial["byTicker"]))

    # A holding with no resolved name is skipped rather than searched for "".
    blank = espi.digest_for_holdings({"AAA.WA": ""}, date(2026, 8, 21), date(2026, 8, 21), get=digest_get)
    check("a holding with no name is skipped", blank["entries"] == [] and blank["byTicker"] == {})

    # ── fetch_report goes through the node URL ────────────────────────────────
    report_html = open(os.path.join(FIXTURES, "espi_report_periodic.html"), encoding="utf-8").read()
    seen_urls = []

    def report_get(url):
        seen_urls.append(url)
        return report_html

    fetched = espi.fetch_report(735217, get=report_get)
    check("fetch_report requests the node permalink", seen_urls == ["https://espiebi.pap.pl/node/735217"], str(seen_urls))
    check("and returns the parsed report", fetched["issuerSymbol"] == "WAWEL SA", fetched["issuerSymbol"])

    # ── Which holdings the digest searches for, and how names are kept ────────
    config = {
        "LPP.WA": {"country": "POL"},
        "CDR.WA": {"country": "POL"},
        "NVDA": {"country": "USA"},
        "7974.T": {"country": "JPN"},
        "SOMETHING.WA": {"country": ""},
    }
    check(
        "Polish holdings are selected by country or suffix",
        espi.polish_tickers(config) == ["CDR.WA", "LPP.WA", "SOMETHING.WA"],
        str(espi.polish_tickers(config)),
    )
    check("a US holding is not Polish", "NVDA" not in espi.polish_tickers(config))
    check("an empty config yields nothing", espi.polish_tickers({}) == [])
    check("a missing config yields nothing", espi.polish_tickers(None) == [])

    # A recorded name must survive a provider lookup: it may have been corrected
    # by hand, or taken from a report's own Symbol Emitenta, which beats any
    # provider's long name.
    merged = espi.merge_issuer_names(
        {"LPP.WA": "LPP SA"},
        {"LPP.WA": "LPP S.A. Group Holding", "CDR.WA": "CD Projekt S.A."},
        ["LPP.WA", "CDR.WA"],
    )
    check("a cached name wins over a fresh lookup", merged["LPP.WA"] == "LPP SA", str(merged))
    check("and a missing one is filled in", merged["CDR.WA"] == "CD Projekt S.A.", str(merged))
    check(
        "a ticker no longer in the book is dropped",
        espi.merge_issuer_names({"OLD.WA": "Gone SA"}, {}, ["LPP.WA"]) == {},
        str(espi.merge_issuer_names({"OLD.WA": "Gone SA"}, {}, ["LPP.WA"])),
    )
    check(
        "a blank name is not recorded",
        espi.merge_issuer_names({"LPP.WA": "   "}, {"LPP.WA": ""}, ["LPP.WA"]) == {},
    )
    check("no cache and no lookup yields nothing", espi.merge_issuer_names(None, None, ["LPP.WA"]) == {})

    # ---- the search-results page, and the empty one -----------------------
    print("Search results page (?search=XTB)")
    search_html = open(os.path.join(FIXTURES, "espi_search_results.html"), encoding="utf-8").read()
    empty_html = open(os.path.join(FIXTURES, "espi_search_empty.html"), encoding="utf-8").read()

    search_entries = espi.parse_listing(search_html)
    # The search page turned out to use the same markup as the dated listing, so
    # one parser serves both. This fixture is what proves it rather than assumes it.
    check("the search page parses", len(search_entries) == 30, str(len(search_entries)))
    check(
        "every row is the issuer that was searched for",
        {espi.normalise_issuer_name(e["issuer"]) for e in search_entries} == {"xtb"},
        str({e["issuer"] for e in search_entries}),
    )
    check(
        "dates come from the page, so a query without dates spans many days",
        len({e["date"] for e in search_entries}) > 10,
        str(len({e["date"] for e in search_entries})),
    )
    check(
        "the EBi badge is still classified",
        any(e["source"] == "EBI" for e in search_entries),
        str({e["source"] for e in search_entries}),
    )
    check(
        "an empty report number is tolerated here too",
        any(not e["number"] for e in search_entries),
    )

    print("A search that matches nothing is not a broken parser")
    # This is the bug the owner hit. PAP renders no `ul.newsList` at all when a
    # phrase matches nothing, and raising for it reported "the layout changed"
    # for the ordinary case of a query with no filings.
    check("an empty result set returns no entries", espi.parse_listing(empty_html) == [])
    check(
        "the empty page is still recognised as a results page",
        "view-id-wszukiwarka" in empty_html,
    )
    # A page that is genuinely not the search view must still raise, or a
    # redirect or a rename would read as "nothing filed".
    for label, html in (
        ("a report page", "<html><body><div class='nDokument'>x</div></body></html>"),
        ("a renamed view", empty_html.replace("view-id-wszukiwarka", "view-id-renamed").replace("path-wyszukiwarka", "path-renamed")),
    ):
        try:
            espi.parse_listing(html)
            check(f"{label} raises rather than reporting zero filings", False)
        except espi.EspiParseError as error:
            check(f"{label} raises rather than reporting zero filings", "results page" in str(error), str(error))

    print("PAP's search is case-sensitive, so one retry in upper case")
    requested: list[str] = []

    def case_sensitive_get(url):
        requested.append(url)
        return search_html if "search=XTB" in url else empty_html

    result = espi.fetch_listing(query="xtb", max_pages=1, get=case_sensitive_get)
    check("a lower-case query still finds the filings", len(result["entries"]) == 30, str(len(result["entries"])))
    check("and says which spelling worked", result["retriedQuery"] == "XTB", str(result["retriedQuery"]))
    check("the retry happened only after the first attempt came back empty", len(requested) == 2, str(requested))
    check("the first attempt used what was typed", "search=xtb&" in requested[0], requested[0])

    # A phrase that matches nothing in either case must not claim a retry helped.
    quiet = espi.fetch_listing(query="zzzqqq", max_pages=1, get=lambda url: empty_html)
    check("a genuinely absent phrase returns nothing", quiet["entries"] == [])
    check("and reports no successful retry", quiet["retriedQuery"] is None, str(quiet["retriedQuery"]))
    # An already-upper-case query must not cost a second request set.
    upper_calls: list[str] = []
    espi.fetch_listing(query="ZZZQQQ", max_pages=1, get=lambda url: (upper_calls.append(url), empty_html)[1])
    check("an upper-case query is not retried", len(upper_calls) == 1, str(upper_calls))

    print("Candidates from a single-issuer search")
    candidates = espi.issuer_candidates(search_entries)
    check("the issuer is offered as a candidate", any(c["name"] == "XTB" for c in candidates), str(candidates[:2]))
    check(
        "the ticker root marks it",
        espi.candidate_starts_with_root("XTB", "XTB.WA"),
    )

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED:")
        for failure in FAILURES:
            print(f"  - {failure}")
        sys.exit(1)
    print("All ESPI source checks passed.")


if __name__ == "__main__":
    main()
