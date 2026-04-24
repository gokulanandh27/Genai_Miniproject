
import asyncio
import logging
from orchestrator import ScrapingOrchestrator, ScrapeRequest

logging.basicConfig(level=logging.INFO)

async def debug_shopclues():
    orchestrator = ScrapingOrchestrator()
    
    request = ScrapeRequest(
        url="https://www.shopclues.com/",
        fields=["watch names and prices"],
        search_query="smartwatch",
        filter_description="under 2000",
        max_pages=1,
        llm_provider="gemini"
    )
    
    print("Debugging Shopclues Scrape...")
    response = await orchestrator.run(request)
    
    print("\n=== RESULTS ===")
    print(f"Success: {response.success}")
    print(f"Items: {len(response.data)}")
    print(f"Error: {response.error}")
    
    if response.data:
        for item in response.data[:3]:
            print(f" - {item}")

if __name__ == "__main__":
    asyncio.run(debug_shopclues())
