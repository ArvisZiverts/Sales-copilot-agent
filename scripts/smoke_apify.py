"""Live Apify check. Costs a few cents per run.

    python -m scripts.smoke_apify https://linkedin.com/in/someone https://example.com

Use this to confirm the actor input schemas are right before wiring the pipeline.
If LinkedIn comes back empty, check the actor's Input tab in the Apify console —
`queries` is the field harvestapi uses, but actors do rename fields between versions.
"""

import asyncio
import sys

from app.clients.apify import enrich


async def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    linkedin_url, website = sys.argv[1], sys.argv[2]
    print(f"Scraping\n  linkedin: {linkedin_url}\n  website:  {website}\n")

    bundle = await enrich(linkedin_url, website)

    for label, result in (("LINKEDIN", bundle.linkedin), ("WEBSITE", bundle.website)):
        print("=" * 70)
        print(f"{label}: {'OK' if result.ok else 'FAILED — ' + result.error}")
        print("=" * 70)
        if result.ok:
            print(f"{len(result.text)} chars\n")
            print(result.text[:2000])
            if len(result.text) > 2000:
                print(f"\n... (+{len(result.text) - 2000} more chars)")
        print()


if __name__ == "__main__":
    asyncio.run(main())
