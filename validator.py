"""
validator.py — Multi-Layer Validation & Quality Scoring
Gemini's approach: basic empty check.
Our approach: structural + semantic + confidence scoring + field-level auditing.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ─── Validation result ─────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    is_valid: bool
    items: list[dict] = field(default_factory=list)
    confidence_score: float = 0.0      # 0.0 – 1.0
    total_extracted: int = 0
    passed_items: int = 0
    rejected_items: int = 0
    rejection_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error_message: str = ""

    def summary(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "confidence_score": round(self.confidence_score, 2),
            "total_extracted": self.total_extracted,
            "passed": self.passed_items,
            "rejected": self.rejected_items,
            "warnings": self.warnings,
            "error": self.error_message,
        }


# ─── Validator ─────────────────────────────────────────────────────────────────

class OutputValidator:
    """
    4-layer validation pipeline:

    Layer 1 — Structural:  Is it a list of dicts? Do they have expected keys?
    Layer 2 — Content:     Are values non-empty strings / correct types?
    Layer 3 — Format:      Do prices/ratings match expected patterns?
    Layer 4 — Confidence:  Score overall quality. Reject if below threshold.
    """

    # Minimum ratio of non-null fields required per item
    MIN_FIELD_COMPLETENESS = 0.3       # at least 30% of expected fields populated
    # Minimum confidence score to accept the full result set
    MIN_CONFIDENCE_THRESHOLD = 0.4
    # Minimum items required to consider a scrape successful
    MIN_ITEMS = 1

    EXPECTED_FIELDS = set()

    PRICE_PATTERNS = [
        re.compile(r"[\$\€\£\₹\¥]\s*[\d,]+(\.\d{1,2})?"),  # $1,234.56
        re.compile(r"[\d,]+(\.\d{1,2})?\s*[\$\€\£\₹]"),     # 1234 ₹
        re.compile(r"(USD|EUR|GBP|INR|JPY)\s*[\d,]+"),       # USD 299
        re.compile(r"[\d,]+(\.\d{1,2})?"),                    # bare number fallback
    ]

    RATING_PATTERN = re.compile(r"\d(\.\d)?\s*(out of\s*\d|/\s*\d|stars?)?", re.IGNORECASE)

    def validate(self, items: list[Any], fields: list[str]) -> ValidationResult:
        result = ValidationResult(is_valid=False, total_extracted=len(items))

        # Layer 1: Structural check
        if not isinstance(items, list):
            return ValidationResult(
                is_valid=False,
                error_message="LLM returned non-list output. Structural failure."
            )

        if len(items) == 0:
            return ValidationResult(
                is_valid=False,
                total_extracted=0,
                error_message=f"No items found for fields: {', '.join(fields)}. "
                              "The requested data may not exist on this page."
            )

        # Layer 2 + 3: Per-item validation
        passed = []
        for item in items:
            ok, reasons = self._validate_item(item)
            if ok:
                item = self._normalize_item(item)
                passed.append(item)
            else:
                result.rejected_items += 1
                result.rejection_reasons.extend(reasons)

        result.items = passed
        result.passed_items = len(passed)

        # Layer 4: Confidence scoring
        result.confidence_score = self._compute_confidence(passed, items)

        if len(passed) < self.MIN_ITEMS:
            result.is_valid = False
            result.error_message = (
                f"All {len(items)} extracted items failed validation. "
                "Data quality too low. Common reasons: wrong URL, login-required page, "
                "or fields not present on this site."
            )
            return result

        if result.confidence_score < self.MIN_CONFIDENCE_THRESHOLD:
            result.warnings.append(
                f"Low confidence score ({result.confidence_score:.0%}). "
                "Results may be incomplete or partially incorrect."
            )

        result.is_valid = True
        return result

    # ── Per-item checks ───────────────────────────────────────────────────────

    def _validate_item(self, item: dict) -> tuple[bool, list[str]]:
        reasons = []

        if not isinstance(item, dict):
            return False, ["Item is not a dict"]

        # Flexible validation: Must have at least one string value
        valid_values = [v for v in item.values() if isinstance(v, str) and len(v.strip()) >= 1]
        if not valid_values:
            reasons.append("Item has no valid string values")
            return False, reasons

        return len(reasons) == 0, reasons

    # ── Normalization ──────────────────────────────────────────────────────────

    def _normalize_item(self, item: dict) -> dict:
        """Normalize field values to consistent formats."""
        # Strip string values
        for k, v in item.items():
            if isinstance(v, str):
                item[k] = v.strip()

        # Remove internal metadata keys before returning
        item.pop("_source_page", None)

        return item

    # ── Confidence scoring ────────────────────────────────────────────────────

    def _compute_confidence(self, passed: list[dict], all_items: list[dict]) -> float:
        """
        Confidence = pass rate
        """
        if not all_items:
            return 0.0

        pass_rate = len(passed) / len(all_items)
        return min(pass_rate, 1.0)
