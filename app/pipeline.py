"""Enrich → analyse → write. Runs as a background task after the webhook is acked.

Contract: this function never raises. Every path writes exactly one sheet row, so a
lead can be degraded but never silently lost.
"""

import logging

from app.clients import apify, llm, sheets
from app.models import EnrichmentBundle, Lead

log = logging.getLogger(__name__)


async def process_lead(lead: Lead) -> None:
    log.info("Processing lead %s (%s)", lead.event_id, lead.email or "no email")

    bundle = EnrichmentBundle()
    sources = ""

    try:
        if not lead.is_enrichable():
            await sheets.append_lead(
                lead,
                status="skipped",
                error="No website or LinkedIn URL submitted — nothing to enrich",
            )
            return

        bundle = await apify.enrich(lead.linkedin_url, lead.website)
        sources = bundle.sources_note()

        if not bundle.has_any_data():
            await sheets.append_lead(
                lead,
                sources=sources,
                status="enrichment_failed",
                error="Both scrapers returned nothing; lead not scored",
            )
            return

        intel = await llm.analyze(lead, bundle)

        status = "ok" if (bundle.linkedin.ok and bundle.website.ok) else "partial"
        await sheets.append_lead(lead, intel=intel, sources=sources, status=status)

    except Exception as exc:  # noqa: BLE001 - the lead must reach the sheet regardless
        log.exception("Pipeline failed for %s", lead.event_id)
        try:
            await sheets.append_lead(
                lead,
                sources=sources or bundle.sources_note(),
                status="error",
                error=f"{type(exc).__name__}: {exc}",
            )
        except Exception:  # noqa: BLE001 - sheet itself is down; log loudly and move on
            log.exception("Could not write failure row for %s — LEAD DATA: %s", lead.event_id, lead.model_dump())
