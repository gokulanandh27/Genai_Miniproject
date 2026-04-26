import asyncio
import logging
import sys
import os
from dotenv import load_dotenv

# Force UTF-8 for Windows
import io
if sys.platform.startswith("win"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add current dir to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from scraper import IntelligentScraper
from planner import LLMPlanner
from extractor import LLMExtractor

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("TEST")

async def run_test(name, url, prompt):
    print(f"\n{'='*20} TESTING: {name} {'='*20}")
    print(f"URL: {url}")
    print(f"Prompt: {prompt}")
    
    s = IntelligentScraper()
    p = LLMPlanner()
    e = LLMExtractor()
    
    try:
        # Load
        print("[1/4] Loading page...")
        initial = await s.load(url)
        if not initial['success']:
            print(f"FAILED to load {url}")
            return
        
        # Plan
        print("[2/4] Planning...")
        plan = await asyncio.to_thread(p.plan, initial['text'], initial['links'], prompt, url)
        print(f"Plan Type: {plan.get('navigation', {}).get('type')}")
        
        # Execute
        print("[3/4] Executing Navigation...")
        listing = await s.execute_plan(url, plan)
        
        # Extract
        print("[4/4] Extracting Data...")
        fields = plan.get("extraction", {}).get("fields", {"title": "title"})
        limit = plan.get("extraction", {}).get("limit", 5)
        data = await e.extract(listing['text'], prompt, fields, limit)
        
        print(f"SUCCESS: Found {len(data)} items.")
        for i, item in enumerate(data[:3]):
            print(f"  {i+1}. {item}")
            
    except Exception as ex:
        print(f"ERROR in {name}: {ex}")
    finally:
        await s.close()

async def main():
    load_dotenv()
    tests = [
        ("BOOKS", "http://books.toscrape.com/", "give me 3 horror books with price"),
        ("NEWS", "https://timesofindia.indiatimes.com/india", "list the latest 5 news headlines"),
        ("TECH", "https://docs.python.org/3/library/index.html", "find 3 modules related to networking"),
        ("AMAZON", "https://www.amazon.in/", "laptops under 40000"),
        ("FLIPKART", "https://www.flipkart.com/", "samsung mobiles under 15000")
    ]
    
    for name, url, prompt in tests:
        await run_test(name, url, prompt)
        print("\nWaiting 5s for next test...")
        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
