import os
import json
import logging
import asyncio
from typing import List, Dict

from chromadb import Client, Settings
from chromadb.utils import embedding_functions

from scraper import PlaywrightScraper
from html_cleaner import HTMLCleaner
import google.generativeai as genai

logger = logging.getLogger(__name__)

class RAGPipeline:
    def __init__(self, collection_name: str = "web_scrape_db"):
        self.chroma_client = Client(Settings(persist_directory="./chroma_db", is_persistent=True))
        # Use sentence-transformers (runs locally, free, no API key needed)
        self.embedding_func = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
        
        # Get or create collection
        self.collection = self.chroma_client.get_or_create_collection(
            name=collection_name, 
            embedding_function=self.embedding_func
        )
        self.cleaner = HTMLCleaner()

    def clear_collection(self):
        """Clears all documents from the collection for a new session."""
        try:
            self.chroma_client.delete_collection(self.collection.name)
        except Exception:
            pass
        self.collection = self.chroma_client.get_or_create_collection(
            name=self.collection.name, 
            embedding_function=self.embedding_func
        )
        logger.info("ChromaDB collection cleared.")

    async def ingest_url(self, url: str, max_pages: int = 5) -> int:
        """
        Scrapes a URL using Playwright (handling dynamic JS), cleans HTML, 
        chunks it, and stores it locally into ChromaDB. 
        NO LLM API USED HERE!
        """
        logger.info(f"Starting ingestion for {url} (max pages: {max_pages})")
        scraper = PlaywrightScraper(config={"max_pages": max_pages, "headless": True})
        
        # Scrape with empty fields to just trigger basic navigation and pagination
        pages_data = await scraper.scrape(url, [""]) 
        
        total_chunks = 0
        documents = []
        metadatas = []
        ids = []

        for page in pages_data:
            logger.info(f"Cleaning & chunking page {page['page_num']}...")
            clean_text = self.cleaner.clean(page["html"], mode="full_text")
            # Chunking smaller for vector similarity
            chunks = self.cleaner.chunk(clean_text, max_chars=1000) 
            
            for i, chunk in enumerate(chunks):
                if not chunk.strip():
                    continue
                doc_id = f"{url}_p{page['page_num']}_c{i}"
                documents.append(chunk)
                metadatas.append({"url": page["url"], "page_num": page["page_num"]})
                ids.append(doc_id)
                total_chunks += 1
        
        if documents:
            logger.info(f"Storing {total_chunks} chunks to ChromaDB...")
            # We insert in batches to avoid DB limits
            batch_size = 100
            for i in range(0, len(documents), batch_size):
                self.collection.upsert(
                    documents=documents[i:i+batch_size],
                    metadatas=metadatas[i:i+batch_size],
                    ids=ids[i:i+batch_size]
                )
        
        return total_chunks

    def retrieve_and_extract(self, fields: List[str]) -> List[dict]:
        """
        Takes the key fields the user wants, searches the local vector DB for relevant chunks,
        and uses the LLM (Gemini) *just once* to answer from those specific chunks.
        """
        query_text = " ".join(fields)
        logger.info(f"Querying ChromaDB for: {query_text}")
        
        # Retrieve up to 150 most relevant chunks (to allow for massive 'give me all' queries)
        n_chunks = min(self.collection.count(), 150)
        if n_chunks == 0:
            logger.warning("DB is empty.")
            return []
            
        results = self.collection.query(
            query_texts=[query_text],
            n_results=n_chunks
        )
        
        if not results['documents'] or not results['documents'][0]:
            logger.warning("No relevant chunks found in DB.")
            return []
            
        retrieved_docs = results['documents'][0]
        context = "\n\n---CHUNK---\n\n".join(retrieved_docs)
        
        logger.info(f"Retrieved {len(retrieved_docs)} chunks from local DB. Sending to LLM.")
        # Now use the single LLM call to extract data
        return self._llm_extract_from_context(context, fields)

    def _llm_extract_from_context(self, context: str, fields: List[str]) -> List[dict]:
        user_query = " ".join(fields)
        
        system_prompt = """You are a smart data extraction assistant. 
Your goal is to answer the user's request using ONLY the provided CONTEXT. 
1. If the user asks for specific data, extract it into a JSON array of objects.
2. Structure the JSON keys based on what the user is asking for.
3. NEVER invent or hallucinate data. If the answer is not in the context, return [].
4. Return ONLY valid JSON array. No markdown tags like ```json.
"""
        
        user_message = f"""
User Request: {user_query}

Use ONLY the following context to extract the data.

CONTEXT:
{context}
"""
        
        try:
            genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
            # Use gemini-2.5-flash to bypass quota limits on older models
            llm = genai.GenerativeModel("gemini-2.5-flash") 
            response = llm.generate_content(system_prompt + "\n\n" + user_message)
            raw = response.text.strip()
            
            import re
            raw = re.sub(r"^```(?:json)?\n?", "", raw, flags=re.IGNORECASE)
            raw = re.sub(r"\n?```$", "", raw, flags=re.IGNORECASE)
            
            logger.info(f"Raw LLM output: {raw}")
            
            data = json.loads(raw)
            if isinstance(data, list):
                return data
            return []
        except Exception as e:
            logger.error(f"RAG LLM extraction error: {e}")
            return []
