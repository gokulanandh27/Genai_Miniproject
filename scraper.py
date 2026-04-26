"""
scraper.py - Universal Intelligent Stealth Scraper
- Singleton browser instance (no crash on reuse)
- Smart content-aware waiting per site type
- Profile rotation (Desktop / Mobile)
- Automatic fallback URL patterns
"""
import asyncio
import logging
import random
import re
from urllib.parse import urljoin, urlparse, quote_plus

from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from selectolax.parser import HTMLParser
import html2text

logger = logging.getLogger(__name__)

PROFILES = [
    {
        "name": "Windows Chrome",
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "viewport": {"width": 1280, "height": 800},
        "is_mobile": False,
    },
    {
        "name": "Mac Chrome",
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "viewport": {"width": 1440, "height": 900},
        "is_mobile": False,
    },
    {
        "name": "iPhone 14",
        "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        "viewport": {"width": 390, "height": 844},
        "is_mobile": True,
    },
]

# Product selectors by site domain — used for smart waiting
SITE_SELECTORS = {
    "amazon": [
        'div[data-component-type="s-search-result"]',
        '.s-main-slot .s-result-item',
        '#search .s-result-item',
    ],
    "flipkart": [
        'div[data-id]',
        '._1AtVbE',
        '.CXW8mj',
        'div._2kHMtA',
    ],
    "shopclues": [
        'div.column',
        'div.products',
        'ul.prd-grid-list',
        'div.prd_box',
    ],
    "ebay": ['li.s-item', '.srp-results .s-item'],
    "default": ['article', 'div.product', 'div.card', '.product-item', 'li.product'],
}

BLOCK_SIGNALS = [
    "captcha", "security challenge", "robot check",
    "verify you are human", "are you a robot",
    "unusual traffic", "access denied",
]


class IntelligentScraper:
    """Singleton-safe universal scraper."""

    _pw = None
    _browser = None

    async def _ensure_browser(self):
        """Start playwright and chromium if not already running."""
        try:
            # Check if existing browser is still alive
            if IntelligentScraper._browser:
                # Ping by creating a dummy context check
                _ = IntelligentScraper._browser.is_connected()
                if not IntelligentScraper._browser.is_connected():
                    raise Exception("Browser disconnected")
        except Exception:
            logger.info("Browser was dead, restarting...")
            IntelligentScraper._browser = None
            IntelligentScraper._pw = None

        if not IntelligentScraper._pw:
            IntelligentScraper._pw = await async_playwright().start()
        if not IntelligentScraper._browser:
            IntelligentScraper._browser = await IntelligentScraper._pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            logger.info("Browser started fresh.")

    def _get_selectors(self, url: str) -> list:
        """Return site-specific CSS selectors for smart waiting."""
        domain = urlparse(url).netloc.lower()
        for key, sels in SITE_SELECTORS.items():
            if key in domain:
                return sels
        return SITE_SELECTORS["default"]

    async def _clean_content(self, html: str) -> str:
        """Convert HTML to clean, LLM-friendly Markdown."""
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        h.body_width = 0
        h.ignore_emphasis = False
        
        # Simple noise reduction
        try:
            parser = HTMLParser(html)
            # Remove scripts, styles, nav, footer
            for tag in ["script", "style", "nav", "footer", "header", "aside"]:
                for el in parser.css(tag):
                    el.decompose()
            html = parser.html or html
        except Exception:
            pass
            
        return h.handle(html)

    async def _bypass_popups(self, page):
        """Tries to find and click 'Accept Cookies' or 'Close' buttons."""
        common_buttons = [
            "Accept", "Agree", "Allow", "Consent", "Continue", "OK", "I agree", 
            "Got it", "Close", "Accept All", "Allow All"
        ]
        for btn_text in common_buttons:
            try:
                # Case-insensitive text match for buttons
                btn = page.get_by_role("button", name=re.compile(f"^{btn_text}$", re.I))
                if await btn.is_visible():
                    await btn.click(timeout=2000)
                    logger.info(f"Bypassed popup using button: {btn_text}")
                    return
            except Exception:
                continue

    async def _smart_wait(self, page, url: str, timeout: int = 12000):
        """Wait for site-specific product content to appear."""
        selectors = self._get_selectors(url)
        combined = ", ".join(selectors)
        try:
            await page.wait_for_selector(combined, timeout=timeout)
            logger.info(f"Smart selector matched content on {url}")
        except Exception:
            logger.warning(f"Smart wait timed out on {url} — using raw page content")

    async def load(self, url: str, js_code: str = None) -> dict:
        """Load a URL with stealth and smart waiting. Returns dict with text/links/url/success."""
        await self._ensure_browser()

        profile = random.choice(PROFILES)
        logger.info(f"Profile: {profile['name']} → {url}")

        context = await IntelligentScraper._browser.new_context(
            user_agent=profile["ua"],
            viewport=profile["viewport"],
            is_mobile=profile["is_mobile"],
            has_touch=profile["is_mobile"],
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)

        try:
            # Human-like random delay before request
            await asyncio.sleep(random.uniform(1.0, 2.5))

            await page.goto(url, timeout=60000, wait_until="load")
            await asyncio.sleep(2)

            # Bypass popups (Accept Cookies etc)
            await self._bypass_popups(page)

            # Wait for JS-rendered product grids
            await self._smart_wait(page, url)

            # Realistic Scrolling
            try:
                for _ in range(random.randint(3, 5)):
                    await page.evaluate(f"window.scrollBy(0, {random.randint(500, 900)})")
                    await asyncio.sleep(1.5)
            except Exception as scroll_err:
                pass

            # Execute any JS-based search action
            if js_code:
                try:
                    await page.evaluate(js_code)
                    await asyncio.sleep(4)
                    await self._smart_wait(page, page.url)
                except Exception as je:
                    logger.warning(f"JS action failed: {je}")

            html = await page.content()
            tree = HTMLParser(html)

            # Check for bot-detection walls
            raw_text = tree.text().lower()
            if any(sig in raw_text for sig in BLOCK_SIGNALS) and len(raw_text) < 5000:
                logger.warning(f"Bot-detection wall hit on {url}")
                await context.close()
                return {"text": "", "html": html, "links": [], "url": page.url, "success": False, "blocked": True}

            # Extract links
            links = []
            seen_hrefs = set()
            for a in tree.css("a"):
                href = a.attributes.get("href", "")
                text = a.text(strip=True)
                if href and text and href not in seen_hrefs:
                    full_href = urljoin(url, href)
                    links.append({"text": text, "href": full_href})
                    seen_hrefs.add(href)

            # Clean and extract text using Markdown converter
            text = await self._clean_content(html)

            logger.info(f"Loaded {page.url} — {len(text)} chars, {len(links)} links")
            return {"text": text, "html": html, "links": links, "url": page.url, "success": True}

        except Exception as e:
            logger.error(f"Load failed for {url}: {e}")
            return {"text": "", "html": "", "links": [], "url": url, "success": False}
        finally:
            await context.close()

    async def close(self):
        """Gracefully shut down browser (only call on app shutdown)."""
        try:
            if IntelligentScraper._browser:
                await IntelligentScraper._browser.close()
        except Exception:
            pass
        try:
            if IntelligentScraper._pw:
                await IntelligentScraper._pw.stop()
        except Exception:
            pass
        IntelligentScraper._browser = None
        IntelligentScraper._pw = None

    async def execute_plan(self, base_url: str, plan: dict) -> dict:
        """Navigate according to the LLM plan and return final page content."""
        nav = plan.get("navigation", {})
        nav_type = nav.get("type", "direct")

        if nav_type == "direct":
            return await self.load(base_url)

        elif nav_type in ("url", "search"):
            target_url = nav.get("target_url", "").strip()
            query = nav.get("search_query", "").strip()

            # If a full URL was provided by the planner, use it directly
            if target_url and target_url.startswith("http"):
                logger.info(f"Direct search URL: {target_url}")
                result = await self.load(target_url)
                if result["success"] and len(result["text"]) > 500:
                    return result

            # Build search URL from known site patterns
            if query:
                parsed = urlparse(base_url)
                domain = parsed.netloc.lower()
                netloc = f"{parsed.scheme}://{parsed.netloc}"

                if "amazon" in domain:
                    candidates = [f"{netloc}/s?k={quote_plus(query)}"]
                elif "flipkart" in domain:
                    candidates = [f"{netloc}/search?q={quote_plus(query)}"]
                elif "shopclues" in domain:
                    candidates = [
                        f"https://m.shopclues.com/search?q={quote_plus(query)}",
                        f"{netloc}/search?q={quote_plus(query)}",
                    ]
                elif "ebay" in domain:
                    candidates = [f"{netloc}/sch/i.html?_nkw={quote_plus(query)}"]
                else:
                    candidates = [
                        f"{netloc}/search?q={quote_plus(query)}",
                        f"{netloc}/search?query={quote_plus(query)}",
                        f"{netloc}/search?keyword={quote_plus(query)}",
                        f"{netloc}/products?search={quote_plus(query)}",
                    ]

                for candidate in candidates:
                    logger.info(f"Trying search URL: {candidate}")
                    r = await self.load(candidate)
                    if r["success"] and len(r["text"]) > 500:
                        return r

            return await self.load(base_url)

        elif nav_type == "link":
            initial = await self.load(base_url)
            link_text = nav.get("link_text", "").lower().strip()
            for link in initial["links"]:
                if link_text in link["text"].lower():
                    logger.info(f"Following link: {link['href']}")
                    return await self.load(link["href"])
            logger.warning(f"Link '{link_text}' not found, using base page")
            return initial

        return await self.load(base_url)
