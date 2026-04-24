
import requests
import json
import time

url = "http://127.0.0.1:8000/scrape"
payload = {
    "url": "http://books.toscrape.com/",
    "fields": ["give me description of the book named A Light in the Attic"],
    "max_pages": 1,
    "llm_provider": "gemini"
}

print(f"Sending Deep Crawl request for 'A Light in the Attic'...")
start = time.time()
try:
    response = requests.post(url, json=payload, timeout=180)
    end = time.time()
    print(f"Status Code: {response.status_code} (took {end-start:.1f}s)")
    if response.status_code == 200:
        data = response.json()
        print("Success!")
        items = data['data']
        for item in items:
            print(f"ITEM FOUND: {json.dumps(item, indent=2)}")
    else:
        print("Response Error:")
        print(json.dumps(response.json(), indent=2))
except Exception as e:
    print(f"Error: {e}")
