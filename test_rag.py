import asyncio
import json
import httpx

async def main():
    url = "http://127.0.0.1:8000"
    
    print("1. Ingesting URL...")
    # Using a fast loading dynamic URL or static URL for test. 
    # Using a real e-commerce sandbox to demonstrate extraction
    ingest_payload = {"url": "http://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html", "max_pages": 1}
    async with httpx.AsyncClient() as client:
        res = await client.post(f"{url}/rag/ingest", json=ingest_payload, timeout=60.0)
        print("Ingest Status:", res.status_code)
        print("Ingest Response:", res.text)
        
    print("\n2. Searching RAG...")
    search_payload = {"fields": ["title", "price", "availability"]}
    async with httpx.AsyncClient() as client:
        res = await client.post(f"{url}/rag/search", json=search_payload, timeout=60.0)
        print("Search Status:", res.status_code)
        try:
            print("Search Response:", json.dumps(res.json(), indent=2))
        except:
            print("Search Response:", res.text)

if __name__ == "__main__":
    asyncio.run(main())
