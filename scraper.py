"""
scraper.py — Enterprise Playwright Scraping Engine
Optimized hybrid approach: DOM-first logic, LLM as fallback.
"""

import asyncio
import random
import logging
from typing import Optional
from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from playwright_stealth import stealth_async

logger = logging.getLogger(__name__)

# ─── Realistic browser fingerprints ───────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
]


class PlaywrightScraper:
    """
    Core scraping engine. Handles:
      - Stealth browser launch
      - Human-like navigation (delays, scrolls)
      - Cookie/consent banner dismissal
      - Search-first flow for e-commerce sites
      - Structured HTML extraction per page
      - Delegation to PaginationHandler for multi-page traversal
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.max_pages: int = self.config.get("max_pages", 5)
        self.timeout: int = self.config.get("timeout_ms", 60_000)
        self.headless: bool = self.config.get("headless", True)
        self.proxy: Optional[dict] = self.config.get("proxy")  # {"server": "...", "username": ..., "password": ...}

    # ── Public entry point ────────────────────────────────────────────────────

    async def scrape(self, url: str, fields: list[str], filter_description: str = "", llm_client=None) -> list[dict]:
        """
        Scrape `url` for `fields`. Returns list of raw item dicts.
        Each dict is keyed by field; values are raw strings from the page.
        """
        import sys
        if sys.platform.startswith("win"):
            # Run in a separate thread with a forced ProactorEventLoop to bypass Uvicorn Windows bugs
            return await asyncio.to_thread(self._scrape_sync_wrapper, url, fields, filter_description, llm_client)
        else:
            return await self._do_scrape(url, fields, filter_description, llm_client)
 
    def _scrape_sync_wrapper(self, url: str, fields: list[str], filter_description: str = "", llm_client=None) -> list[dict]:
        """Thread wrapper to ensure ProactorEventLoop is used on Windows."""
        import sys
        if sys.platform.startswith("win"):
            loop = asyncio.ProactorEventLoop()
            asyncio.set_event_loop(loop)
        else:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        try:
            return loop.run_until_complete(self._do_scrape(url, fields, filter_description, llm_client))
        finally:
            loop.close()
 
    async def _do_scrape(self, url: str, fields: list[str], filter_description: str = "", llm_client=None) -> list[dict]:
        self.llm_client = llm_client
        async with async_playwright() as pw:
            browser = await self._launch_browser(pw)
            page = None
            try:
                context = await self._create_context(browser)
                page = await context.new_page()
                await stealth_async(page)
 
                # Step 1: Navigate
                logger.info(f"Navigating to {url}")
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)
                except Exception as e:
                    logger.error(f"Initial navigation failed: {e}")
                    if page:
                        html = await page.content()
                        with open("error_page.html", "w", encoding="utf-8") as f:
                            f.write(html)
                    raise
 
                content = await page.content()
                text_snippet = await page.evaluate("document.body.innerText")
                clean_snippet = text_snippet[:500].replace("\n", " ")
                logger.info(f"PAGE HTML LENGTH: {len(content)}")
                logger.info(f"PAGE TEXT SNIPPET: {clean_snippet}...")
                
                # Initial popup dismissal
                await self._dismiss_consent(page)
                await self._human_pause(1.0, 2.5)
 
                # Step 2: If search-needed (e.g. Amazon), trigger search for primary field
                # Only attempt if we have a search query (empty list = browse mode, no search)
                search_triggered = False
                if fields:
                    # Dismiss popups again right before searching
                    await self._dismiss_consent(page)
                    search_triggered = await self._try_search(page, fields[0])
                
                if search_triggered:
                    try:
                        # Wait for either a navigation or a small timeout to let AJAX results load
                        logger.info("Waiting for search results to load...")
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except:
                        pass
                    
                    # Heuristic: Wait for product elements to appear
                    product_selectors = [".product", ".item", ".search_res", ".row", "[class*='product' i]", ".grid-view"]
                    for sel in product_selectors:
                        try:
                            await page.wait_for_selector(sel, state="visible", timeout=3000)
                            logger.info(f"Confirmed results loaded via selector: {sel}")
                            break
                        except: continue

                    # Log snippet of the results page
                    results_html = await page.content()
                    results_text = await page.evaluate("document.body.innerText")
                    clean_results = results_text[:1000].replace("\n", " ")
                    logger.info(f"RESULTS PAGE HTML LENGTH: {len(results_html)}")
                    logger.info(f"RESULTS PAGE TEXT SNIPPET: {clean_results}...")
                    
                    if len(results_html) < 5000:
                        logger.warning("Results page looks suspiciously small. Search might have failed or returned no results.")
                    
                    await self._dismiss_consent(page)
 
                # Step 2.5: Apply filters if provided
                if filter_description:
                    logger.info(f"Attempting to apply filter: {filter_description}")
                    filter_applied = await self._try_apply_filter(page, filter_description)
                    if filter_applied:
                        try:
                            await page.wait_for_load_state("networkidle", timeout=5000)
                            await self._dismiss_consent(page)
                        except:
                            pass
 
                # Step 2.7: Deep Crawl (Follow Detail Links if needed)
                # If prompt mentions "description", "detail", "specs", etc.
                html_pages = []
                deep_keywords = ["description", "detail", "specs", "specification", "about", "review"]
                if any(k in " ".join(fields).lower() for k in deep_keywords):
                    logger.info("Detected detail-oriented prompt. Attempting deep crawl...")
                    deep_pages = await self._try_deep_crawl(page, fields)
                    if deep_pages:
                        html_pages.extend(deep_pages)

                # Step 3: Paginate + collect HTML chunks
                await self._dismiss_consent(page)
                from pagination import PaginationHandler
                paginator = PaginationHandler(page, max_pages=self.max_pages)
                remaining_pages = await paginator.collect_all_pages()
                html_pages.extend(remaining_pages)
                
                return html_pages
 
            finally:
                if browser:
                    await browser.close()
 
    # ── Helpers ───────────────────────────────────────────────────────────────
 
    async def _try_deep_crawl(self, page: Page, fields: list[str]) -> list[dict]:
        """
        Heuristic-based deep crawling:
        1. Find all links on the page (text + title attribute).
        2. Identify links that match words in the prompt.
        3. Visit them and return their HTML.
        """
        try:
            # 1. Get all links with their text and title
            links = await page.evaluate("""
                () => {
                    return Array.from(document.querySelectorAll('a')).map(a => ({
                        text: a.innerText.trim(),
                        title: a.getAttribute('title') || '',
                        href: a.href
                    })).filter(l => (l.text.length > 2 || l.title.length > 2) && l.href.startsWith('http'))
                }
            """)
            
            # 2. Heuristic match: find links that appear in the prompt
            prompt_text = " ".join(fields).lower()
            to_visit = []
            
            # Avoid visiting too many
            max_deep = 5
            
            for link in links:
                if len(to_visit) >= max_deep: break
                
                # Check visible text and title attribute
                # Clean the text (remove dots, etc)
                link_text = link['text'].lower().replace("...", "").strip()
                link_title = link['title'].lower().strip()
                
                match = False
                if link_text and len(link_text) > 4 and link_text in prompt_text:
                    match = True
                elif link_title and len(link_title) > 4 and link_title in prompt_text:
                    match = True
                
                if match:
                    if link['href'] not in to_visit:
                        logger.info(f"Matched detail link: '{link_text}' / '{link_title}' -> {link['href']}")
                        to_visit.append(link['href'])
            
            if not to_visit:
                logger.warning("No detail links matched the prompt criteria.")
                return []
            
            async def visit_link(i, url):
                logger.info(f"Deep crawling detail page {i+1}: {url}")
                new_page = await page.context.new_page()
                try:
                    await stealth_async(new_page)
                    # Use a shorter timeout and wait only for commit
                    await new_page.goto(url, wait_until="commit", timeout=15000)
                    await self._dismiss_consent(new_page)
                    
                    # Quick scroll
                    await new_page.evaluate("window.scrollTo(0, 500)")
                    await asyncio.sleep(0.5)
                    
                    html = await new_page.content()
                    from html_cleaner import HTMLCleaner
                    cleaner = HTMLCleaner()
                    cleaned = cleaner.clean(html)
                    
                    return {
                        "page_num": f"detail_{i+1}",
                        "url": url,
                        "html": cleaned
                    }
                except Exception as e:
                    logger.warning(f"Failed to crawl detail page {url}: {e}")
                    return None
                finally:
                    await new_page.close()

            # Limit to top 3 most relevant links to save time
            tasks = [visit_link(i, url) for i, url in enumerate(to_visit[:3])]
            results = await asyncio.gather(*tasks)
            deep_results = [r for r in results if r]
            
            return deep_results
        except Exception as e:
            logger.error(f"Deep crawl failed: {e}")
            return []




    async def _launch_browser(self, pw) -> Browser:
        launch_opts = {
            "headless": self.headless,
            "args": [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-extensions",
            ],
        }
        if self.proxy:
            launch_opts["proxy"] = self.proxy
        return await pw.chromium.launch(**launch_opts)

    async def _create_context(self, browser: Browser) -> BrowserContext:
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport=random.choice(VIEWPORTS),
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            ignore_https_errors=True,
        )
        # Block images to save bandwidth and speed up load
        await context.route("**/*.{png,jpg,jpeg,gif,webp,svg}", lambda route: route.abort())
        return context

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _dismiss_consent(self, page: Page):
        """Click common cookie/consent/popup close buttons."""
        selectors = [
            "button[id*='accept']", "button[class*='accept']",
            "button[aria-label*='Accept']", "#onetrust-accept-btn-handler",
            ".cc-accept", "[data-testid='accept-button']",
            "button.p-close", ".p-close", "button:has-text('Close')", # Shopclues/Popups
            ".modal-close", ".close-modal", "[aria-label='Close']",
        ]
        for sel in selectors:
            try:
                # Use a very short timeout for each check to avoid slowing down too much
                btn = await page.wait_for_selector(sel, state="visible", timeout=1000)
                if btn:
                    await btn.click(force=True)
                    logger.info(f"Dismissed popup/consent via {sel}")
                    await self._human_pause(0.5, 1.0)
            except Exception:
                pass

    async def _try_search(self, page: Page, query: str) -> bool:
        """
        Try to find a search box and search for `query`.
        Returns True if search was performed.
        """
        search_selectors = [
            "input#autocomplete", # Shopclues
            "input[type='search']",
            "input[name='q']",
            "input[name='search']",
            "input[placeholder*='search' i]",
            "input[placeholder*='find' i]",
            "input[placeholder*='products' i]",
            "#searchInput", "#search", ".search-input",
            "input[aria-label*='search' i]",
            "#twotabsearchtextbox", # Amazon specific
            "[data-testid='search-input']",
        ]
        for sel in search_selectors:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    logger.info(f"Found search bar via {sel}")
                    await el.scroll_into_view_if_needed()
                    await el.click(force=True)
                    await self._human_pause(0.5, 1.0)
                    
                    # Try to clear and type
                    await el.fill("")
                    await el.type(query, delay=random.randint(40, 120))
                    await self._human_pause(0.5, 1.0)
                    await el.press("Enter")
                    
                    # Fallback: Find and click search button if still on same page
                    await self._human_pause(0.5, 1.0)
                    button_selectors = [
                        "button[type='submit']", "button.search-button", ".srch_btn", "#searchBtn",
                        "i.search-icon", "span.search-icon", "button:has-text('Search')",
                    ]
                    for bsel in button_selectors:
                        try:
                            btn = await page.query_selector(bsel)
                            if btn and await btn.is_visible():
                                await btn.click()
                                logger.info(f"Clicked search button via {bsel}")
                                break
                        except:
                            pass
                    
                    logger.info(f"Search submitted for '{query}'")
                    return True
            except Exception as e:
                logger.debug(f"Search selector {sel} failed: {e}")
                pass
        return False

    async def _try_apply_filter(self, page: Page, description: str) -> bool:
        """
        Heuristic-based filter application for e-commerce sites.
        Focuses on price filters as they are most common.
        """
        # 1. Parse description for numbers (potential price limit)
        prices = [int(s) for s in description.split() if s.isdigit()]
        if not prices:
            logger.warning(f"No numeric price found in filter description: {description}")
            return False

        target_price = prices[0]
        
        # 2. Try common price filter inputs
        price_selectors = [
            "input[name='low-price']", "input[name='high-price']",  # Amazon
            "input[id*='low' i]", "input[id*='high' i]",
            "input[id*='min' i]", "input[id*='max' i]",
            "input[placeholder*='min' i]", "input[placeholder*='max' i]",
            "input[aria-label*='min' i]", "input[aria-label*='max' i]",
        ]
        
        # We'll try to set the 'high' price if "under" or "less than" is in description
        is_under = any(w in description.lower() for w in ["under", "less", "max", "up to"])
        
        try:
            if is_under:
                # Find the 'max' or 'high' price input
                max_selectors = [s for s in price_selectors if any(k in s.lower() for k in ["high", "max"])]
                for sel in max_selectors:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        await el.fill(str(target_price))
                        await el.press("Enter")
                        logger.info(f"Applied price filter: under {target_price} via {sel}")
                        return True
            else:
                # Find the 'min' or 'low' price input
                min_selectors = [s for s in price_selectors if any(k in s.lower() for k in ["low", "min"])]
                for sel in min_selectors:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        await el.fill(str(target_price))
                        await el.press("Enter")
                        logger.info(f"Applied price filter: above {target_price} via {sel}")
                        return True
        except Exception as e:
            logger.error(f"Failed to apply price filter: {e}")

        # 3. If heuristics fail, we could use LLM here to find the filter buttons
        # For now, we'll return False if heuristics fail.
        return False

    async def _human_pause(self, min_s: float, max_s: float):
        await asyncio.sleep(random.uniform(min_s, max_s))

    async def _auto_scroll(self, page: Page):
        """Scroll gradually to trigger lazy-loaded content."""
        await page.evaluate("""
            async () => {
                await new Promise(resolve => {
                    let totalHeight = 0;
                    const distance = 300;
                    const timer = setInterval(() => {
                        window.scrollBy(0, distance);
                        totalHeight += distance;
                        if (totalHeight >= document.body.scrollHeight - window.innerHeight) {
                            clearInterval(timer);
                            resolve();
                        }
                    }, 150);
                });
            }
        """)
        await self._human_pause(0.5, 1.0)
