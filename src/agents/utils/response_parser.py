"""Utility to extract the Final Answer from ReAct agent responses."""

from __future__ import annotations

import re
from typing import Optional


def extract_final_answer(raw_response: str) -> str:
    """
    Extract only the Final Answer from a ReAct agent response.
    
    ReAct agents use format:
    Thought: ...
    Action: ...
    Observation: ...
    Final Answer: [this is what we want to show]
    
    This function extracts only the text after "Final Answer:" and cleans it.
    
    Args:
        raw_response: Raw response from agent (may include Thought/Action/Observation)
        
    Returns:
        Clean final answer text only
    """
    if not raw_response:
        return raw_response
    
    # Try to extract Final Answer using regex
    # Pattern: Find "Final Answer:" followed by any content
    pattern = r'(?:Final Answer:)\s*(.*?)(?:\n\n|$)'
    match = re.search(pattern, raw_response, re.DOTALL | re.IGNORECASE)
    
    if match:
        final_answer = match.group(1).strip()
        
        # Clean up any remaining markdown or formatting artifacts
        final_answer = final_answer.replace('**Thought:**', '').replace('**Action:**', '')
        final_answer = final_answer.strip()
        
        return final_answer
    
    # If no "Final Answer:" found, check if response contains Thought/Action markers
    # If it does, something went wrong - return a cleaned version
    if '**Thought:**' in raw_response or '**Action:**' in raw_response or 'Observation:' in raw_response:
        # Try to extract just the last paragraph or clean content
        # Remove all ReAct markers
        cleaned = re.sub(r'\*\*(?:Thought|Action|Observation):\*\*.*?(?=\*\*(?:Thought|Action|Observation|Final Answer):|$)', '', raw_response, flags=re.DOTALL)
        cleaned = cleaned.strip()
        
        # If still has issues, return a safe message
        if not cleaned or len(cleaned) < 10:
            return "Lo siento, hubo un error al procesar la respuesta. ¿Podrías reformular tu pregunta?"
        
        return cleaned
    
    # If no ReAct markers found, return as-is (normal response)
    return raw_response.strip()

