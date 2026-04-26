"""
extractor.py — LLM-powered structured data extractor
Uses Gemini → Groq → SiliconFlow fallback chain for resilience.
"""
import os
import json
import logging
import re
import asyncio

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger(__name__)

EXTRACT_SYSTEM = """You are a master data extraction engine.

IDENTIFY INTENT:
1. SINGULAR FACTS: If the user asks for a specific fact (e.g., "CEO name", "Headquarters"), extract ONLY that single best answer.
2. REPEATING DATA: If the user asks for a list (e.g., "laptops", "job openings"), extract every matching row.

Rules:
- Return ONLY a JSON list of objects: [{"field1": "val", ...}]
- For REPEATING data, extract AS MANY items as possible up to the limit.
- For SINGULAR facts, return a list with exactly ONE object containing the fact.
- Clean all values: remove HTML, extra whitespace, and noisy labels.
- Do not add explanations. Return pure JSON starting with `[` and ending with `]`.
"""

# Ordered fallback models
FALLBACK_MODELS = [
    ("groq", "llama-3.3-70b-versatile"),
    ("groq", "llama-3.1-8b-instant"),
    ("gemini", "gemini-2.5-flash-lite"),
    ("gemini", "gemini-2.0-flash"),
    ("gemini", "gemini-1.5-flash"),
]


class LLMExtractor:
    def __init__(self):
        self.google_key = os.getenv("GOOGLE_API_KEY")
        self.groq_key = os.getenv("GROQ_API_KEY")
        self.sf_key = os.getenv("SILICONFLOW_API_KEY")

    def _build_prompt(self, page_text: str, prompt: str, fields: dict, limit: int, filter_desc: str) -> str:
        fields_str = "\n".join(f"- {k}: {v}" for k, v in fields.items())
        filter_note = f"\nFilter: {filter_desc}" if filter_desc else ""
        return (
            f"User Request: {prompt}\n"
            f"EXTRACT AS MANY ITEMS AS POSSIBLE, up to a maximum of {limit} items.\n"
            f"Return the data with these fields:\n{fields_str}"
            f"{filter_note}\n\n"
            f"Page Content:\n{page_text}\n\n"
            f"Return ONLY a JSON array."
        )

    async def extract(self, page_text: str, prompt: str, fields: dict, limit: int = 10, filter_desc: str = "") -> list:
        if not page_text.strip():
            return []

        # ── 1. Try Groq (Fastest/Reliable) ────────────
        groq_text = page_text[:40000] # Safe limit for Llama-3 70b
        messages = [
            SystemMessage(content=EXTRACT_SYSTEM),
            HumanMessage(content=self._build_prompt(groq_text, prompt, fields, limit, filter_desc))
        ]
        for model in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]:
            try:
                if not self.groq_key: break
                llm = ChatOpenAI(
                    model=model,
                    openai_api_key=self.groq_key,
                    openai_api_base="https://api.groq.com/openai/v1",
                    temperature=0,
                    max_tokens=4096,
                )
                resp = await llm.ainvoke(messages)
                parsed = self._parse(resp.content)
                if parsed is not None:
                    logger.info(f"Extracted {len(parsed)} items via groq/{model}")
                    return parsed[:limit]
            except Exception as e:
                logger.warning(f"Extractor fallback groq/{model} failed: {e}")

        # ── 2. Try Gemini (High Context) ──────────────
        gemini_text = page_text[:150000]
        messages = [
            SystemMessage(content=EXTRACT_SYSTEM),
            HumanMessage(content=self._build_prompt(gemini_text, prompt, fields, limit, filter_desc))
        ]
        for model in ["gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-1.5-flash"]:
            try:
                if not self.google_key: break
                llm = ChatGoogleGenerativeAI(
                    model=model, 
                    google_api_key=self.google_key, 
                    temperature=0,
                    max_retries=0
                )
                resp = await llm.ainvoke(messages)
                parsed = self._parse(resp.content)
                if parsed is not None:
                    logger.info(f"Extracted {len(parsed)} items via {model}")
                    return parsed[:limit]
            except Exception as e:
                logger.warning(f"Extractor fallback {model} failed: {e}")

        # ── 3. Try SiliconFlow ──────────────────────────
        for model in ["deepseek-ai/DeepSeek-V3"]:
            try:
                if not self.sf_key: break
                llm = ChatOpenAI(
                    model=model,
                    openai_api_key=self.sf_key,
                    openai_api_base="https://api.siliconflow.cn/v1",
                    temperature=0,
                    max_tokens=4096,
                )
                resp = await llm.ainvoke(messages)
                parsed = self._parse(resp.content)
                if parsed is not None:
                    logger.info(f"Extracted {len(parsed)} items via siliconflow/{model}")
                    return parsed[:limit]
            except Exception as e:
                logger.warning(f"Extractor fallback siliconflow/{model} failed: {e}")

        logger.error("All LLM providers exhausted")
        return []

    def _parse(self, raw: str) -> list:
        if not raw:
            return None
        raw = raw.strip()
        # Remove markdown fences
        raw = re.sub(r"^```(?:json)?\n?", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\n?```$", "", raw, flags=re.IGNORECASE)
        
        # Helper to find array inside dict
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
            # Fallback regex to find array
            match = re.search(r"\[[\s\S]*\]", raw)
            if match:
                try:
                    data = json.loads(match.group())
                    return extract_array(data)
                except Exception:
                    pass
        logger.warning(f"Failed to parse JSON from LLM response. Snippet: {raw[:100]}")
        return []