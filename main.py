"""
main.py — FastAPI Server — Universal AI Web Scraper
"""
import sys
import io

if sys.platform.startswith("win"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import asyncio
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import logging
import os
import csv
import re
from io import StringIO
from urllib.parse import urlparse, quote_plus

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
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

app = FastAPI(title="Universal Web Scraper")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

planner  = LLMPlanner()
scraper  = IntelligentScraper()
extractor = LLMExtractor()


class ScrapeRequest(BaseModel):
    url:    HttpUrl
    prompt: str
    limit:  int = 10
    export: str = "json"


# ── Static frontend ──────────────────────────────────────────────────────────
_dist = os.path.join(os.path.dirname(__file__), "frontend/dist")
if os.path.isdir(os.path.join(_dist, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(_dist, "assets")), name="assets")


@app.get("/")
async def root():
    index = os.path.join(_dist, "index.html")
    if not os.path.exists(index):
        raise HTTPException(status_code=404, detail="Run: cd frontend && npm run build")
    return FileResponse(index)


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Helpers ──────────────────────────────────────────────────────────────────
CORPORATE_KEYWORDS = [
    "about", "leadership", "team", "people", "contact",
    "careers", "who-we-are", "management", "executive"
]


def _score_link(link: dict, prompt: str) -> int:
    combined = f"{link.get('text', '')} {link.get('href', '')}".lower()
    prompt_l = prompt.lower()
    score = sum(10 for kw in CORPORATE_KEYWORDS if kw in combined)
    score += sum(5 for word in prompt_l.split() if len(word) > 3 and word in combined)
    return score


def _find_next_page(links: list, current_url: str) -> str:
    keywords = ["next", "›", "»", ">"]
    for link in links:
        text = link.get("text", "").strip().lower()
        href = link.get("href", "")
        if not href:
            continue
        if any(kw == text for kw in keywords) and current_url not in href:
            return href
    for link in links:
        text = link.get("text", "").strip().lower()
        href = link.get("href", "")
        if not href:
            continue
        if any(kw in text for kw in keywords) and len(text) < 15 and current_url not in href:
            return href
    return None


def _build_search_url(base_url: str, prompt: str) -> str:
    """Build a direct search URL from the user's prompt."""
    stop = {"give", "me", "list", "show", "find", "get", "the", "a", "an",
            "with", "and", "or", "of", "in", "on", "at", "to", "for",
            "items", "products", "results", "details", "name", "price",
            "rating", "20", "10", "50", "100", "25"}
    words = [w for w in re.sub(r'[^a-z0-9 ]', '', prompt.lower()).split() if w not in stop]
    query = quote_plus(' '.join(words[:8]))
    parsed = urlparse(base_url)
    domain = parsed.netloc.lower()

    if "amazon" in domain:
        return f"{parsed.scheme}://{parsed.netloc}/s?k={query}"
    elif "flipkart" in domain:
        return f"{parsed.scheme}://{parsed.netloc}/search?q={query}"
    elif "ebay" in domain:
        return f"{parsed.scheme}://{parsed.netloc}/sch/i.html?_nkw={query}"
    elif "shopclues" in domain:
        return f"https://m.shopclues.com/search?q={query}"
    else:
        return f"{parsed.scheme}://{parsed.netloc}/search?q={query}"


async def _smart_navigate(base_url: str, prompt: str, initial: dict) -> dict:
    """
    For corporate/info sites - try top relevant internal links.
    """
    links = initial.get("links", [])
    scored = sorted(
        [(l, _score_link(l, prompt)) for l in links if _score_link(l, prompt) > 0],
        key=lambda x: x[1],
        reverse=True
    )
    for link, score in scored[:3]:
        href = link.get("href", "")
        if not href or not href.startswith("http"):
            continue
        logger.info(f"Smart nav: trying [{link.get('text')}] score={score}")
        res = await scraper.load(href)
        if res["success"] and len(res["text"]) > 2000:
            return res
    return initial


def _is_garbage(text: str) -> bool:
    """Detect if a page returned garbage / no-results content."""
    garbage = ["mmMwWLliI", "0 items found", "no results found", "did not match", "404"]
    return len(text) < 500 or any(g in text for g in garbage)


async def _core_scrape(url: str, prompt: str, limit: int, export_format: str):
    """Main scraping logic."""
    # Force a fresh browser session per request to defeat Amazon IP/Session flagging
    await scraper.force_restart()
    
    is_ecommerce = any(x in url for x in ["amazon", "flipkart", "ebay", "shopclues", "books.toscrape"])
    is_corporate = not is_ecommerce

    # ── STEP 1: For e-commerce, go directly to search URL ─────────────────
    if is_ecommerce:
        search_url = _build_search_url(url, prompt)
        logger.info(f"E-commerce: loading search URL directly: {search_url}")
        listing = await scraper.load(search_url)
        if not listing["success"] or _is_garbage(listing.get("text", "")):
            logger.warning("Direct search URL failed, loading homepage...")
            listing = await scraper.load(url)
    else:
        # ── STEP 1b: For corporate/info sites, load homepage first ─────────
        logger.info(f"Corporate: loading homepage: {url}")
        initial = await scraper.load(url)
        if not initial["success"] or not initial["text"]:
            await asyncio.sleep(2)
            initial = await scraper.load(url)

        if not initial["success"]:
            return JSONResponse(status_code=502, content={
                "success": False,
                "error": "Website is down or blocking us. Please try again."
            })

        # Plan navigation (for corporate sites)
        logger.info("Planning navigation...")
        plan = await planner._plan_async(initial["text"], initial["links"], prompt, url, limit=limit)

        if plan.get("not_applicable"):
            return {
                "success": True, "not_applicable": True,
                "message": plan.get("not_applicable_reason", "Not found on this site."),
                "data": [], "count": 0
            }

        # Navigate
        listing = await scraper.execute_plan(url, plan)

        # If navigation gave garbage, try smart link crawler
        if not listing["success"] or _is_garbage(listing.get("text", "")):
            logger.warning("Navigation gave poor content. Trying smart link crawler...")
            listing = await _smart_navigate(url, prompt, initial)

        if not listing.get("text"):
            listing = initial

    # ── STEP 2: Plan for e-commerce (needed for fields/filter) ────────────
    if is_ecommerce:
        initial_for_plan = listing
        plan = await planner._plan_async(
            initial_for_plan["text"][:3000], initial_for_plan["links"][:30], prompt, url, limit=limit
        )
        if plan.get("not_applicable"):
            return {
                "success": True, "not_applicable": True,
                "message": plan.get("not_applicable_reason", "Not available on this site."),
                "data": [], "count": 0
            }
    
    extraction = plan.get("extraction", {})
    fields = extraction.get("fields", {"title": "item title", "price": "price"})
    filter_desc = extraction.get("filter", "")
    need_detail = plan.get("need_detail_pages", False)
    
    # E-commerce search pages have all the info we need. Fetching 20 detail pages 
    # gets us blocked instantly. Disable detail fetching for e-commerce.
    if is_ecommerce:
        need_detail = False

    # ── STEP 3: Harvest pages ─────────────────────────────────────────────
    all_texts = []
    current = listing
    pages = 0
    max_pages = 3

    while current and pages < max_pages:
        pages += 1
        logger.info(f"Harvesting page {pages}...")
        if need_detail:
            detail_texts = await _fetch_detail_pages(current, url, limit)
            all_texts.extend(detail_texts)
        else:
            all_texts.append(current["text"])

        if sum(len(t) for t in all_texts) > 80000:
            break

        next_url = _find_next_page(current["links"], current["url"])
        if not next_url:
            break
        await asyncio.sleep(1)
        current = await scraper.load(next_url)
        if not current.get("success") or current.get("blocked"):
            break

    # ── STEP 4: Extract ───────────────────────────────────────────────────
    combined = "\n\n---PAGE BREAK---\n\n".join(all_texts)
    logger.info(f"Extracting from {pages} page(s), {len(combined)} chars, limit={limit}...")

    data = await extractor.extract(combined, prompt, fields, limit=limit, filter_desc=filter_desc)

    # Retry fallback for corporate sites
    if not data and is_corporate:
        logger.warning("No data - trying smart nav fallback...")
        if 'initial' in dir():
            fb = await _smart_navigate(url, prompt, initial)
            if fb.get("text") and fb["text"] != listing.get("text", ""):
                data = await extractor.extract(fb["text"], prompt, fields, limit=limit)

    logger.info(f"Done. Extracted {len(data)} items from {pages} page(s).")

    if export_format == "csv" and data:
        return _export_csv(data)

    return {
        "success": True,
        "not_applicable": False,
        "data": data,
        "count": len(data),
        "pages_scraped": pages,
        "page_url": listing.get("url", url),
    }


@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    url    = str(req.url)
    prompt = req.prompt.strip()
    limit  = max(1, req.limit)

    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    logger.info(f"=== REQUEST === {url} | {prompt} | limit={limit}")

    try:
        result = await asyncio.wait_for(
            _core_scrape(url, prompt, limit, req.export),
            timeout=110  # 110 second hard limit
        )
        return result
    except asyncio.TimeoutError:
        logger.error("Scrape timed out after 110s")
        return JSONResponse(status_code=504, content={
            "success": False,
            "error": "Timed out (110s). Amazon is heavily protected. Try eBay or Books to Scrape, or retry."
        })
    except Exception as e:
        logger.exception("Unhandled error")
        raise HTTPException(status_code=500, detail=str(e))


async def _fetch_detail_pages(listing_page: dict, base_url: str, limit: int) -> list:
    links = listing_page.get("links", [])
    base_domain = urlparse(base_url).netloc
    skip = {"login", "signin", "cart", "checkout", "account", "policy",
            "terms", "contact", "help", "faq", "sitemap", "sort=", "filter="}

    candidates = []
    seen = set()
    for link in links:
        href = link.get("href", "")
        text = link.get("text", "").strip()
        if not href or not text or href in seen:
            continue
        if not href.startswith("http") or base_domain not in href:
            continue
        if any(kw in href.lower() for kw in skip):
            continue
        if len(text) > 3:
            candidates.append(href)
            seen.add(href)

    candidates = candidates[: limit * 2]
    sem = asyncio.Semaphore(5)

    async def fetch_one(href):
        async with sem:
            try:
                r = await scraper.load(href)
                return r.get("text", "")
            except Exception:
                return ""

    results = await asyncio.gather(*[fetch_one(h) for h in candidates])
    return [r for r in results if r.strip()]


def _export_csv(data: list):
    if not data:
        return StreamingResponse(iter([""]), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=results.csv"})
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=data[0].keys())
    writer.writeheader()
    writer.writerows(data)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=results.csv"}
    )
