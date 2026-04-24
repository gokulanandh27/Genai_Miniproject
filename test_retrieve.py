import asyncio
from rag_pipeline import RAGPipeline

def test_retrieve():
    pipeline = RAGPipeline()
    try:
        data = pipeline.retrieve_and_extract(["title", "price", "availability"])
        print("Data:", data)
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_retrieve()
