"""
planner.py — LLM Navigation Planner
Reads the webpage structure and user prompt, returns a JSON navigation plan.
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

PLANNER_SYSTEM = """You are an expert web scraping navigation planner.

Given a webpage's content and a user's natural language request, produce a JSON navigation plan.

Return ONLY valid JSON (no markdown fences, no explanation):
{
  "not_applicable": false,
  "not_applicable_reason": "",
  "navigation": {
    "type": "direct",
    "target_url": "",
    "link_text": "",
    "search_query": ""
  },
  "need_detail_pages": false,
    "extraction": {
    "fields": {
      "title": "the item title",
      "price": "the price",
      "rating": "star rating",
      "description": "full description text"
    },
    "limit": 50,
    "filter": ""
  }
}

Navigation type rules:
- "direct"  → data is already visible on this page, extract now
- "search"  → HIGHLY PREFERRED for specific items, products, or filtering (e.g. "laptops under 50000", "horror books"). Set BOTH `search_query` AND `target_url` to the site's search URL format if known (e.g. https://www.amazon.in/s?k=laptop+under+50000).
- "link"    → click a sidebar/nav link (set link_text). Use ONLY if search is not an option.
- "url"     → go directly to a specific URL (set target_url)

"need_detail_pages" rules:
- Set to TRUE if the user wants detailed info (description, full specs, full content)
  that is typically only shown on individual item/product/article pages, not listing pages.
- Set to FALSE if the listing page itself has all the needed info (title, price, rating).
- EXAMPLES:
  - "give me the description of Book X" → need_detail_pages: true
  - "list top 5 horror books with title and price" → need_detail_pages: false
  - "description of A Light in the Attic and Sharp Objects" → need_detail_pages: true
  - "top 5 laptops under 70000" → need_detail_pages: false

Important rules:
- STRICT RULE FOR not_applicable: If the user's prompt is asking for products, categories, or information that CLEARLY do not exist on this website (e.g., asking for laptops on a bookstore site, or cars on a cooking site), you MUST set "not_applicable": true and provide a reason. Do not try to extract unrelated items.
- For filters like "top 5", "under 70000", "5-star only" → put in extraction.filter
- Only include fields likely present on the page
- limit = {limit} (STRICTLY USE THIS NUMBER)
"""

FALLBACK_MODELS = [
    ("groq", "llama-3.3-70b-versatile"),
    ("groq", "llama-3.1-8b-instant"),
    ("gemini", "gemini-2.5-flash-lite"),
    ("gemini", "gemini-2.0-flash"),
    ("gemini", "gemini-1.5-flash"),
]

class LLMPlanner:
    def __init__(self):
        self.google_key = os.getenv("GOOGLE_API_KEY")
        self.groq_key = os.getenv("GROQ_API_KEY")
        self.sf_key = os.getenv("SILICONFLOW_API_KEY")

    def plan(self, page_text: str, page_links: list, prompt: str, url: str, limit: int = 50) -> dict:
        """Synchronous wrapper for _plan_async."""
        return asyncio.run(self._plan_async(page_text, page_links, prompt, url, limit))

    async def _plan_async(self, page_text: str, page_links: list, prompt: str, url: str, limit: int = 50) -> dict:
        """Call LLMs with fallback to produce a navigation plan."""
        truncated = page_text[:3000]
        links_str = "\n".join(
            f"  [{l.get('text','').strip()[:40]}] → {l.get('href','')[:60]}"
            for l in page_links[:50]
            if l.get("text", "").strip()
        )

        user_msg = (
            f"Website URL: {url}\n"
            f"User Request: {prompt}\n"
            f"Target Limit: {limit}\n\n"
            f"Page Text (truncated):\n{truncated}\n\n"
            f"Links on page:\n{links_str}\n\n"
            f"Return the navigation plan JSON."
        )

        for provider, model in FALLBACK_MODELS:
            try:
                result = await self._call(provider, model, user_msg)
                if result is not None:
                    logger.info(
                        f"Plan via {provider}/{model}: type={result.get('navigation',{}).get('type')}, "
                        f"need_detail_pages={result.get('need_detail_pages')}, "
                        f"not_applicable={result.get('not_applicable')}"
                    )
                    return result
            except Exception as e:
                logger.warning(f"Planner fallback {provider}/{model} failed: {e}")
                continue

        logger.error("All LLM providers for planner exhausted")
        return {
            "not_applicable": False,
            "not_applicable_reason": "",
            "need_detail_pages": False,
            "navigation": {"type": "direct", "target_url": "", "link_text": "", "search_query": ""},
            "extraction": {
                "fields": {"title": "item title", "description": "description"},
                "limit": limit,
                "filter": "",
            },
        }

    async def _call(self, provider: str, model: str, user_msg: str):
        if provider == "gemini":
            if not self.google_key:
                return None
            llm = ChatGoogleGenerativeAI(
                model=model, 
                google_api_key=self.google_key, 
                temperature=0,
                max_retries=0 # Immediate fallback on quota error
            )
            resp = await llm.ainvoke(
                [SystemMessage(content=PLANNER_SYSTEM), HumanMessage(content=user_msg)]
            )
            return self._parse(resp.content)

        elif provider == "groq":
            if not self.groq_key:
                return None
            llm = ChatOpenAI(
                model=model,
                openai_api_key=self.groq_key,
                openai_api_base="https://api.groq.com/openai/v1",
                temperature=0,
                max_tokens=2048,
            )
            resp = await llm.ainvoke(
                [SystemMessage(content=PLANNER_SYSTEM), HumanMessage(content=user_msg)]
            )
            return self._parse(resp.content)

        elif provider == "siliconflow":
            if not self.sf_key:
                return None
            llm = ChatOpenAI(
                model=model,
                openai_api_key=self.sf_key,
                openai_api_base="https://api.siliconflow.cn/v1",
                temperature=0,
                max_tokens=2048,
            )
            resp = await llm.ainvoke(
                [SystemMessage(content=PLANNER_SYSTEM), HumanMessage(content=user_msg)]
            )
            return self._parse(resp.content)

        return None

    def _parse(self, raw: str) -> dict:
        if not raw:
            return None
        raw = raw.strip()
        raw = re.sub(r"^```(?:json)?\n?", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\n?```$", "", raw, flags=re.IGNORECASE)
        try:
            return json.loads(raw)
        except Exception:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except Exception:
                    pass
        return None
