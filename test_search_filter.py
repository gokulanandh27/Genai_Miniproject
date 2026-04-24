
import asyncio
import logging
from orchestrator import ScrapingOrchestrator, ScrapeRequest

logging.basicConfig(level=logging.INFO)

async def test_search_filter():
    orchestrator = ScrapingOrchestrator()
    
    # Testing on eBay as it's a good target for search+filter
    request = ScrapeRequest(
        url="https://www.ebay.com",
        fields=["watch names and prices"],
        search_query="casio watch",
        filter_description="under 50 dollars",
        max_pages=1,
        llm_provider="gemini"
    )
    
    print("Starting Search + Filter Test on eBay...")
    response = await orchestrator.run(request)
    
    print("\n=== RESULTS ===")
    print(f"Success: {response.success}")
    print(f"Items found: {len(response.data)}")
    if response.data:
        print("First 3 items:")
        for item in response.data[:3]:
            print(f" - {item}")
    else:
        print(f"Error: {response.error}")

if __name__ == "__main__":
    asyncio.run(test_search_filter())
