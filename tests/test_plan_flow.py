"""
Test plan creation flow and emotion detection.
"""

import pytest

from src.agents.plan_memory import PlanContext, PlanMemoryManager
from src.classifiers.emotion_detector import EmotionDetector, UserEmotion


class TestEmotionDetection:
    """Test emotion detection."""

    def setup_method(self):
        self.detector = EmotionDetector()

    def test_detect_bored(self):
        query = "Estoy aburrido, no tengo nada que hacer"
        emotion, confidence = self.detector.detect(query)
        assert emotion == UserEmotion.BORED
        assert confidence > 0.3

    def test_detect_romantic(self):
        query = "Busco un lugar romántico para una cita especial"
        emotion, confidence = self.detector.detect(query)
        assert emotion == UserEmotion.ROMANTIC
        assert confidence > 0.3

    def test_detect_stressed(self):
        query = "Tengo prisa, necesito algo rápido"
        emotion, confidence = self.detector.detect(query)
        assert emotion == UserEmotion.STRESSED
        assert confidence > 0.3

    def test_detect_excited(self):
        query = "¡Emocionado de explorar lugares nuevos!"
        emotion, confidence = self.detector.detect(query)
        assert emotion == UserEmotion.EXCITED
        assert confidence > 0.3

    def test_neutral_no_emotion(self):
        query = "Busco un bar en Zaragoza"
        emotion, confidence = self.detector.detect(query)
        assert emotion == UserEmotion.NEUTRAL
        assert confidence <= 0.3

    def test_tone_adaptation(self):
        emotion = UserEmotion.BORED
        tone = self.detector.adapt_response_tone(emotion)
        assert "enthusiastic" in tone.lower() or "variety" in tone.lower()

    def test_detect_adventurous(self):
        query = "Quiero explorar algo diferente y nuevo"
        emotion, confidence = self.detector.detect(query)
        assert emotion == UserEmotion.ADVENTUROUS
        assert confidence > 0.3

    def test_detect_tired(self):
        query = "Estoy cansado, busco algo tranquilo"
        emotion, confidence = self.detector.detect(query)
        assert emotion == UserEmotion.TIRED
        assert confidence > 0.3

    def test_detect_celebratory(self):
        query = "Es mi cumpleaños y quiero celebrar"
        emotion, confidence = self.detector.detect(query)
        assert emotion == UserEmotion.CELEBRATORY
        assert confidence > 0.3


class TestPlanMemory:
    """Test plan memory management."""

    def setup_method(self):
        self.memory = PlanMemoryManager()

    def test_update_context(self):
        self.memory.update_plan_context(
            duration="2 hours", num_people=4, cities=["Zaragoza"]
        )
        assert self.memory.plan_context.duration == "2 hours"
        assert self.memory.plan_context.num_people == 4
        assert "Zaragoza" in self.memory.plan_context.cities

    def test_missing_fields(self):
        missing = self.memory.get_missing_for_plan()
        assert "duration" in missing
        assert "vibe" in missing
        assert len(missing) == 5  # All 5 required fields

    def test_plan_ready(self):
        self.memory.update_plan_context(
            duration="2 hours",
            num_people=2,
            cities=["Zaragoza"],
            place_types=["bars"],
            vibe="chill",
        )
        ready, missing = self.memory.plan_context.is_plan_ready()
        assert ready is True
        assert len(missing) == 0

    def test_plan_not_ready(self):
        self.memory.update_plan_context(
            duration="2 hours",
            num_people=2
            # Missing cities, place_types, vibe
        )
        ready, missing = self.memory.plan_context.is_plan_ready()
        assert ready is False
        assert len(missing) > 0

    def test_conversation_history(self):
        self.memory.add_turn("Quiero un plan", "¿Cuánto tiempo tienes?")
        assert len(self.memory.conversation_history) == 1
        assert self.memory.conversation_history[0]["user"] == "Quiero un plan"

    def test_track_questions_asked(self):
        self.memory.mark_question_asked("¿Cuánto tiempo tienes?")
        assert self.memory.has_asked_about("tiempo")
        assert not self.memory.has_asked_about("presupuesto")

    def test_context_summary(self):
        self.memory.update_plan_context(
            duration="evening", num_people=3, cities=["Zaragoza"], vibe="party"
        )
        summary = self.memory.get_context_summary()
        assert "evening" in summary
        assert "3" in summary
        assert "Zaragoza" in summary

    def test_reset(self):
        self.memory.update_plan_context(duration="2 hours", num_people=4)
        self.memory.add_turn("test", "test")

        self.memory.reset()

        assert self.memory.plan_context.duration is None
        assert len(self.memory.conversation_history) == 0

    def test_multiple_cities(self):
        self.memory.update_plan_context(cities=["Zaragoza", "Madrid", "Barcelona"])
        assert len(self.memory.plan_context.cities) == 3
        assert "Madrid" in self.memory.plan_context.cities

    def test_multiple_place_types(self):
        self.memory.update_plan_context(
            place_types=["bars", "restaurants", "museums"]
        )
        assert len(self.memory.plan_context.place_types) == 3
        assert "restaurants" in self.memory.plan_context.place_types

    def test_budget_levels(self):
        self.memory.update_plan_context(budget="high")
        assert self.memory.plan_context.budget == "high"

        self.memory.update_plan_context(budget="low")
        assert self.memory.plan_context.budget == "low"

    def test_transport_modes(self):
        self.memory.update_plan_context(transport="car")
        assert self.memory.plan_context.transport == "car"

        self.memory.update_plan_context(transport="public")
        assert self.memory.plan_context.transport == "public"


class TestPlanContext:
    """Test plan context dataclass."""

    def test_to_dict(self):
        context = PlanContext(
            duration="2h", num_people=2, cities=["Zaragoza"]
        )
        data = context.to_dict()
        assert data["duration"] == "2h"
        assert data["num_people"] == 2
        assert "created_at" in data

    def test_is_plan_ready_all_fields(self):
        context = PlanContext(
            duration="2h",
            num_people=2,
            cities=["Zaragoza"],
            place_types=["bars"],
            vibe="party",
        )
        ready, missing = context.is_plan_ready()
        assert ready is True
        assert missing == []

    def test_is_plan_ready_missing_fields(self):
        context = PlanContext(duration="2h", num_people=2)
        ready, missing = context.is_plan_ready()
        assert ready is False
        assert "cities" in missing
        assert "place_types" in missing
        assert "vibe" in missing

    def test_default_values(self):
        context = PlanContext()
        assert context.duration is None
        assert context.num_people is None
        assert context.cities == []
        assert context.place_types == []
        assert context.vibe is None
        assert context.budget is None
        assert context.transport is None
        assert context.emotion_detected is None
        assert context.user_questions_asked == []

    def test_emotion_tracking(self):
        context = PlanContext(emotion_detected="bored")
        assert context.emotion_detected == "bored"

        data = context.to_dict()
        assert data["emotion_detected"] == "bored"


class TestEmotionResponseTones:
    """Test emotion-based response tone recommendations."""

    def setup_method(self):
        self.detector = EmotionDetector()

    def test_all_emotions_have_tones(self):
        for emotion in UserEmotion:
            tone = self.detector.adapt_response_tone(emotion)
            assert isinstance(tone, str)
            assert len(tone) > 0

    def test_bored_tone_is_enthusiastic(self):
        tone = self.detector.adapt_response_tone(UserEmotion.BORED)
        assert any(
            keyword in tone.lower()
            for keyword in ["enthusiastic", "variety", "novelty"]
        )

    def test_stressed_tone_is_concise(self):
        tone = self.detector.adapt_response_tone(UserEmotion.STRESSED)
        assert any(
            keyword in tone.lower() for keyword in ["concise", "efficient", "direct"]
        )

    def test_romantic_tone_is_elegant(self):
        tone = self.detector.adapt_response_tone(UserEmotion.ROMANTIC)
        assert any(
            keyword in tone.lower()
            for keyword in ["elegant", "thoughtful", "special"]
        )

