from typing import Literal

from pydantic import BaseModel, Field


class Lead(BaseModel):
    """What the lead typed into the Typeform."""

    event_id: str
    submitted_at: str
    full_name: str = ""
    email: str = ""
    phone: str = ""
    website: str = ""
    linkedin_url: str = ""

    def is_enrichable(self) -> bool:
        return bool(self.website or self.linkedin_url)


class ScrapeResult(BaseModel):
    """One source's worth of scraped text, or the reason we don't have it."""

    ok: bool = False
    text: str = ""
    error: str = ""

    @property
    def summary(self) -> str:
        return self.text if self.ok else f"[unavailable: {self.error}]"


class EnrichmentBundle(BaseModel):
    linkedin: ScrapeResult = Field(default_factory=ScrapeResult)
    website: ScrapeResult = Field(default_factory=ScrapeResult)

    def has_any_data(self) -> bool:
        return self.linkedin.ok or self.website.ok

    def sources_note(self) -> str:
        parts = []
        parts.append("LinkedIn: scraped" if self.linkedin.ok else f"LinkedIn: {self.linkedin.error or 'not provided'}")
        parts.append("Website: scraped" if self.website.ok else f"Website: {self.website.error or 'not provided'}")
        return " | ".join(parts)


class LeadIntelligence(BaseModel):
    """Claude's analysis. This schema is enforced by the API, not by parsing.

    Constraint note: the structured-output schema compiler supports `enum` but not
    numeric min/max, so `icp_score` is a Literal (which compiles to an enum) rather
    than an int with ge/le. That is what guarantees you never get "8/10" or 11 in
    the sheet.
    """

    industry: str = Field(
        description="The broad industry the lead's company operates in, e.g. 'B2B SaaS', "
        "'Commercial real estate'. Use 'Unknown' if the data does not support a call."
    )
    niche: str = Field(
        description="The specific sub-segment or vertical they focus on within that "
        "industry, e.g. 'Series A fintech startups', 'Dental practice acquisitions'."
    )
    primary_service: str = Field(
        description="The single main thing they sell or deliver, in one sentence, "
        "phrased the way they would describe it."
    )
    company_size_signal: str = Field(
        description="Best evidence of headcount or company stage found in the data "
        "(e.g. 'LinkedIn shows 11-50 employees', 'Solo founder, no team mentioned'). "
        "Say 'No signal found' rather than guessing."
    )
    icp_score: Literal[1, 2, 3, 4, 5, 6, 7, 8, 9, 10] = Field(
        description="How well this lead fits our ICP, per the rubric. Use the full "
        "range — most leads are not 7s."
    )
    icp_reason: str = Field(
        description="2-4 sentences: why this exact score against the rubric, what "
        "specifically makes them a good or bad fit for our service, and how they would "
        "integrate with what we do. Cite concrete evidence from the scraped data. If "
        "the score is low, name the disqualifier explicitly."
    )
    icebreaker: str = Field(
        description="One or two sentences the rep can say to this lead, following the "
        "icebreaker guidance. Must reference a specific verifiable detail."
    )
    data_confidence: Literal["high", "medium", "low"] = Field(
        description="How much scraped evidence backed this analysis. 'low' means the "
        "rep should treat the score as a guess."
    )
