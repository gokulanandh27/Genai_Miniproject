"""
pagination.py — Smart Pagination Handler
Strategy: DOM heuristics FIRST (fast, free), LLM reasoning as FALLBACK (accurate for unknown sites).
This is the key architectural improvement over naive approaches.
"""

import re
import logging
from typing import Optional
from playwright.async_api import Page
from html_cleaner import HTMLCleaner

logger = logging.getLogger(__name__)

# ─── DOM-based next-page selector candidates (ordered by confidence) ──────────
NEXT_PAGE_SELECTORS = [
    # Semantic / ARIA
    "a[aria-label='Next page']",
    "a[aria-label='Next']",
    "button[aria-label='Next page']",
    "button[aria-label='Go to next page']",
    # Common class/id patterns
    "a.next", "a.next-page", ".pagination .next a", ".pagination-next a",
    "li.next a", "li.next > a",
    "[class*='next-page']", "[class*='nextpage']",
    # Text-content heuristics (handled separately in _find_by_text)
    # Amazon-specific
    "a[href*='page=']:last-of-type",
    ".s-pagination-next",
    # Generic rel=next
    "a[rel='next']",
]

# Text patterns that strongly indicate a "next" button
NEXT_TEXT_PATTERNS = re.compile(
    r"^\s*(next|next\s*page|›|»|→|>\s*|next\s*›)\s*$",
    re.IGNORECASE,
)


class PaginationHandler:
    """
    Handles multi-page traversal with a 3-tier detection strategy:

    Tier 1: rel="next" link header (fastest, standards-based)
    Tier 2: DOM selector heuristics (fast, works for 80% of sites)
    Tier 3: LLM reasoning on HTML snippet (slow but accurate for novel sites)

    Each page's cleaned HTML is yielded for the extraction layer.
    """

    def __init__(self, page: Page, max_pages: int = 5, llm_client=None):
        self.page = page
        self.max_pages = max_pages
        self.llm_client = llm_client  # Optional — only used in Tier 3
        self.cleaner = HTMLCleaner()
        self._visited_urls: set[str] = set()

    async def collect_all_pages(self) -> list[dict]:
        """
        Iterate through pages, returning list of:
          { "page_num": int, "url": str, "html": str }
        """
        pages_data = []
        current_page = 1

        while current_page <= self.max_pages:
            url = self.page.url
            if url in self._visited_urls:
                logger.warning(f"Loop detected at {url}, stopping pagination.")
                break
            self._visited_urls.add(url)

            logger.info(f"Processing page {current_page}: {url}")

            # Scroll to load lazy content
            await self._scroll_page()

            # Collect HTML
            html = await self.page.content()
            cleaned = self.cleaner.clean(html)
            pages_data.append({
                "page_num": current_page,
                "url": url,
                "html": cleaned,
            })

            # Try to navigate to next page
            next_found = await self._navigate_next()
            if not next_found:
                # If no next button, maybe it's infinite scroll?
                # If current_page < max_pages, try to scroll more and see if content changed
                logger.info(f"No next page found after page {current_page}. Checking for infinite scroll...")
                old_height = await self.page.evaluate("document.body.scrollHeight")
                await self._scroll_page()
                new_height = await self.page.evaluate("document.body.scrollHeight")
                
                if new_height > old_height:
                    logger.info("Content expanded after scroll. Continuing extraction.")
                    # We don't increment current_page because it's technically still the same DOM, 
                    # but we'll allow it to continue until max_pages is hit or height stops growing.
                    current_page += 1
                    continue
                else:
                    logger.info("No next page and height didn't increase. Done.")
                    break

            current_page += 1
            # Wait for new content
            try:
                await self.page.wait_for_load_state("domcontentloaded", timeout=self.timeout)
                await self.page.wait_for_timeout(2000)
            except Exception:
                await self.page.wait_for_timeout(2000)

        return pages_data

    # ── Navigation ────────────────────────────────────────────────────────────

    async def _navigate_next(self) -> bool:
        """Try all tiers to find and click next page. Returns True if navigated."""

        # Tier 1: <link rel="next"> in <head>
        next_url = await self.page.evaluate("""
            () => {
                const link = document.querySelector('link[rel="next"]');
                return link ? link.href : null;
            }
        """)
        if next_url:
            logger.debug(f"Tier 1 (rel=next): {next_url}")
            await self.page.goto(next_url, wait_until="domcontentloaded")
            return True

        # Tier 2: DOM selector heuristics
        for selector in NEXT_PAGE_SELECTORS:
            try:
                el = await self.page.query_selector(selector)
                if el and await el.is_visible() and await el.is_enabled():
                    # Verify it's not disabled/current
                    classes = await el.get_attribute("class") or ""
                    aria_disabled = await el.get_attribute("aria-disabled") or ""
                    if "disabled" in classes.lower() or aria_disabled == "true":
                        continue
                    logger.debug(f"Tier 2 (DOM selector): {selector}")
                    await el.scroll_into_view_if_needed()
                    await el.click()
                    return True
            except Exception:
                pass

        # Tier 2b: Text-based scan
        text_match = await self._find_by_text()
        if text_match:
            logger.debug("Tier 2b (text match): next button found")
            await text_match.scroll_into_view_if_needed()
            await text_match.click()
            return True

        # Tier 3: LLM-based reasoning (only if llm_client provided)
        if self.llm_client:
            return await self._llm_find_next()

        return False

    async def _find_by_text(self):
        """Find anchor/button whose visible text matches next-page patterns."""
        elements = await self.page.query_selector_all("a, button")
        for el in elements:
            try:
                text = (await el.inner_text()).strip()
                if NEXT_TEXT_PATTERNS.match(text):
                    if await el.is_visible() and await el.is_enabled():
                        classes = await el.get_attribute("class") or ""
                        if "disabled" not in classes.lower():
                            return el
            except Exception:
                pass
        return None

    async def _llm_find_next(self) -> bool:
        """
        Tier 3: Send pagination-relevant HTML snippet to LLM.
        Asks for the CSS selector of the next button.
        Only activates for sites where DOM heuristics fail.
        """
        try:
            # Extract only the pagination region to minimize tokens
            pagination_html = await self.page.evaluate("""
                () => {
                    const candidates = [
                        document.querySelector('[class*="pagination"]'),
                        document.querySelector('[class*="paging"]'),
                        document.querySelector('nav[aria-label*="page" i]'),
                        document.querySelector('footer'),
                    ];
                    for (const el of candidates) {
                        if (el) return el.outerHTML.substring(0, 3000);
                    }
                    return document.body.innerHTML.substring(
                        Math.max(0, document.body.innerHTML.length - 5000)
                    );
                }
            """)

            prompt = f"""You are a web scraping assistant. Analyze this HTML and find the "next page" element.
            
HTML snippet:
{pagination_html}

Return ONLY a JSON object:
{{
  "found": true/false,
  "selector": "CSS selector string or null",
  "reason": "brief explanation"
}}

Rules:
- Return the most specific CSS selector for the next-page button/link
- Return found: false if there is no next page or it's disabled
- DO NOT guess — only return found: true if you see a clear next-page element"""

            response = await self.llm_client.ainvoke(prompt)
            import json
            result = json.loads(response.content.strip())

            if result.get("found") and result.get("selector"):
                el = await self.page.query_selector(result["selector"])
                if el and await el.is_visible():
                    logger.info(f"Tier 3 (LLM): found next via selector '{result['selector']}'")
                    await el.click()
                    return True
        except Exception as e:
            logger.warning(f"LLM pagination fallback failed: {e}")

        return False

    # ── Scroll helper ─────────────────────────────────────────────────────────

    async def _scroll_page(self):
        """Scroll to bottom to trigger lazy-loaded content."""
        await self.page.evaluate("""
            async () => {
                await new Promise(resolve => {
                    let last = 0;
                    const check = setInterval(() => {
                        window.scrollBy(0, 400);
                        const cur = window.scrollY + window.innerHeight;
                        if (cur >= document.body.scrollHeight || cur === last) {
                            clearInterval(check);
                            resolve();
                        }
                        last = cur;
                    }, 200);
                });
            }
        """)
        await self.page.wait_for_timeout(800)
