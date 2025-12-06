"""Utility to extract places from agent tool results."""

from __future__ import annotations

import json
import ast
from typing import Any, Dict, List

from src.agents.utils.place_normalizer import normalize_places
from src.config import constants
from src.utils.logger import get_logger

logger = get_logger("place_extractor")


def extract_places_from_messages(messages: List[Any]) -> List[Dict[str, Any]]:
    """
    Extract places from LangChain agent messages.
    
    Looks through tool messages and extracts place data from:
    - places field
    - results field
    - Direct place objects
    
    Args:
        messages: List of LangChain messages from agent execution
        
    Returns:
        List of place dictionaries (limited to MAX_PLACES_PER_RESPONSE)
    """
    places = []
    
    for message in messages:
        # Skip AI messages with tool calls
        if hasattr(message, 'tool_calls') and message.tool_calls:
            continue
        
        # Check if this is a tool message (result from a tool)
        if hasattr(message, 'type') and message.type == 'tool':
            try:
                content = message.content
                
                parsed = None
                
                # If content is a string, try to parse it
                if isinstance(content, str):
                    try:
                        # Try standard JSON first
                        parsed = json.loads(content)
                    except (json.JSONDecodeError, TypeError):
                        # Fallback: Try ast.literal_eval for Python stringified dicts (single quotes)
                        try:
                            parsed = ast.literal_eval(content)
                        except (ValueError, SyntaxError):
                            parsed = None
                
                # If content is already a dict
                elif isinstance(content, dict):
                    parsed = content
                
                # Process parsed content
                if isinstance(parsed, dict):
                    # Check various possible field names
                    if 'places' in parsed and isinstance(parsed['places'], list):
                        places.extend(parsed['places'])
                    elif 'results' in parsed and isinstance(parsed['results'], list):
                        places.extend(parsed['results'])
                    elif 'data' in parsed and isinstance(parsed['data'], list):
                        places.extend(parsed['data'])
                        
            except Exception:
                # Silently skip malformed messages
                continue
    
    # Normalize all places to consistent format
    normalized = normalize_places(places)
    
    # Limit to maximum configured places
    total_found = len(normalized)
    limited = normalized[:constants.MAX_PLACES_PER_RESPONSE]
    
    if total_found > constants.MAX_PLACES_PER_RESPONSE:
        logger.info(
            "places_limited",
            total_found=total_found,
            limit=constants.MAX_PLACES_PER_RESPONSE,
            returned=len(limited),
        )
    
    return limited
