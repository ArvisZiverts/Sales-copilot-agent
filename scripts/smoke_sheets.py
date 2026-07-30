"""Write a test row to the Google Sheet.

    python -m scripts.smoke_sheets

If this 403s, the sheet is not shared with the service account. Open the service
account JSON, copy `client_email`, and share the sheet with that address as Editor.
"""

import asyncio

from app.clients.sheets import append_lead
from app.models import Lead, LeadIntelligence


async def main() -> None:
    lead = Lead(
        event_id="smoke_test",
        submitted_at="",
        full_name="SMOKE TEST — delete this row",
        email="smoke@example.com",
        phone="+10000000000",
        website="https://example.com",
        linkedin_url="https://linkedin.com/in/example",
    )
    intel = LeadIntelligence(
        industry="Test",
        niche="Test",
        primary_service="Test",
        company_size_signal="Test",
        icp_score=5,
        icp_reason="This row was written by scripts/smoke_sheets.py.",
        icebreaker="If you can read this, Sheets auth works.",
        data_confidence="low",
    )

    await append_lead(lead, intel=intel, sources="smoke test", status="ok")
    print("Row written. Check the sheet, then delete it.")


if __name__ == "__main__":
    asyncio.run(main())
