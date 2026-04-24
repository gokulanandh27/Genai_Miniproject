import asyncio
from rag_pipeline import RAGPipeline

async def test_ingest():
    pipeline = RAGPipeline()
    try:
        chunks = await pipeline.ingest_url("https://example.com", 1)
        print("Success! Chunks:", chunks)
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_ingest())
