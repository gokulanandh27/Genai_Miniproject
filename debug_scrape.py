import asyncio
from orchestrator import ScrapingOrchestrator, ScrapeRequest

async def main():
    orc = ScrapingOrchestrator()
    req = ScrapeRequest(
        url="http://books.toscrape.com/",
        fields=["give me book names with 4 star or above rating"],
        max_pages=1,
        llm_provider="gemini"
    )
    resp = await orc.run(req)
    print("Success:", resp.success)
    print("Error:", resp.error)
    print("Data count:", len(resp.data))
    print("Validation:", resp.validation)
    if resp.data:
        print("First item:", resp.data[0])

asyncio.run(main())
