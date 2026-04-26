"""
test_universal.py — End-to-end multi-site testing for ScraperBot v3

Tests:
1. Amazon (Pagination & Search)
2. Times of India (News Headlines)
3. Python Docs (Documentation extraction)
"""
import asyncio
import requests
import json
import time
import sys
import io

# Fix Windows encoding issues in terminal
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:8000"

TESTS = [
    {
        "name": "1. Amazon - Mobiles Pagination",
        "url": "https://www.amazon.in/",
        "prompt": "Give me mobile phones under 20000 rupees (Limit: 35 items)",
    },
    {
        "name": "2. Times of India - Headlines",
        "url": "https://timesofindia.indiatimes.com/",
        "prompt": "Extract the top 5 latest news headlines and their short summaries",
    },
    {
        "name": "3. Python Docs - Functions",
        "url": "https://docs.python.org/3/library/json.html",
        "prompt": "List the main functions in the json module with their descriptions",
    }
]

def run_test(test: dict) -> dict:
    print(f"\n{'='*60}")
    print(f"Test: {test['name']}")
    print(f"URL:  {test['url']}")
    print(f"Prompt: {test['prompt']}")
    print("-" * 60)

    start = time.time()
    try:
        resp = requests.post(
            f"{BASE}/scrape",
            json={"url": test["url"], "prompt": test["prompt"]},
            timeout=300, # Pagination might take a while
        )
        elapsed = time.time() - start

        data = resp.json()
        status = "PASS" if resp.status_code == 200 else "FAIL"

        if data.get("not_applicable"):
            print(f"[{status}] NOT APPLICABLE: {data.get('message')} ({elapsed:.1f}s)")
        else:
            count = data.get("count", 0)
            print(f"[{status}] {count} item(s) extracted in {elapsed:.1f}s")
            if data.get("data"):
                for i, item in enumerate(data["data"][:3]):
                    print(f"  [{i+1}] {json.dumps(item, ensure_ascii=False)[:120]}")
                if count > 3:
                    print(f"  ... and {count - 3} more")

        return {"test": test["name"], "status": status, "elapsed": elapsed, "count": data.get("count", 0)}

    except Exception as e:
        elapsed = time.time() - start
        print(f"[FAIL] Exception: {e} ({elapsed:.1f}s)")
        return {"test": test["name"], "status": "FAIL", "elapsed": elapsed, "error": str(e)}

def main():
    try:
        r = requests.get(f"{BASE}/health", timeout=5)
        print(f"[OK] Server is running (version {r.json().get('version')})")
    except Exception:
        print("[ERROR] Server is NOT running. Start it first: python run.py")
        sys.exit(1)

    results = []
    for test in TESTS:
        result = run_test(test)
        results.append(result)

    print(f"\n{'='*60}")
    print("UNIVERSAL TEST SUMMARY")
    print("=" * 60)
    passed = sum(1 for r in results if r["status"] == "PASS")
    for r in results:
        icon = "PASS" if r["status"] == "PASS" else "FAIL"
        print(f"  [{icon}] {r['test']} - {r.get('count', 0)} items ({r.get('elapsed', 0):.1f}s)")
    print(f"\n{passed}/{len(results)} tests passed")

if __name__ == "__main__":
    main()
