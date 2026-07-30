"""Apify scrapers for the lead's LinkedIn profile and company website.

Both use the run-sync-get-dataset-items endpoint: one HTTP call that blocks until
the actor finishes and returns the dataset. Simpler than run + poll, and our actors
finish inside the timeout.

Actors (approved 2026-07-30):
  harvestapi~linkedin-profile-scraper   $4 / 1000 profiles, no cookies or LI account
  apify~website-content-crawler         ~$0.20-0.50 / 1000 pages, markdown output
"""

import logging
import re

import httpx

from app.config import get_settings
from app.models import EnrichmentBundle, ScrapeResult

log = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com/v2"

# Enough context for a good judgement, short of burning tokens on nav boilerplate.
MAX_LINKEDIN_CHARS = 12_000
MAX_WEBSITE_CHARS = 20_000


async def _run_actor(client: httpx.AsyncClient, actor: str, payload: dict) -> list[dict]:
    settings = get_settings()
    url = f"{APIFY_BASE}/acts/{actor}/run-sync-get-dataset-items"
    response = await client.post(
        url,
        params={"token": settings.apify_token},
        json=payload,
        timeout=httpx.Timeout(settings.apify_timeout_seconds, connect=15.0),
    )
    response.raise_for_status()
    items = response.json()
    return items if isinstance(items, list) else []


def _plain(value) -> str:
    """Flatten the actor's nested objects (location, etc.) into readable text.

    Several fields come back as dicts — `location` is
    {"linkedinText": ..., "parsed": {...}}. Interpolating those raw puts JSON in the
    model's context and wastes tokens on noise.
    """
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("linkedinText", "text", "name", "label", "title"):
            if value.get(key):
                return str(value[key])
        parsed = value.get("parsed")
        if isinstance(parsed, dict) and parsed.get("text"):
            return str(parsed["text"])
        return ""
    return str(value).strip()


def _flatten_linkedin(item: dict) -> str:
    """Render the profile into readable text for the model.

    Field names verified against harvestapi/linkedin-profile-scraper output on
    2026-07-30. If the actor changes its schema, `scripts/smoke_apify.py` shows it
    immediately as missing lines.
    """
    lines: list[str] = []

    name = " ".join(p for p in (item.get("firstName"), item.get("lastName")) if p).strip()
    if name:
        lines.append(f"Name: {name}")

    for label, key in (
        ("Headline", "headline"),
        ("Location", "location"),
        ("About", "about"),
    ):
        value = _plain(item.get(key))
        if value:
            lines.append(f"{label}: {value}" if key != "about" else f"\nAbout:\n{value}")

    # Reach, not connections. connectionsCount saturates (it reads 8 for a profile
    # with 40M followers), so it is worse than useless as a size signal.
    followers = item.get("followerCount")
    if isinstance(followers, int) and followers:
        lines.append(f"Followers: {followers:,}")

    # Status flags that bear directly on ICP fit: `hiring` suggests they are solving
    # a workflow problem with headcount; `openToWork` usually means job seeker.
    flags = [name for name, key in (("hiring", "hiring"), ("open to work", "openToWork"),
                                    ("LinkedIn influencer", "influencer"), ("creator", "creator"))
             if item.get(key)]
    if flags:
        lines.append(f"Profile flags: {', '.join(flags)}")

    sites = [s for s in (item.get("websites") or []) if isinstance(s, str)]
    if sites:
        lines.append(f"Listed websites: {', '.join(sites[:3])}")

    current = item.get("currentPosition") or []
    if isinstance(current, list) and current and isinstance(current[0], dict):
        role = current[0]
        title = _plain(role.get("position"))
        company = _plain(role.get("companyName"))
        if title or company:
            lines.append(f"Current role: {title} at {company}".strip())

    experience = item.get("experience") or []
    if isinstance(experience, list) and experience:
        lines.append("\nExperience:")
        for role in experience[:6]:
            if not isinstance(role, dict):
                continue
            title = _plain(role.get("position"))
            company = _plain(role.get("companyName"))
            period = _plain(role.get("duration") or role.get("date") or role.get("dateRange"))
            lines.append(f"- {title} at {company}" + (f" ({period})" if period else ""))
            desc = _plain(role.get("description"))[:400]
            if desc:
                lines.append(f"  {desc}")

    education = item.get("education") or []
    if isinstance(education, list) and education:
        schools = [_plain(e.get("schoolName")) for e in education[:3] if isinstance(e, dict)]
        schools = [s for s in schools if s]
        if schools:
            lines.append("\nEducation: " + ", ".join(schools))

    skills = item.get("skills") or item.get("topSkills") or []
    if isinstance(skills, list) and skills:
        names = [_plain(s.get("name")) if isinstance(s, dict) else _plain(s) for s in skills[:20]]
        names = [n for n in names if n]
        if names:
            lines.append("\nSkills: " + ", ".join(names))

    return "\n".join(lines).strip()


_COMPANY_URL = re.compile(r"linkedin\.com/(company|school|showcase)/", re.I)
_PROFILE_URL = re.compile(r"linkedin\.com/in/", re.I)


async def scrape_linkedin(client: httpx.AsyncClient, url: str) -> ScrapeResult:
    if not url:
        return ScrapeResult(ok=False, error="no LinkedIn URL provided")

    # Leads paste company pages into a "LinkedIn URL" field constantly. The profile
    # actor silently returns nothing for those, which surfaced as a misleading
    # "profile not found or private". Say what actually happened instead, and don't
    # spend an actor run discovering it.
    if _COMPANY_URL.search(url):
        return ScrapeResult(
            ok=False,
            error="company page, not a personal profile — profile scraper skipped",
        )
    if not _PROFILE_URL.search(url):
        return ScrapeResult(ok=False, error="not a recognisable LinkedIn profile URL")

    settings = get_settings()
    try:
        items = await _run_actor(
            client,
            settings.apify_linkedin_actor,
            {"queries": [url], "maxItems": 1},
        )
    except httpx.HTTPStatusError as exc:
        log.error("LinkedIn actor HTTP %s: %s", exc.response.status_code, exc.response.text[:300])
        return ScrapeResult(ok=False, error=f"actor returned HTTP {exc.response.status_code}")
    except httpx.TimeoutException:
        return ScrapeResult(ok=False, error="actor timed out")
    except Exception as exc:  # noqa: BLE001 - a scrape failure must never kill the lead
        log.exception("LinkedIn scrape failed")
        return ScrapeResult(ok=False, error=f"{type(exc).__name__}: {exc}")

    if not items:
        return ScrapeResult(ok=False, error="profile not found or private")

    text = _flatten_linkedin(items[0])
    if not text:
        return ScrapeResult(ok=False, error="actor returned an empty profile")

    return ScrapeResult(ok=True, text=text[:MAX_LINKEDIN_CHARS])


_IMAGE_MD = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_EMPTY_LINK = re.compile(r"\[\s*\]\([^)]*\)")
_LINK_MD = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_BLANK_RUN = re.compile(r"\n{3,}")


def _clean_markdown(text: str) -> str:
    """Strip the parts of a crawled page that cost tokens and carry no signal.

    Crawled marketing pages are heavy on images and CDN URLs — on some sites that is
    the majority of the bytes. We keep link *text* (it names their services and nav
    structure, which is exactly what we score on) and drop the URLs.
    """
    text = _IMAGE_MD.sub("", text)
    text = _EMPTY_LINK.sub("", text)
    text = _LINK_MD.sub(r"\1", text)
    text = _BLANK_RUN.sub("\n\n", text)
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def _combine_pages(items: list[dict]) -> str:
    chunks: list[str] = []
    for page in items:
        body = _clean_markdown(page.get("markdown") or page.get("text") or "")
        if not body.strip():
            continue
        header = f"--- {page.get('url', 'page')} ---"
        metadata = page.get("metadata")
        title = metadata.get("title") if isinstance(metadata, dict) else None
        if title:
            header += f"\nTitle: {title}"
        chunks.append(f"{header}\n{body.strip()}")
    return "\n\n".join(chunks).strip()


async def _crawl(
    client: httpx.AsyncClient, url: str, crawler_type: str, max_pages: int
) -> list[dict]:
    settings = get_settings()
    payload = {
        "startUrls": [{"url": url}],
        "maxCrawlPages": max_pages,
        "maxCrawlDepth": 1,
        "crawlerType": crawler_type,
        "saveMarkdown": True,
        "removeCookieWarnings": True,
        "proxyConfiguration": {"useApifyProxy": True},
    }
    if crawler_type.startswith("playwright"):
        # Give client-side rendering a moment to populate the DOM, otherwise the
        # browser returns the same empty shell cheerio already got.
        payload["dynamicContentWaitSecs"] = 5
    return await _run_actor(client, settings.apify_website_actor, payload)


async def scrape_website(client: httpx.AsyncClient, url: str) -> ScrapeResult:
    """Crawl the company site, cheap first.

    `cheerio` is raw HTTP and roughly 10x cheaper than a headless browser, and it
    handles the server-rendered marketing sites most B2B companies run. But an
    increasing number of sites are JS-rendered and return a shell with no text — so
    when cheerio yields nothing we retry once with a real browser rather than
    reporting a false "no content" and losing the lead's whole website signal.
    """
    if not url:
        return ScrapeResult(ok=False, error="no website provided")

    settings = get_settings()
    attempts = (
        ("cheerio", settings.website_max_pages),
        ("playwright:adaptive", settings.website_fallback_max_pages),
    )
    last_error = "crawler returned no pages"

    for attempt, (crawler_type, max_pages) in enumerate(attempts, start=1):
        try:
            items = await _crawl(client, url, crawler_type, max_pages)
        except httpx.HTTPStatusError as exc:
            log.error(
                "Website actor HTTP %s (%s): %s",
                exc.response.status_code, crawler_type, exc.response.text[:300],
            )
            return ScrapeResult(ok=False, error=f"actor returned HTTP {exc.response.status_code}")
        except httpx.TimeoutException:
            return ScrapeResult(ok=False, error=f"actor timed out ({crawler_type})")
        except Exception as exc:  # noqa: BLE001
            log.exception("Website scrape failed (%s)", crawler_type)
            return ScrapeResult(ok=False, error=f"{type(exc).__name__}: {exc}")

        combined = _combine_pages(items) if items else ""
        if combined:
            if attempt > 1:
                log.info("Website needed the headless browser: %s", url)
            return ScrapeResult(ok=True, text=combined[:MAX_WEBSITE_CHARS])

        last_error = "pages crawled but no readable content" if items else "crawler returned no pages"
        if attempt < len(attempts):
            log.info("%s produced nothing for %s — retrying with a headless browser", crawler_type, url)

    tried = ", ".join(c for c, _ in attempts)
    return ScrapeResult(ok=False, error=f"{last_error} (tried {tried})")


async def enrich(linkedin_url: str, website_url: str) -> EnrichmentBundle:
    """Run both scrapers concurrently. Neither failing stops the other."""
    import asyncio

    async with httpx.AsyncClient() as client:
        linkedin, website = await asyncio.gather(
            scrape_linkedin(client, linkedin_url),
            scrape_website(client, website_url),
        )

    log.info("Enrichment done — linkedin_ok=%s website_ok=%s", linkedin.ok, website.ok)
    return EnrichmentBundle(linkedin=linkedin, website=website)
