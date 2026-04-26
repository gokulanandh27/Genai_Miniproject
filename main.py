"""
main.py — FastAPI Server — ScraperBot v3
Simple 2-input scraper: URL + Prompt → structured data
"""
import sys
import io

# Force UTF-8 encoding for Windows consoles
if sys.platform.startswith("win"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
import asyncio

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import logging
import os
from urllib.parse import urljoin
import csv
from io import StringIO
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, HttpUrl
from dotenv import load_dotenv

from planner import LLMPlanner
from scraper import IntelligentScraper
from extractor import LLMExtractor

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="ScraperBot", description="Intelligent LLM-guided web scraper", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

planner = LLMPlanner()
scraper = IntelligentScraper()
extractor = LLMExtractor()


class ScrapeRequest(BaseModel):
    url: HttpUrl
    prompt: str
    limit: int = 10
    export: str = "json" # "json" or "csv"


from fastapi.staticfiles import StaticFiles

# Serve React build
app.mount("/assets", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "frontend/dist/assets")), name="assets")

@app.get("/")
async def root():
    # Return index.html from dist
    return FileResponse(os.path.join(os.path.dirname(__file__), "frontend/dist/index.html"))

# Also handle icons.svg if present in dist
@app.get("/icons.svg")
async def icons():
    return FileResponse(os.path.join(os.path.dirname(__file__), "frontend/dist/icons.svg"))


@app.get("/health")
async def health():
    return {"status": "ok", "version": "3.0.0"}


@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    url = str(req.url)
    prompt = req.prompt.strip()
    limit = req.limit

    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    logger.info(f"Request → URL: {url} | Prompt: {prompt}")

    try:
        # ── Step 1: Load initial page (with retry) ────────────────────────────────────
        logger.info("Step 1: Loading initial page...")
        initial = await scraper.load(url)

        if not initial["success"] or not initial["text"]:
            logger.warning("Initial load failed. Retrying with different profile...")
            await asyncio.sleep(2)
            initial = await scraper.load(url)
            
        if not initial["success"] or not initial["text"]:
            return JSONResponse(
                status_code=502,
                content={"success": False, "error": "The website is blocking requests or is currently down. Please try a different URL or try again later."},
            )

        # ── Step 2: LLM plans navigation ─────────────────────────────────
        logger.info("Step 2: Planning navigation...")
        plan = await asyncio.to_thread(
            planner.plan,
            initial["text"],
            initial["links"],
            prompt,
            url,
            limit=limit
        )

        # ── Step 3: Check if site is relevant ────────────────────────────
        if plan.get("not_applicable"):
            reason = plan.get("not_applicable_reason", "The requested information is not available on this website.")
            return {
                "success": True,
                "not_applicable": True,
                "message": reason,
                "data": [],
                "count": 0,
            }

        # ── Step 3: Execute navigation ───────────────────────────────────
        try:
            logger.info(f"Step 3: Navigating to {plan['navigation'].get('target_url') or url}...")
            listing = await scraper.execute_plan(url, plan)
        except Exception as nav_err:
            logger.warning(f"Navigation failed: {nav_err}. Falling back to direct extraction.")
            listing = initial

        if listing.get("blocked"):
            return {
                "success": False,
                "not_applicable": True,
                "message": "Access was blocked by the website (CAPTCHA/Robot Check). Please try again later.",
                "data": [],
                "count": 0
            }
        
        if not listing.get("text"):
            listing = initial  # fallback

        # ── Step 4: Multi-Page Harvesting ───────────────────────────────
        extraction = plan.get("extraction", {})
        fields = extraction.get("fields", {"title": "item title", "description": "description"})
        limit = req.limit
        filter_desc = extraction.get("filter", "")
        need_detail = plan.get("need_detail_pages", False)

        all_page_texts = []
        current_page = listing
        pages_scraped = 0
        max_pages = 20
        final_url = url

        while current_page and pages_scraped < max_pages:
            pages_scraped += 1
            final_url = current_page["url"]
            logger.info(f"Harvesting page {pages_scraped}...")
            
            if need_detail:
                detail_texts = await _fetch_detail_pages(
                    listing_page=current_page,
                    base_url=url,
                    prompt=prompt,
                    limit=limit,
                )
                if detail_texts:
                    all_page_texts.extend(detail_texts)
            else:
                all_page_texts.append(current_page["text"])

            # Harvest text until we have enough pages to satisfy the limit
            if pages_scraped >= 5: # Safety cap to prevent infinite crawling
                break

            # Find next page
            next_url = _find_next_page(current_page["links"], current_page["url"])
            if next_url and pages_scraped < max_pages:
                logger.info(f"Found next page: {next_url}. Loading...")
                await asyncio.sleep(1)
                current_page = await scraper.load(next_url)
                if current_page.get("blocked"):
                    logger.warning("Next page was blocked. Stopping.")
                    break
            else:
                break

        # ── Step 5: Final Extraction ────────────────────────────────────
        combined_text = "\n\n---PAGE BREAK---\n\n".join(all_page_texts)
        logger.info(f"Step 5: Extracting up to {limit} items from {len(all_page_texts)} pages of content...")
        all_data = await extractor.extract(
            page_text=combined_text,
            prompt=prompt,
            fields=fields,
            limit=limit,
            filter_desc=filter_desc,
        )

        # ── Step 5.5: Intelligent Retry for empty results ───────────────
        if not all_data and pages_scraped == 1:
            logger.info("No data found. Retrying with session warmup...")
            await scraper.load(url) # Visit home
            await asyncio.sleep(2)
            retry_listing = await scraper.execute_plan(url, plan)
            if retry_listing["text"]:
                all_data = await extractor.extract(
                    page_text=retry_listing["text"],
                    prompt=prompt,
                    fields=fields,
                    limit=limit,
                    filter_desc=filter_desc,
                )

        logger.info(f"Done. Extracted {len(all_data)} items across {pages_scraped} pages.")
        
        # ── Step 6: Export Handling ─────────────────────────────────────
        if req.export == "csv" and all_data:
            return _export_csv(all_data, final_url)
            
        return {
            "success": True,
            "not_applicable": False,
            "data": all_data,
            "count": len(all_data),
            "page_url": final_url,
        }

    except Exception as e:
        logger.exception("Unhandled error in /scrape")
        raise HTTPException(status_code=500, detail=str(e))


async def _fetch_detail_pages(
    listing_page: dict, base_url: str, prompt: str, limit: int
) -> list[str]:
    """
    From a listing page, identify item links and fetch each one.
    Returns a list of page text strings (one per detail page).
    """
    links = listing_page.get("links", [])
    page_base = listing_page.get("url", base_url)

    # Filter links that look like item/product/detail pages
    # Heuristic: longer paths, avoid category/filter/nav links
    candidate_links = []
    skip_keywords = {
        "login", "signin", "register", "cart", "checkout", "account",
        "policy", "terms", "contact", "about", "help", "faq", "sitemap",
        "category", "catalogue/category", "page-", "?page", "sort=",
    }
    for link in links:
        href = link.get("href", "")
        text = link.get("text", "").strip()
        if not href or not text:
            continue
        href_lower = href.lower()
        if any(kw in href_lower for kw in skip_keywords):
            continue
        # Must be on the same domain
        if base_url.split("/")[2] not in href:
            continue
        if len(text) > 3 and href not in candidate_links:
            candidate_links.append(href)

    # Limit to what we need (fetch up to limit*2 candidates, return limit results)
    candidate_links = candidate_links[: limit * 2]
    logger.info(f"Found {len(candidate_links)} candidate detail links")

    if not candidate_links:
        return []

    # Fetch detail pages concurrently (max 5 at a time)
    sem = asyncio.Semaphore(5)

    async def fetch_one(link: str) -> str:
        async with sem:
            try:
                result = await scraper.load(link)
                return result.get("text", "")
            except Exception as e:
                logger.warning(f"Detail page failed: {link} — {e}")
                return ""

    tasks = [fetch_one(link) for link in candidate_links]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r.strip()]

def _find_next_page(links: list, current_url: str) -> str:
    """Heuristic to find a 'Next' page link."""
    keywords = ["next", "next page", "›", "»", ">", "older", "page 2"]
    
    # Try exact matches first
    for link in links:
        text = link.get("text", "").strip().lower()
        href = link.get("href", "")
        if text in keywords and href and current_url not in href:
            return href
            
    # Try partial matches
    for link in links:
        text = link.get("text", "").strip().lower()
        href = link.get("href", "")
        if any(kw in text for kw in keywords) and href and len(text) < 15 and current_url not in href:
            return href
            
    return None

def _export_csv(data: list, url: str):
    output = StringIO()
    if not data:
        return StreamingResponse(iter([""]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=results.csv"})
        
    writer = csv.DictWriter(output, fieldnames=data[0].keys())
    writer.writeheader()
    writer.writerows(data)
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=results.csv"}
    )
