"""
Translation and i18n support for system messages and UI text.
Agent responses are handled by multi-language prompts in the LLM.
"""

import json
from pathlib import Path
from typing import Dict, Optional

from src.config.settings import Settings, get_settings
from src.utils.cache_manager import CacheManager
from src.utils.logger import get_logger


class Translator:
    """
    Handles translation of system messages and UI text.
    Note: Agent responses are handled by multi-language LLM prompts.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        cache: Optional[CacheManager] = None,
    ):
        """
        Initialize translator.

        Args:
            settings: Optional settings instance
            cache: Optional cache manager for caching translations
        """
        self.settings = settings or get_settings()
        self.cache = cache
        self.logger = get_logger("translator")
        self.locales: Dict[str, Dict[str, str]] = {}
        self._load_locales()

    def _load_locales(self) -> None:
        """Load locale JSON files from disk."""
        locale_dir = Path(__file__).parent / "locales"

        if not locale_dir.exists():
            self.logger.warning("locales_directory_not_found", path=str(locale_dir))
            return

        for lang in self.settings.supported_languages_list:
            locale_file = locale_dir / f"{lang}.json"

            if locale_file.exists():
                try:
                    with open(locale_file, "r", encoding="utf-8") as f:
                        self.locales[lang] = json.load(f)
                    self.logger.info("locale_loaded", language=lang, keys=len(self.locales[lang]))
                except Exception as exc:
                    self.logger.error("locale_load_error", language=lang, error=str(exc))
            else:
                self.logger.warning("locale_file_not_found", language=lang, path=str(locale_file))
                self.locales[lang] = {}

    def translate(
        self,
        key: str,
        language: str,
        fallback: Optional[str] = None,
        **kwargs,
    ) -> str:
        """
        Translate a message key to target language.

        Args:
            key: Translation key (e.g., "error.invalid_session")
            language: Target language code
            fallback: Optional fallback text if key not found
            **kwargs: Optional format variables

        Returns:
            Translated string

        Example:
            >>> translator.translate(
            ...     "welcome.message",
            ...     "es",
            ...     name="Juan"
            ... )
            "Bienvenido, Juan!"
        """
        # Normalize language
        language = language.lower()

        # Get locale dictionary
        locale = self.locales.get(language, {})

        # Get translation
        translation = locale.get(key)

        if not translation:
            # Try fallback to default language
            if language != self.settings.default_language:
                default_locale = self.locales.get(self.settings.default_language, {})
                translation = default_locale.get(key)

            # Use fallback or key itself
            if not translation:
                translation = fallback or key
                self.logger.debug(
                    "translation_missing",
                    key=key,
                    language=language,
                )

        # Format with variables if provided
        if kwargs:
            try:
                translation = translation.format(**kwargs)
            except KeyError as exc:
                self.logger.warning(
                    "translation_format_error",
                    key=key,
                    error=str(exc),
                )

        return translation

    def t(self, key: str, language: str, **kwargs) -> str:
        """Shorthand alias for translate()."""
        return self.translate(key, language, **kwargs)

    def get_error_message(
        self,
        error_code: str,
        language: str,
        **kwargs,
    ) -> str:
        """
        Get formatted error message.

        Args:
            error_code: Error code (e.g., "invalid_session", "location_required")
            language: Target language
            **kwargs: Optional format variables

        Returns:
            Formatted error message
        """
        key = f"error.{error_code}"
        return self.translate(key, language, **kwargs)

    def get_success_message(
        self,
        message_code: str,
        language: str,
        **kwargs,
    ) -> str:
        """Get formatted success message."""
        key = f"success.{message_code}"
        return self.translate(key, language, **kwargs)

    def get_validation_message(
        self,
        field: str,
        language: str,
        **kwargs,
    ) -> str:
        """Get formatted validation message."""
        key = f"validation.{field}"
        return self.translate(key, language, **kwargs)


# Global translator instance
_translator_instance: Optional[Translator] = None


def get_translator(
    settings: Optional[Settings] = None,
    cache: Optional[CacheManager] = None,
) -> Translator:
    """
    Get or create global translator instance.

    Args:
        settings: Optional settings instance
        cache: Optional cache manager

    Returns:
        Singleton Translator instance
    """
    global _translator_instance
    if _translator_instance is None:
        _translator_instance = Translator(settings, cache)
    return _translator_instance

