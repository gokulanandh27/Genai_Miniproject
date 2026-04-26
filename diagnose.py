"""
diagnose.py - Deep diagnostic to find root cause of 0 items.
"""
import asyncio
import logging
import sys
import io
import json
from dotenv import load_dotenv

if sys.platform.startswith("win"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

import sys
sys.path.insert(0, r'C:\Users\GOKUL\OneDrive\Desktop\genai_mini')
from scraper import IntelligentScraper
from planner import LLMPlanner
from extractor import LLMExtractor

async def diagnose(url, prompt):
    load_dotenv(r'C:\Users\GOKUL\OneDrive\Desktop\genai_mini\.env')
    s = IntelligentScraper()
    p = LLMPlanner()
    e = LLMExtractor()

    print(f"\n{'='*60}")
    print(f"DIAGNOSING: {url}")
    print(f"PROMPT: {prompt}")
    print('='*60)

    # Step 1: Load
    print("\n--- STEP 1: INITIAL LOAD ---")
    init = await s.load(url)
    print(f"Success: {init['success']}")
    print(f"Text Length: {len(init['text'])} chars")
    print(f"Blocked: {init.get('blocked')}")
    print(f"Text Snippet:\n{init['text'][:800]}")

    if not init['success'] or not init['text']:
        print("FAIL: Could not load the page at all.")
        await s.close()
        return

    # Step 2: Plan
    print("\n--- STEP 2: PLANNING ---")
    plan = await asyncio.to_thread(p.plan, init['text'], init['links'], prompt, url)
    print(json.dumps(plan, indent=2, ensure_ascii=False))

    # Step 3: Execute
    print("\n--- STEP 3: NAVIGATION ---")
    target = plan.get('navigation', {}).get('target_url', url)
    print(f"Target URL: {target}")
    listing = await s.execute_plan(url, plan)
    print(f"Final URL: {listing['url']}")
    print(f"Text Length: {len(listing['text'])} chars")
    print(f"Blocked: {listing.get('blocked')}")
    print(f"Text Snippet:\n{listing['text'][:1500]}")

    # Step 4: Extract
    print("\n--- STEP 4: EXTRACTION ---")
    fields = plan.get('extraction', {}).get('fields', {'name': 'product name', 'price': 'price'})
    filt = plan.get('extraction', {}).get('filter', '')
    data = await e.extract(listing['text'], prompt, fields, 5, filt)
    print(f"Items Found: {len(data)}")
    for i, item in enumerate(data):
        print(f"  [{i+1}] {item}")

    await s.close()

async def main():
    await diagnose('https://www.shopclues.com/', 'laptops under 50000')
    await diagnose('https://www.amazon.in/', 'mobile phones under 20000')

asyncio.run(main())
