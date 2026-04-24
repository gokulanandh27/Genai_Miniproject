"""
extractor.py — LLM Extraction Pipeline (Gemini + OpenAI)
Supports Gemini (recommended) and OpenAI fallback.
"""

import asyncio
import json
import logging
import re
from typing import Any
import os

import google.generativeai as genai
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from html_cleaner import HTMLCleaner

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a precise data extraction engine. Your ONLY job is to extract data that is EXPLICITLY present in the provided text.

ABSOLUTE RULES — violations will cause system failure:
1. NEVER invent, infer, or hallucinate any values
2. If a field value is not clearly present in the text → use null
3. Extract ONLY complete, well-formed items — no partial guesses
4. Return ONLY a valid JSON array of objects, no markdown, no explanation, no preamble
5. If NO items match → return exactly: []

Structure the JSON keys dynamically based on what the user is asking for. Use descriptive keys for each object.
"""


class LLMExtractor:
    def __init__(self, llm_provider: str = "gemini", model: str = None):
        self.cleaner = HTMLCleaner()
        self.provider = llm_provider
        # We don't build a single LLM anymore; we build it per-call in the fallback chain
        self.primary_model = model

    # Ordered fallback list — tries each in order when quota is exhausted
    # Format: "provider:model_name"
    FALLBACK_MODELS = [
        "gemini:gemini-flash-lite-latest",
        "groq:llama-3.1-70b-versatile",
        "siliconflow:deepseek-ai/DeepSeek-V3",
        "gemini:gemini-2.0-flash-lite",
        "groq:mixtral-8x7b-32768",
    ]

    async def extract(self, pages_data: list[dict], fields: list[str], url: str) -> list[dict]:
        """
        Concatenates ALL scraped pages into one text block and makes a SINGLE
        LLM API call. This is far more quota-efficient than one call per page.
        """
        if not pages_data:
            return []

        # Build one big combined text from all pages
        all_text_parts = []
        for page in pages_data:
            cleaned = self.cleaner.clean(page["html"])
            all_text_parts.append(f"=== PAGE {page['page_num']} ({page['url']}) ===\n{cleaned}")

        combined_text = "\n\n".join(all_text_parts)
        logger.info(f"Combined text length: {len(combined_text)} chars across {len(pages_data)} pages. Making 1 LLM call.")

        # If combined text exceeds token budget, chunk it into segments
        MAX_CHARS = 800_000
        if len(combined_text) > MAX_CHARS:
            logger.warning(f"Text too long ({len(combined_text)} chars), chunking into segments...")
            segments = self.cleaner.chunk(combined_text, max_chars=MAX_CHARS)
        else:
            segments = [combined_text]

        all_items: list[dict] = []
        seen_keys: set[str] = set()

        for seg_idx, segment in enumerate(segments):
            logger.info(f"Extracting segment {seg_idx+1}/{len(segments)}...")
            items = await self._extract_chunk_with_retry(segment, fields, url)
            for item in items:
                valid_values = [v for v in item.values() if isinstance(v, str) and v.strip()]
                key = valid_values[0].lower().strip() if valid_values else str(item)
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    all_items.append(item)

        logger.info(f"Total extracted: {len(all_items)} items")
        return all_items

    async def _extract_chunk_with_retry(self, text: str, fields: list[str], url: str) -> list[dict]:
        """Calls LLM with automatic model fallback on 429 quota errors."""
        extra_fields_note = f"\nUser is looking for: {', '.join(fields)}" if fields else ""
        user_message = f"""Extract all matching items from the text below.
{extra_fields_note}

Source URL: {url}

TEXT:
{text}

Return ONLY a valid JSON array. If nothing matches, return [].
"""
        
        # Decide the models to try
        models_to_try = self.FALLBACK_MODELS.copy()
        if self.primary_model:
            # If a specific model was requested, put it first
            p_model = f"{self.provider}:{self.primary_model}" if ":" not in self.primary_model else self.primary_model
            if p_model in models_to_try: models_to_try.remove(p_model)
            models_to_try.insert(0, p_model)

        for model_str in models_to_try:
            try:
                provider, model_name = model_str.split(":", 1)
                logger.info(f"🔄 LLM SWITCH: Trying {provider.upper()} model: {model_name}")
                
                raw_text = await self._call_provider(provider, model_name, user_message)
                if raw_text:
                    clean_raw = raw_text[:200].replace("\n", " ")
                    logger.info(f"✅ SUCCESS: {provider.upper()} extraction complete. Raw snippet: {clean_raw}")
                    return self._parse_response(raw_text)
                else:
                    logger.warning(f"⚠️ SKIPPED: {provider} returned no content (missing key).")
                    continue

            except Exception as e:
                err_str = str(e).lower()
                logger.warning(f"❌ FAILED: {model_str} error: {e}")
                if any(x in err_str for x in ["429", "rate_limit", "quota", "overloaded", "not found", "authentication"]):
                    logger.warning(f"⏭️ FALLBACK: Quota/Auth issue on {model_str}, switching to next...")
                    continue
                else:
                    logger.warning(f"⏭️ FALLBACK: Unexpected error, trying next...")
                    continue

        logger.error("All models and providers exhausted their quotas or failed. Cannot extract.")
        return []

    async def _call_provider(self, provider: str, model_name: str, user_message: str) -> str:
        """Call the specific LLM provider API."""
        try:
            if provider == "gemini":
                api_key = os.getenv("GOOGLE_API_KEY")
                if not api_key or api_key == "your_api_key_here" or api_key.strip() == "":
                    return None
                genai.configure(api_key=api_key)
                llm = genai.GenerativeModel(model_name)
                response = await asyncio.to_thread(llm.generate_content, SYSTEM_PROMPT + "\n\n" + user_message)
                return response.text

            elif provider == "groq":
                api_key = os.getenv("GROQ_API_KEY")
                if not api_key or api_key.strip() == "":
                    return None
                llm = ChatOpenAI(
                    model=model_name,
                    openai_api_key=api_key,
                    openai_api_base="https://api.groq.com/openai/v1",
                    temperature=0,
                )
                response = await llm.ainvoke([
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=user_message),
                ])
                return response.content

            elif provider == "siliconflow":
                api_key = os.getenv("SILICONFLOW_API_KEY")
                if not api_key or api_key.strip() == "":
                    return None
                llm = ChatOpenAI(
                    model=model_name,
                    openai_api_key=api_key,
                    openai_api_base="https://api.siliconflow.cn/v1",
                    temperature=0,
                )
                response = await llm.ainvoke([
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=user_message),
                ])
                return response.content
            
            # Fallback to OpenAI if key exists
            elif provider == "openai":
                api_key = os.getenv("OPENAI_API_KEY")
                if not api_key: return None
                llm = ChatOpenAI(model=model_name, openai_api_key=api_key, temperature=0)
                response = await llm.ainvoke([
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=user_message),
                ])
                return response.content

        except Exception as e:
            logger.error(f"Provider {provider} call failed: {e}")
            raise # Re-raise to be caught by the fallback loop
        
        return None

    def _parse_response(self, raw: str) -> list[dict]:
        raw = raw.strip()
        # Remove markdown if present
        raw = re.sub(r"^```(?:json)?", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"```$", "", raw, flags=re.IGNORECASE)

        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
            return []
        except Exception:
            # Try to find JSON array in the text
            match = re.search(r"\[\s*\{.*\}\s*\]", raw, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except: pass
            logger.warning(f"Failed parsing JSON from raw text.")
            return []

    async def _extract_chunk(self, text: str, fields: list[str], url: str) -> list[dict]:
        return await self._extract_chunk_with_retry(text, fields, url)