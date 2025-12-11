"""ReAct Agent implementation using LangGraph."""

from __future__ import annotations

from typing import Any, Dict, List

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

# Removed: from src.agents.plan_memory import PlanMemoryManager (deprecated)
from src.agents.prompts.system_prompts import get_system_prompt
from src.agents.utils.place_extractor import extract_places_from_messages
from src.agents.utils.place_saver import save_places_to_db
from src.agents.utils.response_parser import extract_final_answer
from src.agents.utils.text_cleaner import clean_response_text
from src.classifiers.emotion_detector import EmotionDetector, UserEmotion
from src.config.settings import Settings, get_settings
from src.tools.tool_registry import get_available_tools
from src.utils.logger import get_logger


class ReactAgent:
    """
    ReAct-style agent that can reason about user queries and use tools.
    
    Flow:
    1. Receives user query + context
    2. Thinks about what to do
    3. Uses tools if needed (e.g., search_places)
    4. Generates final response
    """

    def __init__(self, model_name: str, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.logger = get_logger("react-agent", settings=self.settings)
        self.model_name = model_name
        
        # Initialize LLM
        self.llm = ChatOpenAI(
            model=model_name,
            temperature=0.7,
            api_key=self.settings.openai_api_key,
        )
        
        # Get available tools
        self.tools = get_available_tools()
        
        # Create the agent using LangGraph
        self.agent_executor = create_react_agent(
            model=self.llm,
            tools=self.tools,
        )
        
        # Initialize emotion detector
        self.emotion_detector = EmotionDetector()
        
        # Plan memory manager (session-level)
        # We now use the singleton pattern in PlanMemoryManager directly
        # self.plan_memory: Dict[str, PlanMemoryManager] = {}

    async def run(
        self,
        query: str,
        language: str = "es",
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        Execute the agent with the user query.
        
        Args:
            query: User's question or request
            language: Language for the response
            context: Additional context (location, preferences, conversation_history)
            
        Returns:
            Dictionary with response_text, places, and metadata
        """
        context = context or {}
        
        self.logger.info("agent-starting", query=query, model=self.model_name)
        
        # ============ EMOTION DETECTION ============
        emotion, emotion_confidence = self.emotion_detector.detect(query)
        context["detected_emotion"] = emotion.value
        context["emotion_confidence"] = emotion_confidence
        
        self.logger.info(
            "emotion-detected",
            emotion=emotion.value,
            confidence=emotion_confidence
        )
        
        # Build system prompt
        system_prompt = get_system_prompt(language=language, context=context)
        
        # Adapt system prompt based on emotion
        tone = self.emotion_detector.adapt_response_tone(emotion)
        system_prompt_with_emotion = system_prompt + f"\n\n## 🎯 TONE INSTRUCTION\n{tone}"
        
        # ============ PLAN CONTEXT MANAGEMENT ============
        # ✅ NEW: Extract plan state from conversation metadata (database-backed)
        intention = context.get("intention", "")
        
        if intention == "PLAN":
            from src.agents.context_builder import PlanContextExtractor
            
            # Extract plan state from conversation context
            memory_context = context.get("memory_context", {})
            if memory_context and "recent_turns" in memory_context:
                # This would require passing ConversationContext, but for now
                # we'll use a simpler approach: extract from query
                extracted = PlanContextExtractor.extract_from_query(query, language)
                
                if extracted:
                    # Add to system prompt
                    plan_info = ", ".join(f"{k}: {v}" for k, v in extracted.items())
                    system_prompt_with_emotion += f"\n\n## 📋 PLAN INFO DETECTED\n{plan_info}"
                    self.logger.info("plan-info-extracted", extracted=extracted)
        
        # Prepare messages with conversation history
        messages = [
            SystemMessage(content=system_prompt_with_emotion),
        ]
        
        # ✅ Inject conversation history if available (ENHANCED with new system)
        history_messages = context.get("history_messages", [])
        if history_messages:
            self.logger.info(
                "agent-using-message-history",
                count=len(history_messages),
                source="conversation_buffer"
            )
            messages.extend(history_messages)
        else:
            # Fallback: Parse string history (for backward compatibility)
            conversation_history = context.get("conversation_history", "")
            if conversation_history:
                self.logger.info(
                    "agent-using-history-string",
                    history_length=len(conversation_history),
                    source="legacy"
                )
                # Add as single system message for simplicity
                messages.append(
                    SystemMessage(content=f"## Previous Conversation:\n{conversation_history}")
                )
        
        # Add current query
        messages.append(HumanMessage(content=query))
        
        try:
            # Invoke the agent
            result = await self.agent_executor.ainvoke(
                {"messages": messages}
            )
            
            # Extract the final response
            output_messages = result.get("messages", [])
            final_message = output_messages[-1] if output_messages else None
            
            response_text = ""
            if final_message and isinstance(final_message, AIMessage):
                raw_content = final_message.content
                # Extract only Final Answer (remove Thought/Action/Observation markers)
                final_answer_only = extract_final_answer(raw_content)
                # Clean response text (remove URLs, etc.)
                response_text = clean_response_text(final_answer_only)
            
            # Extract places from tool results
            places = extract_places_from_messages(output_messages)
            
            # Save places to DB (upsert)
            if places:
                try:
                    places = await save_places_to_db(places, self.settings)
                    self.logger.info("places-saved-to-db", count=len(places))
                except Exception as exc:
                    self.logger.error("failed-to-save-places", error=str(exc))
                    # Continue with original places if save fails
            
            # Update plan memory if applicable
            # if intention == "PLAN":
            #    plan_mgr.add_turn(query, response_text)
            
            self.logger.info(
                "agent-completed",
                has_response=bool(response_text),
                places_found=len(places)
            )
            
            return {
                "response_text": response_text,
                "places": places,
                "tool_calls": len([m for m in output_messages if hasattr(m, "tool_calls")]),
                "reasoning_steps": len(output_messages),
                "detected_emotion": emotion.value,
                "emotion_confidence": emotion_confidence,
                "agent_type": "react",
            }
            
        except Exception as exc:
            self.logger.error("agent-execution-failed", error=str(exc))
            return {
                "response_text": f"Lo siento, ocurrió un error al procesar tu solicitud: {str(exc)}",
                "places": [],
                "tool_calls": 0,
                "reasoning_steps": 0,
                "error": str(exc),
                "detected_emotion": emotion.value,
                "emotion_confidence": emotion_confidence,
                "agent_type": "react",
            }

