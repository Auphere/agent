"""RecommendAgent - Specialized agent for recommendations and comparisons."""

from __future__ import annotations

from typing import Any, Dict

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from src.agents.prompts.recommend_prompts import get_recommend_agent_prompt
from src.agents.utils.place_extractor import extract_places_from_messages
from src.agents.utils.place_saver import save_places_to_db
from src.agents.utils.text_cleaner import clean_response_text
from src.agents.utils.response_parser import extract_final_answer
from src.config.settings import Settings, get_settings
from src.tools.tool_registry import get_recommend_tools
from src.utils.logger import get_logger


class RecommendAgent:
    """
    Specialized agent optimized for recommendations and comparisons.
    
    Characteristics:
    - Uses gpt-4-turbo (good reasoning for ranking)
    - Focuses on rank_by_score_tool
    - Opinionated, helpful responses
    - Medium complexity
    
    Best for:
    - "What's the best X?"
    - "Recommend Y"
    - "Compare A and B"
    - "Top 5 places for Z"
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.logger = get_logger("recommend-agent", settings=self.settings)
        
        # Use gpt-4o-mini for recommendations (fast and cost-effective)
        model_name = "gpt-4o-mini"
        
        self.llm = ChatOpenAI(
            model=model_name,
            temperature=0.5,  # Medium temperature for balanced recommendations
            api_key=self.settings.openai_api_key,
            timeout=20,  # Fast timeout (was 30s)
            max_retries=0,  # No retries for speed
            request_timeout=20,
        )
        
        # Get recommend-specific tools
        self.tools = get_recommend_tools()
        
        # Create agent
        self.agent_executor = create_react_agent(
            model=self.llm,
            tools=self.tools,
        )
        
        self.logger.info("recommend-agent-initialized", model=model_name)

    async def run(
        self,
        query: str,
        language: str = "en",
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        Execute recommend agent.
        
        Args:
            query: User's recommendation request
            language: Response language
            context: Additional context
            
        Returns:
            Dict with response_text, places, and metadata
        """
        context = context or {}
        
        self.logger.info(
            "recommend-agent-starting",
            query=query,
            language=language,
        )
        
        # Get specialized recommend prompt
        system_prompt = get_recommend_agent_prompt(context, language)
        
        messages = [SystemMessage(content=system_prompt)]
        
        # ✅ Inject conversation history if available
        history_messages = context.get("history_messages", [])
        if history_messages:
             messages.extend(history_messages)
        else:
            # Fallback string injection
            conversation_history = context.get("conversation_history", "")
            if conversation_history:
                messages[0].content += f"\n\n## Previous Conversation:\n{conversation_history}"
        
        messages.append(HumanMessage(content=query))
        
        try:
            # Execute agent
            result = await self.agent_executor.ainvoke(
                {"messages": messages}
            )
            
            # Extract response
            final_message = result["messages"][-1]
            raw_response_text = final_message.content if hasattr(final_message, 'content') else str(final_message)
            
            # Extract only Final Answer (remove Thought/Action/Observation markers)
            final_answer_only = extract_final_answer(raw_response_text)
            
            # Clean response text (remove URLs, etc.)
            response_text = clean_response_text(final_answer_only)
            
            # Extract places from tool results
            places = extract_places_from_messages(result["messages"])
            
            # Save places to DB (upsert)
            if places:
                try:
                    places = await save_places_to_db(places, self.settings)
                    self.logger.info("places-saved-to-db", count=len(places))
                except Exception as exc:
                    self.logger.error("failed-to-save-places", error=str(exc))
                    # Continue with original places if save fails
            
            # Extract metadata
            tool_calls = len([m for m in result["messages"] if hasattr(m, 'tool_calls') and m.tool_calls])
            reasoning_steps = len(result["messages"])
            
            self.logger.info(
                "recommend-agent-completed",
                tool_calls=tool_calls,
                reasoning_steps=reasoning_steps,
                places_found=len(places),
            )
            
            return {
                "response_text": response_text,
                "places": places,
                "tool_calls": tool_calls,
                "reasoning_steps": reasoning_steps,
                "agent_type": "recommend",
                "model_used": self.llm.model_name,
            }
            
        except Exception as exc:
            self.logger.error(
                "recommend-agent-failed",
                error=str(exc),
                query=query,
            )
            raise

