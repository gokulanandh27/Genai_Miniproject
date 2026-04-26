"""
scraper.py - Universal Intelligent Stealth Scraper
- Singleton browser instance (no crash on reuse)
- Smart content-aware waiting per site type
- Profile rotation (Desktop / Mobile)
- Automatic fallback URL patterns
- Anti-detection hardening
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

# Browser profiles for rotation
PROFILES = [
    {
        "name": "Windows Chrome 124",
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "viewport": {"width": 1366, "height": 768},
        "is_mobile": False,
    },
    {
        "name": "Windows Chrome 123",
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "viewport": {"width": 1440, "height": 900},
        "is_mobile": False,
    },
    {
        "name": "Mac Chrome 124",
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "viewport": {"width": 1440, "height": 900},
        "is_mobile": False,
    },
    {
        "name": "Mac Safari",
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
        "viewport": {"width": 1280, "height": 800},
        "is_mobile": False,
    },
]

# Product selectors by site domain
SITE_SELECTORS = {
    "amazon": [
        'div[data-component-type="s-search-result"]',
        '.s-main-slot .s-result-item',
        '#search .s-result-item',
        '[data-asin]',
    ],
    "flipkart": [
        'div[data-id]', '._1AtVbE', '.CXW8mj', 'div._2kHMtA',
        '._13oc-S', '.col-12-12',
    ],
    "shopclues": [
        'div.column', 'div.products', 'ul.prd-grid-list', 'div.prd_box',
    ],
    "ebay": ['li.s-item', '.srp-results .s-item', '.s-item__wrapper'],
    "toscrape": ['article.product_pod', 'article', '.product_pod'],
    "default": [
        'article', 'div.product', 'div.card', '.product-item',
        'li.product', '.item', '[class*="product"]', '[class*="item"]',
    ],
}

# Only flag as blocked if these appear with very little content
BLOCK_SIGNALS = [
    "captcha",
    "security challenge",
    "robot check",
    "verify you are human",
    "are you a robot",
    "unusual traffic",
    "access denied",
    "blocked",
    "ddos-guard",
    "cloudflare",
]


class IntelligentScraper:
    """Singleton-safe universal scraper with anti-detection."""

    _pw = None
    _browser = None

    async def force_restart(self):
        """Force kill the current browser so a fresh one is generated."""
        try:
            if IntelligentScraper._browser:
                await IntelligentScraper._browser.close()
        except Exception:
            pass
        finally:
            IntelligentScraper._browser = None
            if IntelligentScraper._pw:
                try:
                    await IntelligentScraper._pw.stop()
                except Exception:
                    pass
            IntelligentScraper._pw = None

    async def _ensure_browser(self):
        """Start playwright and chromium if not already running."""
        try:
            if IntelligentScraper._browser:
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
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--disable-extensions",
                    "--disable-infobars",
                    "--window-size=1366,768",
                    "--lang=en-US,en;q=0.9",
                ],
            )
            logger.info("Browser started fresh.")

    def _get_selectors(self, url: str) -> list:
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

        try:
            parser = HTMLParser(html)
            # Remove noise elements
            for tag in ["script", "style", "nav", "footer", "header",
                        "aside", "noscript", "iframe", "svg"]:
                for el in parser.css(tag):
                    el.decompose()
            html = parser.html or html
        except Exception:
            pass

        return h.handle(html)

    async def _bypass_popups(self, page):
        """Try to dismiss cookie/consent popups."""
        buttons = [
            "Accept", "Accept All", "Agree", "Allow", "Allow All",
            "Continue", "OK", "Got it", "I Agree", "Consent", "Close",
            "ACCEPT", "AGREE",
        ]
        for btn_text in buttons:
            try:
                btn = page.get_by_role("button", name=re.compile(f"^{re.escape(btn_text)}$", re.I))
                if await btn.is_visible():
                    await btn.click(timeout=1500)
                    logger.info(f"Dismissed popup: {btn_text}")
                    await asyncio.sleep(0.5)
                    return
            except Exception:
                continue

    async def _smart_wait(self, page, url: str, timeout: int = 12000):
        """Wait for site-specific product content to appear."""
        selectors = self._get_selectors(url)
        combined = ", ".join(selectors)
        try:
            await page.wait_for_selector(combined, timeout=timeout)
            logger.info(f"Content ready on {url}")
        except Exception:
            logger.warning(f"Smart wait timed out on {url} — using raw page content")

    async def load(self, url: str) -> dict:
        """Load a URL with stealth and smart waiting."""
        await self._ensure_browser()

        profile = random.choice(PROFILES)
        logger.info(f"Profile: {profile['name']} → {url}")

        context = await IntelligentScraper._browser.new_context(
            user_agent=profile["ua"],
            viewport=profile["viewport"],
            is_mobile=profile["is_mobile"],
            has_touch=False,
            locale="en-US",
            timezone_id="America/New_York",
            # Extra headers that make us look more human
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
            }
        )
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)

        try:
            await asyncio.sleep(random.uniform(0.5, 1.5))
            await page.goto(url, timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(1.5, 3.0))

            # Dismiss cookie popups
            await self._bypass_popups(page)

            # Wait for JS-rendered content
            await self._smart_wait(page, url)

            # Realistic scroll
            try:
                for _ in range(random.randint(2, 4)):
                    await page.evaluate(f"window.scrollBy(0, {random.randint(400, 800)})")
                    await asyncio.sleep(random.uniform(0.8, 1.5))
                # Scroll back to top
                await page.evaluate("window.scrollTo(0, 0)")
                await asyncio.sleep(0.5)
            except Exception:
                pass

            html = await page.content()
            tree = HTMLParser(html)
            raw_text = tree.text()

            # Block detection — only flag if VERY short + has signal
            text_len = len(raw_text)
            raw_lower = raw_text.lower()
            is_blocked = (
                text_len < 2000 and
                any(sig in raw_lower for sig in BLOCK_SIGNALS)
            )

            if is_blocked:
                logger.warning(f"Bot-detection wall hit on {url} (len={text_len})")
                await context.close()
                return {"text": "", "html": html, "links": [], "url": page.url,
                        "success": False, "blocked": True}

            # Extract links
            links = []
            seen_hrefs = set()
            for a in tree.css("a"):
                href = a.attributes.get("href", "")
                text = a.text(strip=True)
                if href and text and href not in seen_hrefs:
                    full_href = urljoin(url, href)
                    if full_href.startswith("http"):
                        links.append({"text": text, "href": full_href})
                        seen_hrefs.add(href)

            # Clean text for LLM
            text = await self._clean_content(html)

            logger.info(f"Loaded {page.url} — {len(text)} chars, {len(links)} links")
            return {"text": text, "html": html, "links": links, "url": page.url,
                    "success": True, "blocked": False}

        except Exception as e:
            logger.error(f"Load failed for {url}: {e}")
            return {"text": "", "html": "", "links": [], "url": url,
                    "success": False, "blocked": False}
        finally:
            await context.close()

    async def close(self):
        """Gracefully shut down browser."""
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

            # Try target_url if provided
            if target_url and target_url.startswith("http"):
                logger.info(f"Direct nav URL: {target_url}")
                result = await self.load(target_url)
                if result["success"] and len(result["text"]) > 500:
                    return result

            # Build search URL from known patterns
            if query:
                parsed = urlparse(base_url)
                domain = parsed.netloc.lower()
                netloc = f"{parsed.scheme}://{parsed.netloc}"
                q = quote_plus(query)

                if "amazon" in domain:
                    candidates = [f"{netloc}/s?k={q}"]
                elif "flipkart" in domain:
                    candidates = [f"{netloc}/search?q={q}"]
                elif "shopclues" in domain:
                    candidates = [
                        f"https://m.shopclues.com/search?q={q}",
                        f"{netloc}/search?q={q}",
                    ]
                elif "ebay" in domain:
                    candidates = [f"{netloc}/sch/i.html?_nkw={q}"]
                else:
                    candidates = [
                        f"{netloc}/search?q={q}",
                        f"{netloc}/search?query={q}",
                        f"{netloc}/search?keyword={q}",
                        f"{netloc}/products?search={q}",
                    ]

                for candidate in candidates:
                    logger.info(f"Trying search URL: {candidate}")
                    r = await self.load(candidate)
                    # Quality check — reject garbage
                    if r["success"] and len(r["text"]) > 800:
                        garbage = ["mmMwWLliI", "0 items found", "no results found", "404"]
                        if not any(g in r["text"] for g in garbage):
                            return r
                        else:
                            logger.warning(f"Garbage result at {candidate}, skipping")

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
