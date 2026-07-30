# Sales Copilot

Typeform → Apify → Claude → Google Sheets. A lead fills out the form; a scored,
researched brief with a ready-to-use icebreaker lands in the sheet ~90 seconds later.

Cost per lead: roughly **$0.01–0.02** — LinkedIn $0.004, website ~$0.002, and a
`gpt-5-mini` call in the sub-cent range. Scraping is now the larger half of the bill.

---

## Setup, in order

### 1. Local

```bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill it in — see steps 2-5
pytest                      # 21 tests, no credentials needed
```

### 2. Apify

Console → Settings → API & Integrations → copy the Personal API token into
`APIFY_TOKEN`. Both actors are pay-per-use; nothing to install.

Verify before wiring anything else — this costs a few cents:

```bash
python -m scripts.smoke_apify https://linkedin.com/in/YOUR_PROFILE https://YOUR-SITE.com
```

Both sections should print scraped text. If LinkedIn comes back empty, open
`harvestapi/linkedin-profile-scraper` in the Apify console, check the **Input** tab
for the current field name, and update the payload in `app/clients/apify.py`.

### 3. OpenAI

`platform.openai.com` → API keys → `OPENAI_API_KEY`.

The key needs access to `gpt-5-mini`. If the project is brand new it may need credit
on the account before the first call succeeds.

### 4. Google Sheets

1. `console.cloud.google.com` → new project → enable the **Google Sheets API**
2. IAM & Admin → Service Accounts → create one → Keys → Add key → JSON
3. Encode it: `base64 -i service-account.json | tr -d '\n'` → `GOOGLE_SERVICE_ACCOUNT_B64`
4. Create the sheet, take the ID from the URL → `GOOGLE_SHEET_ID`
5. **Share the sheet with the service account's `client_email` as Editor.**
   Skipping this is the single most common failure and it surfaces as a silent 403.

```bash
python -m scripts.smoke_sheets    # writes one test row, then delete it
```

### 5. Typeform

Set the field **refs** in the form editor to exactly: `full_name`, `email`, `phone`,
`website`, `linkedin_url`. Matching falls back to field types if you don't, but refs
are what makes it reliable.

Generate a secret (`openssl rand -hex 32`) into `TYPEFORM_WEBHOOK_SECRET`. You'll
paste the same string into Typeform in step 7.

### 6. End-to-end locally

```bash
uvicorn app.main:app --reload           # terminal 1
python -m scripts.smoke_local_webhook   # terminal 2
```

Returns `{"status":"accepted"}` immediately; watch terminal 1 for enrichment, then
check the sheet.

### 7. Deploy to Railway

```bash
git init && git add -A && git commit -m "Sales copilot agent"
gh repo create sales-copilot --private --source=. --push
```

In Railway: **New Project → Deploy from GitHub repo → pick it.** It reads
`railway.json`, detects Python from `requirements.txt`, and pins 3.12 via
`.python-version`.

The start command in `railway.json` includes `--workers 1` on purpose — the
idempotency cache is in-process, so a second worker would let Typeform retries
through as duplicate rows. Don't drop that flag without moving the cache to Redis.

Then **Variables** → add every key from `.env` (not the file itself), and
**Settings → Networking → Generate Domain**.

Verify: `curl https://YOUR-APP.up.railway.app/health` → `{"status":"ok"}`

Note the app must keep running after it answers the webhook — enrichment continues in
the background for up to a couple of minutes. Don't put it on a serverless platform
that freezes the container once the HTTP response is sent; Railway keeps it alive.

### 8. Point Typeform at it

Typeform → your form → **Connect → Webhooks → Add a webhook**

- Endpoint: `https://YOUR-APP.up.railway.app/webhook/typeform`
- Secret: the same `TYPEFORM_WEBHOOK_SECRET`
- Save, then **Send test request** — expect a 200

Submit the form yourself once. A row should appear in the sheet in about 90 seconds.

---

## Tuning it

**The ICP in `icp_profile.yaml` is a placeholder written for testing.** Replace it
with your real offer, your real 10/10, your real disqualifiers, and a real icebreaker
in your voice. Nothing else needs to change — the file is injected into the prompt
verbatim. This file, not the code, is what determines whether the scores are useful.

After ~20 real leads, check the `icp_score` column. If everything is a 6–8, the rubric
anchors in the YAML aren't distinct enough — sharpen them. If the icebreakers read
generic, add two or three real examples to `icebreaker_guidance`.

Two dials, both env vars, no code change:

- `OPENAI_REASONING_EFFORT` — `minimal` / `low` / `medium` / `high`. Raise it if the
  `icp_reason` column reads shallow or ignores the rubric; lower it to cut cost.
- `OPENAI_MODEL` — try `gpt-5` if `gpt-5-mini` scores inconsistently on the same lead.

If you want to compare, run the same 10 leads through both and diff the score column —
judgement quality on a nuanced rubric is exactly where the bigger model earns its price.

---

## Operating notes

| Sheet `status` | Means |
|---|---|
| `ok` | Both sources scraped, lead scored |
| `partial` | One source failed; scored on the other. Check `sources` |
| `skipped` | Lead submitted no website and no LinkedIn |
| `enrichment_failed` | Both scrapers returned nothing; not scored |
| `error` | Pipeline threw. Reason in the `error` column |

Every lead produces exactly one row regardless of outcome — nothing is dropped
silently. `tests/test_pipeline.py` enforces this.

**Scaling past one replica:** the idempotency cache in `app/main.py` is in-memory, so
each replica has its own. Move `_SEEN_EVENTS` to Redis before raising `numReplicas`.
