"""
html_cleaner.py — Intelligent HTML Cleaner
Removes noise, preserves semantically rich content. Critical for reducing LLM token cost.
"""

import re
from bs4 import BeautifulSoup


class HTMLCleaner:
    """
    Two-mode cleaner:
      - full_text: Returns clean plaintext (for LLM extraction)
      - structured: Returns simplified HTML preserving semantic tags (for selector-based extraction)
    """

    # Tags to completely remove (content + tag)
    STRIP_TAGS = {
        "script", "style", "noscript", "iframe", "svg", "canvas",
        "video", "audio", "map", "head", "meta", "link",
        "nav", "footer", "header",  # remove nav chrome; keep main content
    }

    # Attributes to keep (all others stripped to reduce noise)
    KEEP_ATTRS = {"href", "src", "alt", "aria-label", "data-price", "data-asin"}

    def clean(self, html: str, mode: str = "full_text") -> str:
        """
        Clean HTML.
        mode='full_text'  → plaintext for LLM
        mode='structured' → minimal HTML for selector use
        """
        soup = BeautifulSoup(html, "lxml")

        # Remove noisy tags
        for tag in self.STRIP_TAGS:
            for el in soup.find_all(tag):
                el.decompose()

        # Remove hidden elements
        for el in soup.find_all(style=re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden")):
            el.decompose()

        if mode == "full_text":
            return self._to_text(soup)
        else:
            return self._to_minimal_html(soup)

    def _to_text(self, soup: BeautifulSoup) -> str:
        # Preserve image alt text
        for img in soup.find_all("img", alt=True):
            alt_text = img.get('alt', '').strip()
            if alt_text:
                img.insert_before(f" [Image: {alt_text}] ")
            
        # Preserve common star rating classes
        for el in soup.find_all(class_=re.compile(r"star-rating", re.IGNORECASE)):
            classes = el.get("class", [])
            rating = [c for c in classes if c.lower() != "star-rating"]
            if rating:
                el.insert(0, f" [Rating: {rating[0]} Star] ")

        text = soup.get_text(separator="\n", strip=True)
        # Collapse excessive whitespace/newlines
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" {2,}", " ", text)
        return text.strip()

    def _to_minimal_html(self, soup: BeautifulSoup) -> str:
        """Strip all attributes except allowed ones, return clean HTML."""
        for tag in soup.find_all(True):
            attrs_to_keep = {k: v for k, v in tag.attrs.items() if k in self.KEEP_ATTRS}
            tag.attrs = attrs_to_keep
        return str(soup)

    def chunk(self, text: str, max_chars: int = 12_000) -> list[str]:
        """
        Split cleaned text into chunks for LLM processing.
        Tries to split on double-newlines (paragraph boundaries).
        """
        if len(text) <= max_chars:
            return [text]

        chunks = []
        while text:
            if len(text) <= max_chars:
                chunks.append(text)
                break
            # Find last double-newline before limit
            split_at = text.rfind("\n\n", 0, max_chars)
            if split_at == -1:
                split_at = max_chars
            chunks.append(text[:split_at].strip())
            text = text[split_at:].strip()

        return chunks
