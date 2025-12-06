"""
Emotion and intent detection for empathetic responses.
"""

from __future__ import annotations

from enum import Enum
from typing import Tuple

from src.utils.logger import get_logger


class UserEmotion(str, Enum):
    """Detected user emotions."""

    BORED = "bored"
    EXCITED = "excited"
    ROMANTIC = "romantic"
    STRESSED = "stressed"
    ADVENTUROUS = "adventurous"
    TIRED = "tired"
    CELEBRATORY = "celebratory"
    NEUTRAL = "neutral"


class EmotionDetector:
    """Detects user emotion from query."""

    EMOTION_KEYWORDS = {
        UserEmotion.BORED: [
            "aburrido",
            "aburrida",
            "nada que hacer",
            "sin planes",
            "qué hacer hoy",
            "estoy solo",
            "aburrimiento",
            "me aburro",
        ],
        UserEmotion.EXCITED: [
            "emocionado",
            "emocionada",
            "ansioso",
            "ansiosa",
            "¡",
            "genial",
            "quiero",
            "vamos a",
            "voy a",
            "¡vamos!",
        ],
        UserEmotion.ROMANTIC: [
            "romántico",
            "romántica",
            "pareja",
            "cita",
            "enamorado",
            "enamorada",
            "special",
            "noche especial",
            "ella",
            "él",
            "novio",
            "novia",
        ],
        UserEmotion.STRESSED: [
            "estresado",
            "estresada",
            "urgente",
            "rápido",
            "prisa",
            "no tengo tiempo",
            "ocupado",
            "ocupada",
            "corriendo",
        ],
        UserEmotion.ADVENTUROUS: [
            "aventura",
            "exploremos",
            "nuevo",
            "nunca",
            "diferentes",
            "diferente",
            "probemos",
            "algo loco",
            "experimental",
        ],
        UserEmotion.TIRED: [
            "cansado",
            "cansada",
            "fatigado",
            "fatigada",
            "tranquilo",
            "tranquila",
            "relajado",
            "relajada",
            "sin energía",
            "descansar",
            "tomar algo",
        ],
        UserEmotion.CELEBRATORY: [
            "cumpleaños",
            "celebrar",
            "fiesta",
            "festejemos",
            "festeja",
            "aniversario",
            "despedida",
            "boda",
            "promoción",
        ],
    }

    def __init__(self):
        self.logger = get_logger("emotion_detector")

    def detect(self, query: str) -> Tuple[UserEmotion, float]:
        """
        Detect emotion from query.

        Args:
            query: User query text

        Returns:
            Tuple of (emotion, confidence) where confidence is 0.0-1.0
        """
        query_lower = query.lower()

        # Count keyword matches per emotion
        emotion_scores = {}
        for emotion, keywords in self.EMOTION_KEYWORDS.items():
            matches = sum(1 for kw in keywords if kw in query_lower)
            if matches > 0:
                emotion_scores[emotion] = matches

        if not emotion_scores:
            self.logger.debug("no_emotion_detected", query=query[:50])
            return UserEmotion.NEUTRAL, 0.3

        # Return highest scoring emotion
        top_emotion = max(emotion_scores, key=emotion_scores.get)
        confidence = min(0.95, emotion_scores[top_emotion] * 0.4)

        self.logger.debug(
            "emotion_detected", emotion=top_emotion.value, confidence=confidence
        )
        return top_emotion, confidence

    def adapt_response_tone(self, emotion: UserEmotion) -> str:
        """Get response tone recommendation based on emotion."""
        tones = {
            UserEmotion.BORED: "Be enthusiastic, suggest variety and novelty",
            UserEmotion.EXCITED: "Match their energy, be expressive and bold",
            UserEmotion.ROMANTIC: "Be elegant, thoughtful, and suggest special places",
            UserEmotion.STRESSED: "Be concise, efficient, and direct - save time",
            UserEmotion.ADVENTUROUS: "Be exploratory, suggest unique and bold options",
            UserEmotion.TIRED: "Be calm, gentle, suggest relaxing places",
            UserEmotion.CELEBRATORY: "Be festive, energetic, suggest premium options",
            UserEmotion.NEUTRAL: "Be balanced, helpful, and professional",
        }
        return tones.get(emotion, "Be friendly and helpful")

