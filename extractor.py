"""
extractor.py - LLM-powered structured data extractor
Uses Gemini as primary (reliable, high context), Groq as fallback.
"""
import os
import json
import logging
import re
import asyncio
import aiohttp

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger(__name__)

EXTRACT_SYSTEM = """You are a precise data extraction engine.

TASK: Extract structured data from the webpage content based on the user's request.

RULES:
1. Return ONLY a JSON array: [{"field1": "value1", ...}, ...]
2. For LIST requests (products, books, people): extract AS MANY matching items as possible up to the limit.
3. For SINGULAR facts (CEO, headquarters, founding year): return exactly ONE object.
4. Each object must only contain the requested fields.
5. CRITICAL: Never invent data. If a value is missing, use "N/A".
6. CRITICAL: Extract the item even if some fields (like 'description' or 'rating') are entirely missing from the text.
7. Do NOT include markdown, explanations, or any text outside the JSON array.
8. Start with [ and end with ]
"""

# Verified working models as of April 2026
GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]

GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]


class LLMExtractor:
    def __init__(self):
        self.google_key = os.getenv("GOOGLE_API_KEY")
        self.groq_key = os.getenv("GROQ_API_KEY")

    def _build_prompt(self, page_text: str, prompt: str, fields: dict, limit: int, filter_desc: str) -> str:
        fields_str = "\n".join(f"- {k}: {v}" for k, v in fields.items())
        filter_note = f"\nUser Filter Intent: {filter_desc}" if filter_desc else ""
        return (
            f"User Request: {prompt}\n"
            f"Extract up to {limit} items. Fields to extract:\n{fields_str}\n"
            f"{filter_note}\n\n"
            f"CRITICAL RULES FOR FILTERING:\n"
            f"- STRICT RULE: Filter out items that are completely irrelevant (e.g. if the user wants 'mobile phones', do NOT extract phone cases, stands, chargers, or wires).\n"
            f"- PRICE RULE: Try to respect price limits (e.g. 'under 20000').\n"
            f"- FALLBACK RULE: If you cannot find {limit} items under the price limit on this page, YOU MUST RELAX THE PRICE FILTER and extract other relevant items (e.g. phones priced slightly higher) until you reach the {limit} item limit. It is better to return a phone slightly over budget than to return an empty list.\n\n"
            f"--- PAGE CONTENT ---\n{page_text}\n--- END ---\n\n"
            f"Return ONLY a JSON array."
        )

    async def extract(self, page_text: str, prompt: str, fields: dict, limit: int = 10, filter_desc: str = "") -> list:
        if not page_text or not page_text.strip():
            return []

        # ── Fast path: Try Gemini first (reliable, high context, no daily quota)
        gemini_text = page_text[:80000]
        gemini_prompt = f"{EXTRACT_SYSTEM}\n\n{self._build_prompt(gemini_text, prompt, fields, limit, filter_desc)}"

        if self.google_key:
            for model in GEMINI_MODELS:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.google_key}"
                    payload = {
                        "contents": [{"parts": [{"text": gemini_prompt}]}],
                        "generationConfig": {"temperature": 0.0}
                    }
                    async with aiohttp.ClientSession() as session:
                        async with session.post(url, json=payload) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                content = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                                parsed = self._parse(content)
                                if parsed is not None and len(parsed) > 0:
                                    logger.info(f"Extracted {len(parsed)} items via pure Gemini API/{model}")
                                    return parsed[:limit]
                                else:
                                    logger.warning(f"Gemini API/{model} returned empty list")
                            else:
                                logger.warning(f"Gemini API/{model} failed with HTTP {resp.status}: {await resp.text()}")
                except Exception as e:
                    logger.warning(f"Gemini API/{model} failed: {e}")

        # ── Fallback: Try Groq (fast, but strict daily limits on free tier) ───────
        groq_text = page_text[:2500] # Safe limit to avoid 413 Payload Too Large (6000 TPM limit)
        groq_prompt = self._build_prompt(groq_text, prompt, fields, limit, filter_desc)
        groq_messages = [
            SystemMessage(content=EXTRACT_SYSTEM),
            HumanMessage(content=groq_prompt)
        ]

        if self.groq_key:
            for model in GROQ_MODELS:
                try:
                    llm = ChatOpenAI(
                        model=model,
                        openai_api_key=self.groq_key,
                        openai_api_base="https://api.groq.com/openai/v1",
                        temperature=0,
                        max_tokens=4096,
                    )
                    resp = await llm.ainvoke(groq_messages)
                    parsed = self._parse(resp.content)
                    if parsed is not None and len(parsed) > 0:
                        logger.info(f"Extracted {len(parsed)} items via Groq/{model}")
                        return parsed[:limit]
                except Exception as e:
                    logger.warning(f"Groq/{model} failed: {e}")

        logger.error("All LLM providers exhausted")
        return []

    def _parse(self, raw: str) -> list:
        if not raw:
            return None
        raw = raw.strip()
        # Remove markdown fences
        raw = re.sub(r"^```(?:json)?\n?", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\n?```$", "", raw, flags=re.IGNORECASE)
        raw = raw.strip()

        def extract_array(data):
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for val in data.values():
                    if isinstance(val, list):
                        return val
            return []

        try:
            data = json.loads(raw)
            return extract_array(data)
        except Exception:
            # Fallback: find JSON array anywhere in the text
            match = re.search(r"\[[\s\S]*\]", raw)
            if match:
                try:
                    data = json.loads(match.group())
                    return extract_array(data)
                except Exception:
                    pass
        logger.warning(f"Failed to parse JSON. Snippet: {raw[:200]}")
        return []
