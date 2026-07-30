"""Append one row per lead to a Google Sheet.

gspread is synchronous, so writes run in a thread to avoid blocking the event loop.
The header row is created on first write so a brand-new sheet just works.
"""

import base64
import json
import logging
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

from app.config import get_settings
from app.models import Lead, LeadIntelligence

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

HEADERS = [
    "timestamp",
    "full_name",
    "email",
    "phone",
    "website",
    "linkedin_url",
    "industry",
    "niche",
    "primary_service",
    "company_size_signal",
    "icp_score",
    "icp_reason",
    "icebreaker",
    "data_confidence",
    "sources",
    "status",
    "error",
]


def _worksheet():
    settings = get_settings()
    if not settings.google_service_account_b64:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_B64 is not set")
    if not settings.google_sheet_id:
        raise RuntimeError("GOOGLE_SHEET_ID is not set")

    info = json.loads(base64.b64decode(settings.google_service_account_b64))
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    spreadsheet = gspread.authorize(creds).open_by_key(settings.google_sheet_id)

    try:
        worksheet = spreadsheet.worksheet(settings.google_sheet_tab)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=settings.google_sheet_tab, rows=1000, cols=len(HEADERS)
        )

    if not worksheet.row_values(1):
        worksheet.append_row(HEADERS, value_input_option="RAW")

    return worksheet


def _row(
    lead: Lead,
    intel: LeadIntelligence | None,
    sources: str,
    status: str,
    error: str,
) -> list:
    return [
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        lead.full_name,
        lead.email,
        lead.phone,
        lead.website,
        lead.linkedin_url,
        intel.industry if intel else "",
        intel.niche if intel else "",
        intel.primary_service if intel else "",
        intel.company_size_signal if intel else "",
        intel.icp_score if intel else "",
        intel.icp_reason if intel else "",
        intel.icebreaker if intel else "",
        intel.data_confidence if intel else "",
        sources,
        status,
        error[:500],
    ]


def _append_sync(row: list) -> None:
    _worksheet().append_row(row, value_input_option="RAW")


async def append_lead(
    lead: Lead,
    intel: LeadIntelligence | None = None,
    sources: str = "",
    status: str = "ok",
    error: str = "",
) -> None:
    import asyncio

    row = _row(lead, intel, sources, status, error)
    await asyncio.to_thread(_append_sync, row)
    log.info("Wrote row for %s (status=%s)", lead.email or lead.event_id, status)
