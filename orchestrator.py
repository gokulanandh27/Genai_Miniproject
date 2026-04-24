"""
orchestrator.py — Multi-Field Scraping Orchestrator
Coordinates parallel field scraping, result merging, and export.
This is the main entry point called by FastAPI.
"""

import asyncio
import logging
from dataclasses import dataclass, field, asdict
from typing import Literal
import json
import csv
import io

from scraper import PlaywrightScraper
from extractor import LLMExtractor
from validator import OutputValidator, ValidationResult

logger = logging.getLogger(__name__)


@dataclass
class ScrapeRequest:
    url: str
    fields: list[str]
    max_pages: int = 5
    export_format: Literal["json", "csv"] = "json"
    llm_provider: str = "claude"
    proxy: dict = None
    search_query: str = ""
    filter_description: str = ""


@dataclass
class ScrapeResponse:
    success: bool
    data: list[dict] = field(default_factory=list)
    validation: dict = field(default_factory=dict)
    export_csv: str = ""        # populated if export_format="csv"
    fields_searched: list[str] = field(default_factory=list)
    total_pages_scraped: int = 0
    error: str = ""


class ScrapingOrchestrator:
    """
    Orchestrates the full pipeline for one ScrapeRequest:

    1. For each field → spin up a scrape+extract task (parallel)
    2. Merge all results
    3. Validate merged output
    4. Format and return

    Why parallel per-field? Each field may require a different search query
    on the target site (e.g. search "smartwatch" then "mobile phone").
    Running them sequentially would be 2x–Nx slower.
    """

    def __init__(self):
        self.validator = OutputValidator()

    async def run(self, request: ScrapeRequest) -> ScrapeResponse:
        logger.info(f"Orchestrator: url={request.url}, fields={request.fields}")

        if not request.fields:
            return ScrapeResponse(success=False, error="No fields provided.")

        # Deduplicate and clean fields
        fields = list(dict.fromkeys(f.strip() for f in request.fields if f.strip()))

        # Optimization: If search_query is provided, we scrape ONCE and extract ALL fields
        if request.search_query:
            logger.info(f"Global search query provided: '{request.search_query}'. Scraping once.")
            result = await self._scrape_field(request, fields)
            all_items = result.get("items", [])
            total_pages = result.get("pages", 0)
            errors = result.get("errors", [])
        else:
            # Fallback to parallel per-field scraping (legacy/diverse search mode)
            tasks = [
                self._scrape_field(request, [field_query])
                for field_query in fields
            ]
            results_per_field = await asyncio.gather(*tasks, return_exceptions=True)
            
            all_items = []
            total_pages = 0
            errors = []

            for idx, result in enumerate(results_per_field):
                if isinstance(result, Exception):
                    errors.append(f"Field '{fields[idx]}': {str(result)}")
                elif isinstance(result, dict):
                    all_items.extend(result.get("items", []))
                    total_pages += result.get("pages", 0)

        if not all_items and errors:
            return ScrapeResponse(
                success=False,
                error=f"Scrape failed. Errors: {'; '.join(errors)}",
                fields_searched=fields,
            )

        # Validate
        validation: ValidationResult = self.validator.validate(all_items, fields)

        response = ScrapeResponse(
            success=validation.is_valid,
            data=validation.items,
            validation=validation.summary(),
            fields_searched=fields,
            total_pages_scraped=total_pages,
            error=validation.error_message if not validation.is_valid else "",
        )

        if request.export_format == "csv" and validation.items:
            response.export_csv = self._to_csv(validation.items)

        return response

    # ── Per-field pipeline ────────────────────────────────────────────────────

    async def _scrape_field(self, request: ScrapeRequest, field_queries: list[str]) -> dict:
        """
        Full pipeline: scrape → extract → tag
        Now supports multiple field queries for a single scrape.
        """
        scraper = PlaywrightScraper(config={
            "max_pages": request.max_pages,
            "headless": True,
            "proxy": request.proxy,
        })
        extractor = LLMExtractor(llm_provider=request.llm_provider)

        # 1. Scrape pages
        # If no explicit search_query is provided, use the first field as a fallback
        # This preserves the original behavior while allowing explicit search.
        scrape_fields = []
        if request.search_query:
            scrape_fields = [request.search_query]
        elif field_queries:
            scrape_fields = [field_queries[0]]
        
        try:
            pages_data = await scraper.scrape(
                request.url, 
                scrape_fields, 
                filter_description=request.filter_description
            )
        except Exception as e:
            logger.error(f"Scrape failed: {e}")
            return {"items": [], "pages": 0, "errors": [str(e)]}

        # 2. Extract structured items from HTML using all field prompts
        # We merge all field prompts into one extraction call for efficiency
        items = await extractor.extract(pages_data, field_queries, request.url)

        # 3. Tag items with a generic field query if multiple provided
        for item in items:
            if "_field_query" not in item:
                item["_field_query"] = ", ".join(field_queries)

        logger.info(f"Extracted {len(items)} items from {len(pages_data)} page(s)")
        return {"items": items, "pages": len(pages_data)}

    # ── Export ────────────────────────────────────────────────────────────────

    def _to_csv(self, items: list[dict]) -> str:
        if not items:
            return ""
        # Flatten all keys
        all_keys = sorted({k for item in items for k in item.keys()
                           if not k.startswith("_")})
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        for item in items:
            row = {k: item.get(k, "") for k in all_keys}
            # Flatten nested extra dict
            extra = item.get("extra", {})
            if isinstance(extra, dict):
                for ek, ev in extra.items():
                    if ek not in row:
                        row[ek] = ev
            writer.writerow(row)
        return output.getvalue()
