"""Pipeline tests with every external client mocked.

The invariant under test: exactly one sheet row is written on every path, including
failures. If that breaks, leads disappear.
"""

import pytest

from app import pipeline
from app.models import EnrichmentBundle, Lead, LeadIntelligence, ScrapeResult


@pytest.fixture
def lead():
    return Lead(
        event_id="evt_1",
        submitted_at="2026-07-30T10:00:00Z",
        full_name="Dana Whitfield",
        email="dana@northgateops.com",
        website="https://northgateops.com",
        linkedin_url="https://linkedin.com/in/example-lead-not-a-real-profile",
    )


@pytest.fixture
def intel():
    return LeadIntelligence(
        industry="B2B professional services",
        niche="Ops consulting for mid-market logistics",
        primary_service="Fractional COO engagements",
        company_size_signal="LinkedIn shows 11-50 employees",
        icp_score=8,
        icp_reason="Right size and industry with a visible manual workflow.",
        icebreaker="You list three onboarding tracks for enterprise clients.",
        data_confidence="high",
    )


@pytest.fixture
def captured(monkeypatch):
    """Capture every sheets.append_lead call instead of hitting Google."""
    rows = []

    async def fake_append(lead, intel=None, sources="", status="ok", error=""):
        rows.append({"lead": lead, "intel": intel, "status": status, "error": error})

    monkeypatch.setattr(pipeline.sheets, "append_lead", fake_append)
    return rows


def _bundle(linkedin_ok=True, website_ok=True):
    return EnrichmentBundle(
        linkedin=ScrapeResult(ok=linkedin_ok, text="profile" if linkedin_ok else "", error="" if linkedin_ok else "private"),
        website=ScrapeResult(ok=website_ok, text="site" if website_ok else "", error="" if website_ok else "404"),
    )


@pytest.mark.asyncio
async def test_happy_path_writes_ok_row(lead, intel, captured, monkeypatch):
    async def fake_enrich(li, ws):
        return _bundle()

    async def fake_analyze(lead, bundle):
        return intel

    monkeypatch.setattr(pipeline.apify, "enrich", fake_enrich)
    monkeypatch.setattr(pipeline.llm, "analyze", fake_analyze)

    await pipeline.process_lead(lead)

    assert len(captured) == 1
    assert captured[0]["status"] == "ok"
    assert captured[0]["intel"].icp_score == 8


@pytest.mark.asyncio
async def test_linkedin_failure_still_scores_and_flags_partial(lead, intel, captured, monkeypatch):
    async def fake_enrich(li, ws):
        return _bundle(linkedin_ok=False)

    async def fake_analyze(lead, bundle):
        return intel

    monkeypatch.setattr(pipeline.apify, "enrich", fake_enrich)
    monkeypatch.setattr(pipeline.llm, "analyze", fake_analyze)

    await pipeline.process_lead(lead)

    assert len(captured) == 1
    assert captured[0]["status"] == "partial"
    assert captured[0]["intel"] is not None


@pytest.mark.asyncio
async def test_both_scrapers_dead_writes_failure_row_without_calling_llm(lead, captured, monkeypatch):
    async def fake_enrich(li, ws):
        return _bundle(linkedin_ok=False, website_ok=False)

    async def boom(lead, bundle):
        raise AssertionError("the model must not be called with no data")

    monkeypatch.setattr(pipeline.apify, "enrich", fake_enrich)
    monkeypatch.setattr(pipeline.llm, "analyze", boom)

    await pipeline.process_lead(lead)

    assert len(captured) == 1
    assert captured[0]["status"] == "enrichment_failed"


@pytest.mark.asyncio
async def test_llm_failure_writes_error_row(lead, captured, monkeypatch):
    async def fake_enrich(li, ws):
        return _bundle()

    async def fake_analyze(lead, bundle):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(pipeline.apify, "enrich", fake_enrich)
    monkeypatch.setattr(pipeline.llm, "analyze", fake_analyze)

    await pipeline.process_lead(lead)

    assert len(captured) == 1
    assert captured[0]["status"] == "error"
    assert "rate limited" in captured[0]["error"]


@pytest.mark.asyncio
async def test_lead_with_no_urls_is_skipped_not_dropped(captured, monkeypatch):
    bare = Lead(event_id="evt_2", submitted_at="", full_name="Nobody", email="a@b.com")

    async def boom(*args, **kwargs):
        raise AssertionError("must not call Apify with nothing to scrape")

    monkeypatch.setattr(pipeline.apify, "enrich", boom)

    await pipeline.process_lead(bare)

    assert len(captured) == 1
    assert captured[0]["status"] == "skipped"


@pytest.mark.asyncio
async def test_process_lead_never_raises(lead, monkeypatch):
    """Even total collapse must not escape into the background task runner."""

    async def fake_enrich(li, ws):
        raise RuntimeError("apify down")

    async def fake_append(*args, **kwargs):
        raise RuntimeError("sheets down too")

    monkeypatch.setattr(pipeline.apify, "enrich", fake_enrich)
    monkeypatch.setattr(pipeline.sheets, "append_lead", fake_append)

    await pipeline.process_lead(lead)  # must not raise
