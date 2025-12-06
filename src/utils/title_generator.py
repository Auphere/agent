"""Utility for generating chat titles automatically."""

from langchain_openai import ChatOpenAI
from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger


async def generate_chat_title(
    user_query: str,
    agent_response: str | None = None,
    language: str = "es",
    settings: Settings | None = None,
) -> str:
    """
    Generate a concise title for a chat based on the first user query.
    
    Args:
        user_query: First user message in the chat
        agent_response: Optional first agent response (for better context)
        language: Language code (es, en, etc.)
        settings: Optional settings instance
        
    Returns:
        Generated title (max 60 characters)
    """
    settings = settings or get_settings()
    logger = get_logger("title_generator")
    
    # Use a lightweight model for title generation
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.3,
        api_key=settings.openai_api_key,
        max_tokens=20,  # Titles should be short
    )
    
    # Create prompt based on language
    if language.startswith("es"):
        prompt = f"""Genera un título corto (máximo 6 palabras) para esta conversación basándote en la primera pregunta del usuario.

Pregunta del usuario: "{user_query}"
"""
        if agent_response:
            prompt += f"\nRespuesta del asistente: {agent_response[:100]}..."
        
        prompt += "\n\nResponde SOLO con el título, sin comillas ni explicaciones."
    else:
        prompt = f"""Generate a short title (maximum 6 words) for this conversation based on the user's first question.

User question: "{user_query}"
"""
        if agent_response:
            prompt += f"\nAssistant response: {agent_response[:100]}..."
        
        prompt += "\n\nReply with ONLY the title, no quotes or explanations."
    
    try:
        response = await llm.ainvoke(prompt)
        title = response.content.strip()
        
        # Remove quotes if present
        title = title.strip('"').strip("'").strip()
        
        # Truncate to 60 characters max
        if len(title) > 60:
            title = title[:57] + "..."
        
        # Fallback to a default title if empty
        if not title:
            title = "Nueva conversación" if language.startswith("es") else "New conversation"
        
        logger.debug("title_generated", title=title, query_length=len(user_query))
        
        return title
        
    except Exception as exc:
        logger.error("title_generation_failed", error=str(exc))
        # Fallback title
        if language.startswith("es"):
            # Try to extract a simple title from the query
            words = user_query.split()[:6]
            title = " ".join(words)
            if len(title) > 60:
                title = title[:57] + "..."
            return title if title else "Nueva conversación"
        else:
            words = user_query.split()[:6]
            title = " ".join(words)
            if len(title) > 60:
                title = title[:57] + "..."
            return title if title else "New conversation"

