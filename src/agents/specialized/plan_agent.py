"""PlanAgent - Specialized agent for creating complete itineraries."""

from __future__ import annotations

from typing import Any, Dict

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from src.agents.prompts.plan_prompts import get_plan_agent_prompt
from src.agents.utils.place_extractor import extract_places_from_messages
from src.agents.utils.place_saver import save_places_to_db
from src.agents.utils.text_cleaner import clean_response_text
from src.agents.utils.response_parser import extract_final_answer
from src.config.settings import Settings, get_settings
from src.tools.tool_registry import get_plan_tools
from src.utils.logger import get_logger


class PlanAgent:
    """
    Specialized agent optimized for creating complete itineraries.
    
    Characteristics:
    - Uses gpt-4 or gpt-4-turbo (better reasoning)
    - Orchestrates multiple tools
    - Detailed, structured responses
    - Complex multi-step reasoning
    
    Best for:
    - "Plan X for Y people"
    - "Create itinerary"
    - "Organize evening/day/weekend"
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.logger = get_logger("plan-agent", settings=self.settings)
        
        # Use gpt-4o-mini for plans (fast and cost-effective)
        model_name = "gpt-4o-mini"
        
        self.llm = ChatOpenAI(
            model=model_name,
            temperature=0.7,  # Higher for creative planning
            api_key=self.settings.openai_api_key,
            timeout=45,  # Increased timeout for complex planning queries
            max_retries=1,  # Allow one retry for timeouts
            request_timeout=45,  # Hard limit on request
        )
        
        # Get plan-specific tools
        self.tools = get_plan_tools()
        
        # Create agent
        self.agent_executor = create_react_agent(
            model=self.llm,
            tools=self.tools,
        )
        
        self.logger.info("plan-agent-initialized", model=model_name)

    async def run(
        self,
        query: str,
        language: str = "en",
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        Execute plan agent.
        
        Args:
            query: User's plan request
            language: Response language
            context: Additional context
            
        Returns:
            Dict with response_text, places, and metadata
        """
        context = context or {}
        
        self.logger.info(
            "plan-agent-starting",
            query=query,
            language=language,
        )
        
        # Get specialized plan prompt
        system_prompt = get_plan_agent_prompt(context, language)
        
        messages = [SystemMessage(content=system_prompt)]
        
        # ✅ Inject conversation history if available (Improved)
        history_messages = context.get("history_messages", [])
        if history_messages:
            self.logger.info("plan-agent-using-message-history", count=len(history_messages))
            messages.extend(history_messages)
        else:
            # Fallback: String injection
            conversation_history = context.get("conversation_history", "")
            if conversation_history:
                messages[0].content += f"\n\n## IMPORTANT - Previous Conversation:\n{conversation_history}\n\nUSE this information to avoid asking for details the user already provided!"
        
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
                "plan-agent-completed",
                tool_calls=tool_calls,
                reasoning_steps=reasoning_steps,
                places_found=len(places),
            )
            
            return {
                "response_text": response_text,
                "places": places,
                "tool_calls": tool_calls,
                "reasoning_steps": reasoning_steps,
                "agent_type": "plan",
                "model_used": self.llm.model_name,
            }
            
        except Exception as exc:
            self.logger.error(
                "plan-agent-failed",
                error=str(exc),
                query=query,
            )
            raise

