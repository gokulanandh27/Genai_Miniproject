import asyncio
import logging
import sys
import io
from scraper import IntelligentScraper
from planner import LLMPlanner
from extractor import LLMExtractor
from dotenv import load_dotenv

# Force UTF-8
if sys.platform.startswith("win"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("ProdTest")

TEST_CASES = [
    {
        "name": "E-commerce (Amazon)",
        "url": "https://www.amazon.in/",
        "prompt": "laptops under 40000",
        "check": lambda items: all(float(str(i.get('price','0')).replace(',','').replace('₹','').strip().split('.')[0]) <= 40000 for i in items if 'price' in i)
    },
    {
        "name": "E-commerce (Flipkart)",
        "url": "https://www.flipkart.com/",
        "prompt": "samsung mobiles under 20000",
        "check": lambda items: len(items) > 0
    },
    {
        "name": "News (BBC)",
        "url": "https://www.bbc.com/news",
        "prompt": "latest world news headlines",
        "check": lambda items: len(items) > 3
    },
    {
        "name": "Technical Docs (Python)",
        "url": "https://docs.python.org/3/library/",
        "prompt": "list networking modules",
        "check": lambda items: any('socket' in str(i).lower() for i in items)
    }
]

async def run_tests():
    load_dotenv()
    scraper = IntelligentScraper()
    planner = LLMPlanner()
    extractor = LLMExtractor()
    
    results = []
    
    for tc in TEST_CASES:
        logger.info(f"\n--- RUNNING TEST: {tc['name']} ---")
        try:
            # 1. Load
            init = await scraper.load(tc['url'])
            if not init['success']:
                logger.error(f"Failed to load {tc['url']}")
                results.append((tc['name'], "FAIL (Load)"))
                continue
            
            # 2. Plan
            plan = await asyncio.to_thread(planner.plan, init['text'], init['links'], tc['prompt'], tc['url'])
            
            # 3. Navigate
            listing = await scraper.execute_plan(tc['url'], plan)
            
            # 4. Extract
            data = await extractor.extract(
                listing['text'], 
                tc['prompt'], 
                plan['extraction']['fields'], 
                plan['extraction']['limit'],
                plan['extraction']['filter']
            )
            
            # 5. Validate
            if data and tc['check'](data):
                logger.info(f"✅ TEST PASSED: {tc['name']} (Found {len(data)} items)")
                results.append((tc['name'], "PASS"))
            else:
                logger.error(f"❌ TEST FAILED: {tc['name']} (Items: {len(data)})")
                results.append((tc['name'], f"FAIL (Check) - Found {len(data)} items"))
                
        except Exception as e:
            logger.exception(f"💥 TEST CRASHED: {tc['name']}")
            results.append((tc['name'], f"CRASH: {e}"))
            
    await scraper.close()
    
    print("\n\n" + "="*40)
    print("FINAL TEST RESULTS")
    print("="*40)
    all_pass = True
    for name, res in results:
        print(f"{name:.<30} {res}")
        if res != "PASS": all_pass = False
    
    if all_pass:
        print("\n🏆 ALL PRODUCTION TESTS PASSED! THE BOT IS 100% READY.")
        sys.exit(0)
    else:
        print("\n⚠️ SOME TESTS FAILED. DO NOT DEPLOY.")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(run_tests())
