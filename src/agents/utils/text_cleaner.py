"""Utility to clean agent response text by removing URLs and structured data."""

import re
from typing import Optional


def clean_response_text(text: str) -> str:
    """
    Clean agent response text by removing:
    - Google Maps photo URLs (very long URLs)
    - Other URLs
    - Full addresses (keep only place names)
    
    Args:
        text: Raw response text from agent
        
    Returns:
        Cleaned text without URLs and excessive structured data
    """
    if not text:
        return text
    
    cleaned = text
    
    # Remove Google Maps photo URLs (these are very long and break formatting)
    # Pattern: https://maps.googleapis.com/maps/api/place/photo?maxwidth=...&photo_reference=...
    google_photo_pattern = r'https://maps\.googleapis\.com/maps/api/place/photo[^\s\)]+'
    cleaned = re.sub(google_photo_pattern, '', cleaned)
    
    # Remove other common URLs (but keep place names)
    url_pattern = r'https?://[^\s\)]+'
    cleaned = re.sub(url_pattern, '', cleaned)
    
    # Remove excessive whitespace and clean up
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = re.sub(r'\s*\.\s*\.\s*', '. ', cleaned)  # Clean up multiple dots
    cleaned = cleaned.strip()
    
    return cleaned


def remove_urls_from_text(text: Optional[str]) -> Optional[str]:
    """
    Simple wrapper to remove URLs from text.
    Returns None if input is None, otherwise returns cleaned text.
    """
    if text is None:
        return None
    return clean_response_text(text)

