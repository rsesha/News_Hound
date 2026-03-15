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

# Configuration for llama-swap API - now uses LOCAL_MODEL_PORT from .env
LOCAL_MODEL_PORT = os.getenv("LOCAL_MODEL_PORT", "8080")
LOCAL_MODEL_NAME = os.getenv("LOCAL_MODEL_NAME", "qwen35-small")
LOCAL_LLM_TIMEOUT = int(os.getenv("LOCAL_LLM_TIMEOUT", "180"))  # Default 180 seconds (3 minutes)
USE_GEMINI = os.getenv("USE_GEMINI", "False").lower() in ("true", "1", "yes")  # Force use Gemini for summarization
LLAMA_SWAP_BASE_URL = os.getenv("LLAMA_SWAP_BASE_URL", f"http://127.0.0.1:{LOCAL_MODEL_PORT}")
LLAMA_SWAP_API_URL = f"{LLAMA_SWAP_BASE_URL}/v1"

logger.info(f"Local LLM configured: Model={LOCAL_MODEL_NAME}, Port={LOCAL_MODEL_PORT}, Timeout={LOCAL_LLM_TIMEOUT}s, USE_GEMINI={USE_GEMINI}, URL={LLAMA_SWAP_BASE_URL}")

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
        
    def _make_request(self, endpoint: str, payload: Dict[str, Any], timeout: int = None) -> Dict[str, Any]:
        """Make HTTP request to llama-swap API."""
        url = f"{self.base_url}{endpoint}"
        headers = {"Content-Type": "application/json"}
        
        # Use provided timeout or default from environment
        actual_timeout = timeout if timeout else LOCAL_LLM_TIMEOUT
        
        try:
            print(f"DEBUG: Calling local LLM at {url} (timeout {actual_timeout}s)...")
            response = requests.post(url, headers=headers, json=payload, timeout=actual_timeout)
            response.raise_for_status()
            print(f"DEBUG: Local LLM call successful.")
            return response.json()
        except requests.exceptions.Timeout:
            logger.warning(f"Local LLM request timed out after {actual_timeout}s at {url}")
            return {}
        except Exception as e:
            logger.debug(f"Local LLM failed at {url}: {str(e)}")
            # Don't raise here, let the caller decide if they want to fallback
            return {}

    def _call_gemini(self, messages: List[Dict[str, str]], model_name: str) -> str:
        """Call Gemini API via google-genai."""
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise Exception("GEMINI_API_KEY not found in environment.")
        
        try:
            from google import genai
            from google.genai import types
            
            print(f"DEBUG: Calling Gemini API ({model_name})...")
            client = genai.Client(api_key=api_key)
            
            # Convert messages to Gemini format
            prompt = ""
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                prompt += f"{role.upper()}: {content}\n"
            
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=self.config.max_tokens,
                    temperature=self.config.temperature,
                )
            )
            print(f"DEBUG: Gemini API call successful.")
            return response.text
        except Exception as e:
            logger.error(f"Gemini API call failed: {str(e)}")
            raise Exception(f"Gemini API failed: {str(e)}")

    def call(self, messages: List[Dict[str, str]], model_name: Optional[str] = None) -> str:
        """Call the LLM with messages, falling back to Gemini if needed."""
        model_to_use = model_name or self.config.model_name
        
        # If USE_GEMINI is True, always use Gemini for summarization
        if USE_GEMINI:
            print(f"DEBUG: USE_GEMINI=True, using Gemini model: {model_to_use if 'gemini' in model_to_use.lower() else 'gemini-2.5-flash-lite'}")
            gemini_model = model_to_use if "gemini" in model_to_use.lower() else "gemini-2.5-flash-lite"
            return self._call_gemini(messages, gemini_model)
        
        # If model name implies gemini, use it directly
        if "gemini" in model_to_use.lower():
            return self._call_gemini(messages, model_to_use)
            
        # Otherwise try local first
        payload = {
            "model": model_to_use,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "top_p": self.config.top_p,
        }
        
        try:
            response = self._make_request("/chat/completions", payload)
            if response and "choices" in response:
                return str(response["choices"][0]["message"]["content"])
        except:
            pass
            
        # Fallback to Gemini if local fails and we have a key
        if os.getenv("GEMINI_API_KEY"):
            # Use a default gemini model if we were trying a local one
            fallback_model = "gemini-2.5-flash-lite" # or the one user mentioned
            if "gemini" not in model_to_use.lower():
                print(f"DEBUG: Local LLM failed. Falling back to {fallback_model}...")
                return self._call_gemini(messages, fallback_model)
        
        raise Exception("Failed to call both local and Gemini LLMs.")
    
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