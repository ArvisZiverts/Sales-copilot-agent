"""LLM analysis: turn scraped text into a scored, actionable lead brief.

Provider: OpenAI, via the Responses API with structured outputs
(`responses.parse` + a Pydantic model). `icp_score` is guaranteed to be an integer
1-10 and every field is guaranteed present — no JSON parsing, no "sometimes it
returns 8/10" bugs downstream.

This module is the only place the provider appears. `pipeline.py` imports `analyze`
and knows nothing about OpenAI, so swapping providers again is a one-file change.
"""

import logging

from openai import AsyncOpenAI

from app.config import get_settings
from app.icp import company_name, render_icp
from app.models import EnrichmentBundle, Lead, LeadIntelligence

log = logging.getLogger(__name__)

INSTRUCTIONS = """\
You are the research analyst for {company}'s sales team. A lead has just filled out \
our inbound form. You have been given whatever we could scrape from their LinkedIn \
profile and their company website.

Your job: extract the firmographics, score how well they fit our ideal customer \
profile, justify that score, and write one icebreaker the rep can actually use.

Here is everything you need to know about what we sell and who we sell to:

<icp_profile>
{icp}
</icp_profile>

How to do this well:

- Ground every claim in the scraped data. If the data does not support a conclusion, \
say so plainly rather than inferring. "No signal found" is a valid and useful answer; \
an invented detail is worse than a blank field because the rep will repeat it on a call.
- Score against the rubric anchors, not against a gut feeling. Use the full 1-10 range. \
If most leads come out as 7s the scoring is worthless — a 7 must mean something \
different from a 4. Check the hard disqualifiers before anything else; if one applies, \
the score is 1-2 regardless of how impressive the company looks.
- The icp_reason is written for a rep deciding whether to spend an hour on this person. \
Tell them what specifically makes this a good or bad fit and how the lead would \
actually work with our service — not a summary of the company.
- The icebreaker must reference one concrete, verifiable detail from the scraped data. \
Follow the icebreaker guidance in the profile exactly, including its tone rules. If the \
scraped data is too thin to reference anything specific, write \
"Insufficient data for a personalised opener" rather than a generic compliment.
- Be honest in data_confidence. If only one source scraped, or the content was thin, \
that is medium or low.
"""

USER_TEMPLATE = """\
<lead_form_submission>
Name: {name}
Email: {email}
Phone: {phone}
Website: {website}
LinkedIn: {linkedin}
</lead_form_submission>

<scrape_status>
{sources}
</scrape_status>

<linkedin_profile>
{linkedin_text}
</linkedin_profile>

<company_website>
{website_text}
</company_website>

Analyse this lead and return the structured brief."""


def _refusal_text(response) -> str | None:
    """OpenAI signals a safety refusal as a content item, not an exception."""
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) != "message":
            continue
        for block in getattr(item, "content", []) or []:
            if getattr(block, "type", None) == "refusal":
                return getattr(block, "refusal", "refused")
    return None


async def analyze(lead: Lead, bundle: EnrichmentBundle) -> LeadIntelligence:
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    instructions = INSTRUCTIONS.format(company=company_name(), icp=render_icp())
    user = USER_TEMPLATE.format(
        name=lead.full_name or "(not provided)",
        email=lead.email or "(not provided)",
        phone=lead.phone or "(not provided)",
        website=lead.website or "(not provided)",
        linkedin=lead.linkedin_url or "(not provided)",
        sources=bundle.sources_note(),
        linkedin_text=bundle.linkedin.summary,
        website_text=bundle.website.summary,
    )

    response = await client.responses.parse(
        model=settings.openai_model,
        instructions=instructions,
        input=[{"role": "user", "content": user}],
        text_format=LeadIntelligence,
        # gpt-5-mini is a reasoning model: reasoning tokens count against
        # max_output_tokens, so keep this generous or briefs truncate before the
        # structured object is complete.
        reasoning={"effort": settings.openai_reasoning_effort},
        max_output_tokens=16000,
    )

    refusal = _refusal_text(response)
    if refusal:
        raise RuntimeError(f"Model refused to analyse this lead: {refusal}")

    if response.output_parsed is None:
        raise RuntimeError(
            f"Structured output was empty (status={getattr(response, 'status', 'unknown')}, "
            f"incomplete={getattr(response, 'incomplete_details', None)})"
        )

    usage = response.usage
    log.info(
        "Analysis complete — score=%s in=%s out=%s",
        response.output_parsed.icp_score,
        getattr(usage, "input_tokens", "?"),
        getattr(usage, "output_tokens", "?"),
    )
    return response.output_parsed
