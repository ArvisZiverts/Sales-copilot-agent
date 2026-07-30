# Sales Copilot Agent

Typeform → Apify enrichment → Claude analysis → Google Sheets.

A lead fills out a Typeform. We scrape their LinkedIn profile and company website
via Apify, have Claude extract firmographics + score ICP fit + write a personal
icebreaker, and append one row to a Google Sheet for the sales rep.

## Architecture

```
Typeform submit
   └─► POST /webhook/typeform          (FastAPI, Railway)
         ├─ verify HMAC signature, return 200 immediately   ← Typeform times out at 10s
         └─► background task
               ├─ Apify: LinkedIn profile  ─┐ run concurrently
               ├─ Apify: website crawl      ─┘
               ├─ Claude: extract + score + icebreaker (structured output)
               └─ Google Sheets: append row
```

**Why ack-then-work:** enrichment takes 40–90s. If Typeform waits it times out and
retries, producing duplicate leads. We ack in <100ms and process async.

## Layout

| Path | Purpose |
|---|---|
| `app/main.py` | FastAPI app, `/webhook/typeform`, `/health` |
| `app/config.py` | Env-backed settings (pydantic-settings) |
| `app/models.py` | `Lead`, `EnrichmentBundle`, `LeadIntelligence` |
| `app/security.py` | Typeform HMAC-SHA256 verification |
| `app/pipeline.py` | Orchestration: enrich → analyze → write |
| `app/icp.py` | Loads `icp_profile.yaml` |
| `app/clients/typeform.py` | Parses the `form_response` payload into a `Lead` |
| `app/clients/apify.py` | LinkedIn + website scrapers |
| `app/clients/llm.py` | Structured analysis call (OpenAI) — the only provider-aware file |
| `app/clients/sheets.py` | Appends the row |
| `icp_profile.yaml` | **The ICP definition. Edit this, not the Python.** |

## Rules for working in this repo

- **ICP changes go in `icp_profile.yaml`.** Never hardcode scoring criteria into
  prompts or Python. The YAML is injected into the system prompt verbatim.
- **Every lead gets a sheet row, including failures**, with a `status` column.
  Nothing disappears silently. If you add an early return to the pipeline, it must
  still write a row.
- **Never let an exception escape the background task** — it would drop the lead.
- **Typeform field matching is by `ref`, then falls back to field `type`.** Refs are
  set in the Typeform editor and are the stable identifier; titles are not.
- **Idempotency is keyed on Typeform's `event_id`.** In-memory today (see the
  `_SEEN_EVENTS` note in `app/main.py`); swap for Redis if we run >1 replica.
- Enrichment degrades gracefully: if LinkedIn fails we still score from the website
  alone and flag it. A partial lead beats a lost lead.

## Apify notes (verified live 2026-07-30)

- **LinkedIn field names are real, not guessed.** There is no `fullName` — it's
  `firstName` + `lastName`. `location` is a nested dict. `connectionsCount`
  saturates (reads `8` on a 40M-follower profile) — use `followerCount` for reach.
  `hiring` and `openToWork` are strong ICP signals and are surfaced deliberately.
  If the actor changes schema, `scripts/smoke_apify.py` shows it as missing lines;
  `tests/test_apify_parsing.py` only locks the flattening logic, not the schema.
- **The website crawler tries `cheerio` then falls back to `playwright:adaptive`.**
  Cheap raw HTTP first; a real browser only when the first pass returns no text
  (JS-rendered sites). The fallback crawls fewer pages because it is much slower —
  a full 8-page headless crawl exceeded a 180s budget in testing, which is why
  `apify_timeout_seconds` is 300.
- Crawled markdown is stripped of images and link URLs before it reaches the model
  (`_clean_markdown`). On image-heavy sites that was the majority of the bytes.

## LLM notes (OpenAI)

- Model: `gpt-5-mini` (configurable via `OPENAI_MODEL`).
- **`app/clients/llm.py` is the only file that knows the provider.** `pipeline.py`
  imports `analyze(lead, bundle) -> LeadIntelligence` and nothing else. Keep it that
  way — swapping providers again should stay a one-file change.
- Structured output uses the **Responses API**:
  `client.responses.parse(..., text_format=LeadIntelligence)` →
  `response.output_parsed` is a validated Pydantic instance. Do not parse JSON by hand.
- OpenAI strict mode requires **every field required** and `additionalProperties: false`.
  The SDK derives both from the Pydantic model, so **do not give fields in
  `LeadIntelligence` default values** — an optional field breaks strict mode at runtime.
- **gpt-5-mini is a reasoning model.** Reasoning tokens are billed as output tokens and
  count against `max_output_tokens`, so keep it generous (16000) or the structured
  object truncates before it completes.
- `OPENAI_REASONING_EFFORT` (`minimal`/`low`/`medium`/`high`) is the main cost/quality
  dial. `temperature` is not supported on reasoning models — steer with the prompt.
- A safety refusal arrives as a `refusal` content item, **not an exception**, and
  `output_parsed` is then `None`. `_refusal_text()` handles this; if you touch the
  response handling, keep that check or refusals will surface as confusing null errors.

## Commands

```bash
source .venv/bin/activate
uvicorn app.main:app --reload          # local dev on :8000
pytest                                  # tests (clients are mocked)
python -m scripts.smoke_apify <linkedin_url> <website>   # live Apify check
python -m scripts.smoke_sheets          # writes a test row
```

## Secrets

`.env` locally, Railway Variables in prod. Never committed. Required:
`APIFY_TOKEN`, `OPENAI_API_KEY`, `TYPEFORM_WEBHOOK_SECRET`,
`GOOGLE_SERVICE_ACCOUNT_B64`, `GOOGLE_SHEET_ID`.

The Google Sheet must be **shared with the service account's email address** —
a missed step here surfaces as a silent 403.
