"""
Local LLM integration for llama-swap API.
This module provides functions to call local LLM models via llama-swap's V1 API.
"""

import os
import json
import requests
import logging
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)

# Configuration for llama-swap API
LLAMA_SWAP_BASE_URL = os.getenv("LLAMA_SWAP_BASE_URL", "http://127.0.0.1:8080")
LLAMA_SWAP_API_URL = f"{LLAMA_SWAP_BASE_URL}/v1"

class LocalLLMConfig(BaseModel):
    """Configuration for local LLM models."""
    model_name: str = Field(default="qwen35-small")
    temperature: float = Field(default=0.7)
    max_tokens: int = Field(default=1024)
    top_p: float = Field(default=0.9)
    presence_penalty: float = Field(default=0.0)
    frequency_penalty: float = Field(default=0.0)

class LocalLLM:
    """Local LLM client for llama-swap API."""
    
    def __init__(self, config: Optional[LocalLLMConfig] = None):
        self.config = config or LocalLLMConfig()
        self.base_url = LLAMA_SWAP_API_URL
        
    def _make_request(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Make HTTP request to llama-swap API."""
        url = f"{self.base_url}{endpoint}"
        headers = {"Content-Type": "application/json"}
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Local LLM failed at {url}: {str(e)}")
            raise Exception(f"Failed to call local LLM: {str(e)}")

    def call(self, messages: List[Dict[str, str]], model_name: Optional[str] = None) -> str:
        """Call the local LLM with messages."""
        model_to_use = model_name or self.config.model_name
        
        payload = {
            "model": model_to_use,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "top_p": self.config.top_p,
        }
        
        response = self._make_request("/chat/completions", payload)
        return str(response["choices"][0]["message"]["content"])
    
    def call_structured_output(self, messages: List[Dict[str, str]], schema: Any, model_name: Optional[str] = None) -> Any:
        """Call the local LLM with structured output support."""
        return self.call(messages, model_name)

def create_local_llm_from_config(config: RunnableConfig, model_name: Optional[str] = None) -> LocalLLM:
    """Create a LocalLLM instance from RunnableConfig."""
    model_name = model_name or "qwen35-small"
    
    if config and "configurable" in config:
        configurable = config["configurable"]
        if "model_name" in configurable:
            model_name = configurable["model_name"]
    
    return LocalLLM(LocalLLMConfig(model_name=model_name))

def convert_messages_to_llama_format(messages: List[BaseMessage]) -> List[Dict[str, str]]:
    """Convert LangChain messages to llama-swap format."""
    formatted_messages = []
    
    for message in messages:
        if isinstance(message, HumanMessage):
            role = "user"
            content = str(message.content)
        elif isinstance(message, AIMessage):
            role = "assistant"
            content = str(message.content)
        else:
            role = "user"
            content = str(message.content)
            
        formatted_messages.append({"role": role, "content": content})
    
    return formatted_messages