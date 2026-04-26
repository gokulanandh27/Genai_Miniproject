import asyncio
import logging
import sys
import os
from dotenv import load_dotenv

# Add current dir to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from scraper import IntelligentScraper
from planner import LLMPlanner
from extractor import LLMExtractor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DEBUG")

async def test_flipkart():
    load_dotenv()
    s = IntelligentScraper()
    p = LLMPlanner()
    e = LLMExtractor()
    
    url = "https://www.flipkart.com/"
    prompt = "give me mobile phones under 20000"
    
    print("\n--- STEP 1: INITIAL LOAD ---")
    initial = await s.load(url)
    print(f"Success: {initial['success']}, Text Len: {len(initial['text'])}")
    
    if not initial['success']:
        print("Initial load failed.")
        return

    print("\n--- STEP 2: PLANNING ---")
    plan = await asyncio.to_thread(p.plan, initial['text'], initial['links'], prompt, url)
    print(f"Plan: {plan}")
    
    print("\n--- STEP 3: NAVIGATION ---")
    listing = await s.execute_plan(url, plan)
    print(f"Final URL: {listing['url']}, Text Len: {len(listing['text'])}")
    
    if listing.get("blocked"):
        print("BLOCKED BY CAPTCHA")
        return

    print("\n--- STEP 4: EXTRACTION ---")
    data = await e.extract(listing['text'], prompt, {"title":"title", "price":"price"}, 5)
    print(f"Extracted {len(data)} items.")
    for item in data:
        print(f" - {item}")

if __name__ == "__main__":
    asyncio.run(test_flipkart())
