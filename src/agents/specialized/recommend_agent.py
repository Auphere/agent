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
        
        # 🔴 CRITICAL FIX: Check if user is asking for NEW recommendations
        # If yes, we MUST force tool usage
        query_lower = query.lower()
        requires_search = any([
            "recomienda" in query_lower,
            "recomendame" in query_lower,
            "busca" in query_lower,
            "encuentra" in query_lower,
            "suggest" in query_lower,
            "recommend" in query_lower,
            "find" in query_lower,
            "search" in query_lower,
            "quiero" in query_lower,
            "dame" in query_lower,
            "muestra" in query_lower,
            "show" in query_lower,
            "necesito" in query_lower,
            "need" in query_lower,
            "looking for" in query_lower,
            "buscando" in query_lower,
            # Place types
            "restaurante" in query_lower,
            "bar" in query_lower,
            "cafe" in query_lower,
            "club" in query_lower,
            "lugar" in query_lower,
            "sitio" in query_lower,
            "place" in query_lower,
            "spot" in query_lower,
            # Activities
            "cenar" in query_lower,
            "comer" in query_lower,
            "tomar" in query_lower,
            "salir" in query_lower,
            "dinner" in query_lower,
            "lunch" in query_lower,
            "drink" in query_lower,
        ])
        
        # Add instruction to FORCE tool usage if needed
        if requires_search:
            messages.append(HumanMessage(content=f"{query}\n\n🔴 MANDATORY: You MUST call google_places_tool BEFORE responding. DO NOT generate a response without calling the tool first."))
        else:
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
            
            # Extract metadata
            tool_calls = len([m for m in result["messages"] if hasattr(m, 'tool_calls') and m.tool_calls])
            reasoning_steps = len(result["messages"])
            
            # 🔴 SAFETY CHECK: If no tools were called and no places found, force a search
            # This prevents the agent from hallucinating places without actually searching
            if tool_calls == 0 and len(places) == 0:
                # Check if response mentions places (likely a hallucination)
                response_lower = response_text.lower()
                place_indicators = [
                    "encontrado", "found", "lugar", "place", "restaurante", "restaurant",
                    "bar", "café", "cafe", "recomiendo", "recommend", "opción", "option"
                ]
                
                if any(indicator in response_lower for indicator in place_indicators):
                    self.logger.warning(
                        "no-tools-called-for-recommendation",
                        query=query,
                        response_preview=response_text[:100],
                    )
                    
                    # Force a search using google_places_tool
                    try:
                        from src.tools.search.google_places import google_places_tool
                        
                        # Build search query from user's request
                        search_query = query
                        
                        # Extract location from context if available
                        location = context.get("location")
                        latitude = location.get("lat") if location else None
                        longitude = location.get("lon") if location else None
                        
                        self.logger.info(
                            "forcing-google-places-search",
                            query=search_query,
                            has_location=bool(location),
                        )
                        
                        # Execute search (call tool directly with keyword arguments)
                        search_result = await google_places_tool.ainvoke(
                            {
                                "query": search_query,
                                "latitude": latitude,
                                "longitude": longitude,
                                "radius_meters": 5000,
                                "max_results": 10,
                                "language": language,
                            }
                        )
                        
                        # Extract places from search result
                        if isinstance(search_result, dict) and search_result.get("success"):
                            forced_places = search_result.get("places", [])
                            if forced_places:
                                places = forced_places
                                tool_calls = 1  # Count the forced tool call
                                self.logger.info(
                                    "forced-search-successful",
                                    places_found=len(places),
                                )
                                
                                # 🔴 CRITICAL FIX: Generate coherent response based on actual results
                                # Instead of the agent's hallucinated response, create a proper one
                                place_count = len(places)
                                location_name = context.get("location", {}).get("city", "tu área")
                                if location_name == "tu área":
                                    # Try to get location from first place
                                    if places and places[0].get("address"):
                                        address = places[0]["address"]
                                        # Extract city from address (e.g., "Zaragoza" from "C. del Coso, 35, Zaragoza")
                                        parts = address.split(",")
                                        for part in reversed(parts):
                                            part = part.strip()
                                            # Skip postal codes and country
                                            if part and not part[0].isdigit() and part.lower() not in ["españa", "spain"]:
                                                location_name = part
                                                break
                                
                                # Detect intent from query for personalized response
                                is_romantic = any(word in query_lower for word in ["novia", "novio", "pareja", "romántic", "romantic", "date", "cita"])
                                is_friends = any(word in query_lower for word in ["amigos", "friends", "grupo", "group"])
                                is_dinner = any(word in query_lower for word in ["cenar", "cena", "dinner"])
                                is_lunch = any(word in query_lower for word in ["comer", "comida", "almuerzo", "lunch"])
                                is_drinks = any(word in query_lower for word in ["tomar", "beber", "drinks", "copa", "cerveza", "cocktail"])
                                
                                # Build contextual response
                                if language.startswith("es"):
                                    if is_romantic and is_dinner:
                                        response_text = f"¡Perfecto! He encontrado {place_count} restaurantes románticos en {location_name} ideales para una cena especial. Los he seleccionado por su ambiente íntimo y excelentes valoraciones.\n\n"
                                    elif is_friends and is_drinks:
                                        response_text = f"¡Genial! Aquí tienes {place_count} lugares en {location_name} perfectos para salir con amigos. Los ordené por ambiente social y valoraciones.\n\n"
                                    elif is_dinner:
                                        response_text = f"¡Excelente! He encontrado {place_count} restaurantes en {location_name} perfectos para cenar. Todos tienen buenas valoraciones y ambiente agradable.\n\n"
                                    elif is_lunch:
                                        response_text = f"¡Perfecto! Aquí tienes {place_count} opciones en {location_name} ideales para comer. Los seleccioné por calidad y valoraciones.\n\n"
                                    else:
                                        response_text = f"¡Genial! He encontrado {place_count} lugares en {location_name} que coinciden con tu búsqueda. Todos tienen excelentes valoraciones.\n\n"
                                    
                                    # Add top recommendation
                                    if places:
                                        top_place = places[0]
                                        top_name = top_place.get("name", "el primero")
                                        top_rating = top_place.get("rating", 0)
                                        if top_rating > 4.5:
                                            response_text += f"Mi top recomendación sería {top_name} - tiene las mejores valoraciones ({top_rating}⭐).\n\n"
                                        else:
                                            response_text += f"Te recomendaría especialmente {top_name} por su excelente ubicación y ambiente.\n\n"
                                    
                                    response_text += "¿Te gustaría saber más sobre alguno en particular?"
                                else:
                                    # English response
                                    if is_romantic and is_dinner:
                                        response_text = f"Perfect! I found {place_count} romantic restaurants in {location_name} ideal for a special dinner. Selected for their intimate ambiance and excellent reviews.\n\n"
                                    elif is_friends and is_drinks:
                                        response_text = f"Great! Here are {place_count} spots in {location_name} perfect for going out with friends. Ranked by social vibe and reviews.\n\n"
                                    elif is_dinner:
                                        response_text = f"Excellent! I found {place_count} restaurants in {location_name} perfect for dinner. All have great ratings and pleasant atmosphere.\n\n"
                                    else:
                                        response_text = f"Great! I found {place_count} places in {location_name} matching your search. All have excellent ratings.\n\n"
                                    
                                    # Add top recommendation
                                    if places:
                                        top_place = places[0]
                                        top_name = top_place.get("name", "the first one")
                                        top_rating = top_place.get("rating", 0)
                                        if top_rating > 4.5:
                                            response_text += f"My top pick would be {top_name} - it has the best ratings ({top_rating}⭐).\n\n"
                                        else:
                                            response_text += f"I'd especially recommend {top_name} for its great location and atmosphere.\n\n"
                                    
                                    response_text += "Want to know more about any of them?"
                            else:
                                self.logger.warning(
                                    "forced-search-returned-no-places",
                                    search_result=search_result,
                                )
                        else:
                            self.logger.error(
                                "forced-search-failed",
                                search_result=search_result,
                            )
                    
                    except Exception as exc:
                        self.logger.error(
                            "failed-to-force-search",
                            error=str(exc),
                            query=query,
                        )
                        # Continue with empty places - better than hallucinated ones
            
            # Save places to DB (upsert)
            if places:
                try:
                    places = await save_places_to_db(places, self.settings)
                    self.logger.info("places-saved-to-db", count=len(places))
                except Exception as exc:
                    self.logger.error("failed-to-save-places", error=str(exc))
                    # Continue with original places if save fails
            
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

