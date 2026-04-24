
import requests
import json

url = "http://127.0.0.1:8000/scrape"
payload = {
    "url": "https://www.shopclues.com/",
    "fields": ["smartwatch"], # No search_query here, should auto-search 'smartwatch'
    "max_pages": 1,
    "llm_provider": "gemini"
}

print(f"Sending request to {url} (Auto-search fallback test)...")
try:
    response = requests.post(url, json=payload, timeout=120)
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Success! Found {len(data['data'])} items.")
    else:
        print("Response:")
        print(json.dumps(response.json(), indent=2))
except Exception as e:
    print(f"Error: {e}")
