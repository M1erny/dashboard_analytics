"""Focused checks for SEC filing intent parsing and result ranking."""

import brain_agent


COMPANIES = {
    "0": {"ticker": "META", "title": "Meta Platforms, Inc.", "cik_str": 1326801},
    "1": {"ticker": "TSLA", "title": "Tesla, Inc.", "cik_str": 1318605},
}

RECENT = {
    "form": ["8-K", "10-Q", "10-K", "10-K"],
    "accessionNumber": ["0001-26-000004", "0001-26-000003", "0001-26-000002", "0001-25-000001"],
    "primaryDocument": ["meta-8k.htm", "meta-10q.htm", "meta-2025-10k.htm", "meta-2024-10k.htm"],
    "filingDate": ["2026-05-29", "2026-04-30", "2026-01-29", "2025-01-30"],
    "reportDate": ["2026-05-27", "2026-03-31", "2025-12-31", "2024-12-31"],
    "primaryDocDescription": ["Current report", "Quarterly report", "Annual report", "Annual report"],
}

ARCHIVE = {
    "form": ["8-K", "10-K"],
    "accessionNumber": ["0001-20-000002", "0001-21-000001"],
    "primaryDocument": ["meta-old-8k.htm", "meta-2020-10k.htm"],
    "filingDate": ["2020-08-01", "2021-01-28"],
    "reportDate": ["2020-07-30", "2020-12-31"],
    "primaryDocDescription": ["Current report", "Annual report"],
}

SUBMISSIONS = {
    "filings": {
        "recent": RECENT,
        "files": [{
            "name": "CIK0001326801-submissions-001.json",
            "filingFrom": "2017-02-23",
            "filingTo": "2024-05-15",
        }],
    },
}


def fake_sec_get_json(url):
    if url == brain_agent.SEC_COMPANY_TICKERS_URL:
        return COMPANIES
    if url == brain_agent.SEC_SUBMISSIONS_URL.format(cik="0001326801"):
        return SUBMISSIONS
    if url.endswith("CIK0001326801-submissions-001.json"):
        return ARCHIVE
    raise AssertionError(f"Unexpected SEC URL: {url}")


real_sec_get_json = brain_agent._sec_get_json
brain_agent._sec_get_json = fake_sec_get_json
try:
    latest_annual = brain_agent.find_official_source_candidates(task="META 10-K", limit=10)
    assert latest_annual["resolvedCompany"]["ticker"] == "META"
    assert latest_annual["intent"]["requestedForms"] == ["10-K"]
    assert [candidate["form"] for candidate in latest_annual["candidates"]] == ["10-K", "10-K"]
    assert latest_annual["candidates"][0]["title"] == "META FY 2025 10-K"
    assert latest_annual["candidates"][0]["isBestMatch"] is True
    assert brain_agent.resolve_sec_company(company="Tesla 10-K")["ticker"] == "TSLA"

    fiscal_year = brain_agent.find_official_source_candidates(task="META 2025 10-K", limit=10)
    assert fiscal_year["candidates"][0]["reportDate"] == "2025-12-31"
    assert fiscal_year["candidates"][0]["isExactMatch"] is True
    assert fiscal_year["candidates"][1]["reportDate"] == "2024-12-31"
    assert fiscal_year["candidates"][1]["isExactMatch"] is False

    quarter = brain_agent.find_official_source_candidates(task="META Q1 2026 10-Q", limit=10)
    assert len(quarter["candidates"]) == 1
    assert quarter["candidates"][0]["title"] == "META Q1 2026 10-Q"
    assert quarter["candidates"][0]["isExactMatch"] is True

    historical = brain_agent.find_official_source_candidates(task="META 2020 10-K", limit=3)
    assert historical["searched"]["archivesLoaded"] == 1
    assert historical["candidates"][0]["title"] == "META FY 2020 10-K"
    assert historical["candidates"][0]["isExactMatch"] is True

    proxy_intent = brain_agent._filing_search_intent("META proxy statement 2025")
    assert proxy_intent["requestedForms"] == ["DEF 14A"]
    assert brain_agent._filing_is_in_results_window("2026-01-28", quarter=4, years={"2025"}) is True
    assert brain_agent._filing_is_in_results_window("2026-04-29", quarter=4, years={"2025"}) is False
    assert brain_agent._document_has_target_quarter("meta-12312025xexhibit991.htm", quarter=4, year="2025") is True
finally:
    brain_agent._sec_get_json = real_sec_get_json


print("Research Agent SEC search checks passed.")
