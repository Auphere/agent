"""
Response Validator - Ensures consistency between response text and actual data.

Key responsibilities:
- Validate that mentioned counts match actual data
- Inject actual counts into response templates
- Detect and fix count mismatches
- Log inconsistencies for debugging
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from src.utils.logger import get_logger

logger = get_logger("response_validator")


# ============================================================================
# Count Patterns for Detection
# ============================================================================

# Spanish patterns for detecting counts in text
ES_COUNT_PATTERNS = [
    r"(?:he encontrado|encontré|aquí tienes?|te muestro|te presento)\s+(\d+)",
    r"(\d+)\s+(?:restaurantes?|bares?|lugares?|opciones?|sitios?|cafés?|clubs?)",
    r"(?:estos?|estas?)\s+(\d+)\s+(?:restaurantes?|bares?|lugares?|opciones?)",
    r"(?:mejores?|top)\s+(\d+)",
]

# English patterns for detecting counts in text
EN_COUNT_PATTERNS = [
    r"(?:i found|here are|showing you|presenting)\s+(\d+)",
    r"(\d+)\s+(?:restaurants?|bars?|places?|options?|spots?|cafes?|clubs?)",
    r"(?:these?|this)\s+(\d+)\s+(?:restaurants?|bars?|places?|options?)",
    r"(?:best|top)\s+(\d+)",
]


def extract_mentioned_count(text: str, language: str = "es") -> Optional[int]:
    """
    Extract the count mentioned in response text.
    
    Args:
        text: Response text to analyze
        language: Language of the text ("es" or "en")
        
    Returns:
        Mentioned count or None if not found
    """
    text_lower = text.lower()
    
    patterns = ES_COUNT_PATTERNS if language.startswith("es") else EN_COUNT_PATTERNS
    
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            try:
                return int(match.group(1))
            except (ValueError, IndexError):
                continue
    
    return None


def validate_response_consistency(
    response_text: str,
    actual_places_count: int,
    language: str = "es",
) -> Tuple[bool, Optional[str]]:
    """
    Validate that response text is consistent with actual data.
    
    Args:
        response_text: The response text to validate
        actual_places_count: Actual number of places being returned
        language: Language of response
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    mentioned_count = extract_mentioned_count(response_text, language)
    
    if mentioned_count is None:
        # No count mentioned - this is acceptable
        return True, None
    
    if mentioned_count != actual_places_count:
        error_msg = (
            f"Count mismatch: Response mentions {mentioned_count} places "
            f"but actually returning {actual_places_count}"
        )
        logger.warning(
            "response-count-mismatch",
            mentioned=mentioned_count,
            actual=actual_places_count,
            language=language,
        )
        return False, error_msg
    
    return True, None


def fix_response_count(
    response_text: str,
    actual_count: int,
    language: str = "es",
) -> str:
    """
    Fix count mismatches in response text by replacing incorrect numbers.
    
    This is a best-effort fix - replaces detected count patterns with actual count.
    
    Args:
        response_text: Original response text
        actual_count: Actual number of places
        language: Language of response
        
    Returns:
        Fixed response text
    """
    mentioned_count = extract_mentioned_count(response_text, language)
    
    if mentioned_count is None or mentioned_count == actual_count:
        return response_text
    
    # Replace the incorrect count with the actual count
    patterns = ES_COUNT_PATTERNS if language.startswith("es") else EN_COUNT_PATTERNS
    
    fixed_text = response_text
    for pattern in patterns:
        # Create replacement pattern that preserves context
        def replace_count(match):
            full_match = match.group(0)
            return full_match.replace(str(mentioned_count), str(actual_count))
        
        fixed_text = re.sub(pattern, replace_count, fixed_text, flags=re.IGNORECASE)
    
    logger.info(
        "response-count-fixed",
        original=mentioned_count,
        fixed_to=actual_count,
    )
    
    return fixed_text


def inject_count_into_template(
    template: str,
    actual_count: int,
    placeholder: str = "{N}",
) -> str:
    """
    Inject actual count into a response template.
    
    Args:
        template: Response template with placeholder
        actual_count: Actual number to inject
        placeholder: Placeholder string to replace
        
    Returns:
        Template with count injected
    """
    return template.replace(placeholder, str(actual_count))


class ResponseValidator:
    """
    Validates and fixes response consistency issues.
    
    Usage:
        validator = ResponseValidator()
        
        # Validate
        is_valid, error = validator.validate(response_text, len(places), language)
        
        # Fix if needed
        if not is_valid:
            response_text = validator.fix(response_text, len(places), language)
    """
    
    def __init__(self):
        self.logger = get_logger("response_validator")
        self._mismatch_count = 0
    
    def validate(
        self,
        response_text: str,
        actual_places_count: int,
        language: str = "es",
    ) -> Tuple[bool, Optional[str]]:
        """Validate response consistency."""
        is_valid, error = validate_response_consistency(
            response_text, actual_places_count, language
        )
        
        if not is_valid:
            self._mismatch_count += 1
        
        return is_valid, error
    
    def fix(
        self,
        response_text: str,
        actual_count: int,
        language: str = "es",
    ) -> str:
        """Fix response count mismatches."""
        return fix_response_count(response_text, actual_count, language)
    
    def validate_and_fix(
        self,
        response_text: str,
        actual_places_count: int,
        language: str = "es",
    ) -> str:
        """
        Validate response and automatically fix if inconsistent.
        
        Args:
            response_text: Response text to validate
            actual_places_count: Actual number of places
            language: Response language
            
        Returns:
            Validated (and possibly fixed) response text
        """
        is_valid, error = self.validate(response_text, actual_places_count, language)
        
        if not is_valid:
            return self.fix(response_text, actual_places_count, language)
        
        return response_text
    
    @property
    def mismatch_count(self) -> int:
        """Number of mismatches detected since initialization."""
        return self._mismatch_count


# Singleton instance
_validator: Optional[ResponseValidator] = None


def get_response_validator() -> ResponseValidator:
    """Get singleton ResponseValidator instance."""
    global _validator
    if _validator is None:
        _validator = ResponseValidator()
    return _validator

