"""
Language Handler - Manages language detection and standardization.

Implements English-first processing:
- All internal reasoning happens in English
- Language is detected at entry point
- Search queries are localized to user's language (if supported)
- Responses are in user's language (Spanish/English only for MVP)

MVP Supported Languages:
- Spanish (es) - Full support
- English (en) - Full support
- Other languages - Detected, but response in English with friendly message
"""

from __future__ import annotations

import re
from typing import Optional, Tuple
from enum import Enum

from src.utils.logger import get_logger

logger = get_logger("language_handler")


class SupportedLanguage(str, Enum):
    """Supported languages for MVP."""
    SPANISH = "es"
    ENGLISH = "en"


# MVP scope - only these languages get native responses
SUPPORTED_LANGUAGES = {SupportedLanguage.SPANISH, SupportedLanguage.ENGLISH}

# Default fallback language
DEFAULT_LANGUAGE = SupportedLanguage.ENGLISH


# ============================================================================
# Language Detection Patterns
# ============================================================================

# Common Spanish indicators (words, patterns)
SPANISH_INDICATORS = [
    # Common words
    r"\b(el|la|los|las|un|una|unos|unas)\b",
    r"\b(de|del|al|en|con|para|por|sin)\b",
    r"\b(que|qué|cómo|dónde|cuándo|cuánto|cuál)\b",
    r"\b(es|está|son|están|ser|estar)\b",
    r"\b(quiero|necesito|busco|dame|muéstrame)\b",
    r"\b(hola|gracias|buenos|buenas)\b",
    r"\b(restaurante|bar|lugar|sitio|opción|opciones)\b",
    r"\b(romántico|tranquilo|animado|divertido)\b",
    # Accented characters common in Spanish
    r"[áéíóúüñ]",
    # Question marks at start (Spanish style)
    r"^¿",
    # Exclamation marks at start (Spanish style)
    r"^¡",
]

# Common English indicators
ENGLISH_INDICATORS = [
    # Common words
    r"\b(the|a|an|this|that|these|those)\b",
    r"\b(is|are|was|were|be|been|being)\b",
    r"\b(i|you|he|she|it|we|they)\b",
    r"\b(want|need|looking|show|find|give)\b",
    r"\b(hello|hi|thanks|please)\b",
    r"\b(restaurant|bar|place|spot|option)\b",
    r"\b(romantic|quiet|lively|fun)\b",
    r"\b(what|where|when|how|which|who)\b",
]

# French indicators (for detection - responds in English)
FRENCH_INDICATORS = [
    r"\b(le|la|les|un|une|des)\b",
    r"\b(est|sont|être|avoir)\b",
    r"\b(je|tu|il|elle|nous|vous|ils|elles)\b",
    r"\b(bonjour|merci|s'il vous plaît)\b",
    r"[àâäéèêëïîôùûüœç]",
]


def _count_pattern_matches(text: str, patterns: list[str]) -> int:
    """Count how many patterns match in the text."""
    text_lower = text.lower()
    count = 0
    for pattern in patterns:
        if re.search(pattern, text_lower, re.IGNORECASE):
            count += 1
    return count


def detect_language(text: str) -> str:
    """
    Detect the language of input text.
    
    Uses pattern matching to identify Spanish, English, or other languages.
    
    Args:
        text: Input text to analyze
        
    Returns:
        Language code ("es", "en", or detected language code)
    """
    if not text or not text.strip():
        return DEFAULT_LANGUAGE.value
    
    text = text.strip()
    
    # Count matches for each language
    spanish_score = _count_pattern_matches(text, SPANISH_INDICATORS)
    english_score = _count_pattern_matches(text, ENGLISH_INDICATORS)
    french_score = _count_pattern_matches(text, FRENCH_INDICATORS)
    
    # Log detection scores for debugging
    logger.debug(
        "language-detection-scores",
        text_preview=text[:50],
        spanish=spanish_score,
        english=english_score,
        french=french_score,
    )
    
    # Determine language based on scores
    if spanish_score > english_score and spanish_score > french_score:
        return SupportedLanguage.SPANISH.value
    elif french_score > english_score and french_score > spanish_score:
        # French detected but not supported - will respond in English
        return "fr"
    else:
        # Default to English
        return SupportedLanguage.ENGLISH.value


def is_supported_language(language: str) -> bool:
    """Check if language is supported for native responses."""
    return language in {lang.value for lang in SUPPORTED_LANGUAGES}


def get_response_language(detected_language: str) -> str:
    """
    Get the language to use for responses.
    
    For MVP:
    - Spanish input -> Spanish response
    - English input -> English response
    - Other languages -> English response
    
    Args:
        detected_language: Detected input language
        
    Returns:
        Language code for response ("es" or "en")
    """
    if detected_language == SupportedLanguage.SPANISH.value:
        return SupportedLanguage.SPANISH.value
    return SupportedLanguage.ENGLISH.value


def get_search_language(detected_language: str) -> str:
    """
    Get the language to use for search queries.
    
    Search queries should be in the user's language when supported
    to get localized results.
    
    Args:
        detected_language: Detected input language
        
    Returns:
        Language code for searches
    """
    if is_supported_language(detected_language):
        return detected_language
    return SupportedLanguage.ENGLISH.value


def get_unsupported_language_message(detected_language: str) -> Optional[str]:
    """
    Get a friendly message for unsupported languages.
    
    Args:
        detected_language: Detected input language
        
    Returns:
        Message if language unsupported, None otherwise
    """
    if is_supported_language(detected_language):
        return None
    
    # Friendly messages for common unsupported languages
    messages = {
        "fr": "I noticed you're writing in French. Currently, I only support Spanish and English. I'll respond in English - hope that's okay! 🙂",
        "de": "Ich habe bemerkt, dass Sie auf Deutsch schreiben. I currently only support Spanish and English, so I'll respond in English.",
        "it": "Ho notato che scrivi in italiano. At the moment I only support Spanish and English, so I'll respond in English.",
        "pt": "Notei que você está escrevendo em português. Currently I only support Spanish and English, so I'll respond in English.",
    }
    
    return messages.get(
        detected_language,
        "I currently only support Spanish and English. I'll respond in English."
    )


class LanguageHandler:
    """
    Manages language detection and standardization for the agent.
    
    Key principles:
    1. Internal processing is ALWAYS in English
    2. User language is detected at entry
    3. Responses are in user's language (if supported)
    4. Searches use localized queries for supported languages
    
    Usage:
        handler = LanguageHandler()
        
        # Detect user language
        detected = handler.detect(user_message)
        
        # Get response language
        response_lang = handler.get_response_language(detected)
        
        # Check if we need to show unsupported language message
        unsupported_msg = handler.get_unsupported_message(detected)
    """
    
    SUPPORTED_LANGUAGES = ["es", "en"]
    INTERNAL_LANGUAGE = "en"  # Always process internally in English
    
    def __init__(self):
        self.logger = get_logger("language_handler")
        self._detection_cache: dict[str, str] = {}
    
    def detect(self, text: str) -> str:
        """
        Detect the language of input text.
        
        Args:
            text: User input text
            
        Returns:
            Detected language code
        """
        # Check cache for repeated texts
        cache_key = text[:100]  # Use first 100 chars as key
        if cache_key in self._detection_cache:
            return self._detection_cache[cache_key]
        
        detected = detect_language(text)
        
        # Cache result
        self._detection_cache[cache_key] = detected
        
        self.logger.info(
            "language-detected",
            text_preview=text[:30],
            detected=detected,
            is_supported=self.is_supported(detected),
        )
        
        return detected
    
    def is_supported(self, language: str) -> bool:
        """Check if language is supported for native responses."""
        return language in self.SUPPORTED_LANGUAGES
    
    def should_respond_in_spanish(self, detected_lang: str) -> bool:
        """Check if response should be in Spanish."""
        return detected_lang == SupportedLanguage.SPANISH.value
    
    def get_response_language(self, detected_lang: str) -> str:
        """Get the language code to use for responses."""
        return get_response_language(detected_lang)
    
    def get_search_language(self, detected_lang: str) -> str:
        """Get the language code to use for search queries."""
        return get_search_language(detected_lang)
    
    def get_unsupported_message(self, detected_lang: str) -> Optional[str]:
        """Get message for unsupported languages (or None if supported)."""
        return get_unsupported_language_message(detected_lang)
    
    def get_internal_language(self) -> str:
        """Get language for internal processing (always English)."""
        return self.INTERNAL_LANGUAGE
    
    def process_input(self, text: str) -> Tuple[str, str, str, Optional[str]]:
        """
        Process input and return all language-related decisions.
        
        Args:
            text: User input text
            
        Returns:
            Tuple of:
            - detected_language: What language the user wrote in
            - response_language: What language to respond in
            - search_language: What language for search queries
            - unsupported_message: Message if language not supported (or None)
        """
        detected = self.detect(text)
        response_lang = self.get_response_language(detected)
        search_lang = self.get_search_language(detected)
        unsupported_msg = self.get_unsupported_message(detected)
        
        return detected, response_lang, search_lang, unsupported_msg


# Singleton instance
_handler: Optional[LanguageHandler] = None


def get_language_handler() -> LanguageHandler:
    """Get singleton LanguageHandler instance."""
    global _handler
    if _handler is None:
        _handler = LanguageHandler()
    return _handler

