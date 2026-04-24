import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

from rag_pipeline import RAGPipeline

pipeline = RAGPipeline()
context = "A Light in the Attic. Price: £51.77. Availability: In stock (22 available)"
fields = ["title", "price", "availability"]

print("LLM API Key exists:", bool(os.getenv("GOOGLE_API_KEY")))
data = pipeline._llm_extract_from_context(context, fields)
print("Extracted Data:", data)
