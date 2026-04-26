"""
test_bot.py — End-to-end tests for ScraperBot v3
Run: python test_bot.py
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
import requests
import json
import time
import sys

BASE = "http://127.0.0.1:8000"

TESTS = [
    {
        "name": "1. Book description (single book)",
        "url": "http://books.toscrape.com",
        "prompt": "Give me the full description and price of the book 'A Light in the Attic'",
    },
    {
        "name": "2. Two books description",
        "url": "http://books.toscrape.com",
        "prompt": "Give me the description and price of TWO books: 'A Light in the Attic' and 'Tipping the Velvet'",
    },
    {
        "name": "3. Top 5 Horror books",
        "url": "http://books.toscrape.com",
        "prompt": "List the top 5 horror books with their title, price, and rating",
    },
    {
        "name": "4. Most expensive books",
        "url": "http://books.toscrape.com",
        "prompt": "What are the 5 most expensive books? Show title and price",
    },
    {
        "name": "5. Not applicable check",
        "url": "http://books.toscrape.com",
        "prompt": "I want a laptop with RTX 3050 GPU under 70000 rupees",
    },
    {
        "name": "6. Wikipedia scrape",
        "url": "https://en.wikipedia.org/wiki/Artificial_intelligence",
        "prompt": "Give me the main topics/sections covered in this article",
    },
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
            timeout=180,
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
    # Check server is running
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
    print("SUMMARY")
    print("=" * 60)
    passed = sum(1 for r in results if r["status"] == "PASS")
    for r in results:
        icon = "PASS" if r["status"] == "PASS" else "FAIL"
        print(f"  [{icon}] {r['test']} ({r.get('elapsed', 0):.1f}s)")
    print(f"\n{passed}/{len(results)} tests passed")


if __name__ == "__main__":
    main()
