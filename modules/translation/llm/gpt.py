from typing import Any
import numpy as np
import requests
import json

from .base import BaseLLMTranslation
from ...utils.translator_utils import MODEL_MAP


class GPTTranslation(BaseLLMTranslation):
    """Translation engine using OpenAI GPT models through direct REST API calls."""
    
    def __init__(self):
        super().__init__()
        self.model_name = None
        self.api_key = None
        self.api_base_url = "https://api.openai.com/v1"
        self.temperature = 1.0
        self.max_tokens = 5000
        self.supports_images = True
    
    def initialize(self, settings: Any, source_lang: str, target_lang: str, model_name: str, **kwargs) -> None:
        """
        Initialize GPT translation engine.
        
        Args:
            settings: Settings object with credentials
            source_lang: Source language name
            target_lang: Target language name
            model_name: GPT model name
        """
        super().initialize(settings, source_lang, target_lang, **kwargs)
        
        self.model_name = model_name
        credentials = settings.get_credentials(settings.ui.tr('Open AI GPT'))
        self.api_key = credentials.get('api_key', '')
        self.model = MODEL_MAP.get(self.model_name)
    
    def _perform_translation(self, user_prompt: str, system_prompt: str, image: np.ndarray) -> str:
        """
        Perform translation using direct REST API calls to OpenAI.
        
        Args:
            user_prompt: Text prompt from user
            system_prompt: System instructions
            image: Image as numpy array
            
        Returns:
            Translated text
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        if self.supports_images and self.img_as_llm_input:
            # Use the base class method to encode the image
            encoded_image, mime_type = self.encode_image(image)
            
            messages = [
                {
                    "role": "system", 
                    "content": [{"type": "text", "text": system_prompt}]
                },
                {
                    "role": "user", 
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded_image}"}}
                    ]
                }
            ]
        else:
            messages = [
                {
                    "role": "system", 
                    "content": [{"type": "text", "text": system_prompt}]
                },
                {
                    "role": "user", 
                    "content": [{"type": "text", "text": user_prompt}]
                }
            ]

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        return self._make_api_request(payload, headers)
    
    def _make_api_request(self, payload, headers):
        """
        Make API request and process response
        """
        try:
            # Check if the API base URL already contains the /chat/completions endpoint
            if self.api_base_url.endswith('/chat/completions'):
                api_url = self.api_base_url
            else:
                api_url = f"{self.api_base_url}/chat/completions"
                
            response = requests.post(
                api_url,
                headers=headers,
                data=json.dumps(payload)
            )
            
            response.raise_for_status()
            response_data = response.json()
            
            # First check for error responses
            if "error" in response_data:
                error_info = response_data["error"]
                error_message = error_info.get("message", "Unknown API error")
                error_code = error_info.get("code", "unknown")
                
                # Handle rate limiting specifically
                if error_code == 429 or "rate limit" in error_message.lower():
                    provider = error_info.get("metadata", {}).get("provider_name", "API provider")
                    raise RuntimeError(f"Rate limit exceeded for {provider}: {error_message}")
                
                # Handle other errors
                raise RuntimeError(f"API error ({error_code}): {error_message}")
            
            # Handle different API response formats
            if "choices" in response_data:
                # Standard OpenAI format
                if len(response_data["choices"]) > 0:
                    # Handle potential differences in response structure
                    choice = response_data["choices"][0]
                    if "message" in choice and "content" in choice["message"]:
                        return choice["message"]["content"]
                    elif "text" in choice:  # Some APIs return text directly
                        return choice["text"]
            
            # Handle Anthropic Claude and similar formats
            if "content" in response_data:
                return response_data["content"]
                
            # Handle other potential formats
            if "response" in response_data:
                return response_data["response"]
                
            # If we can't find a standard format, log and raise an error
            print(f"Unexpected API response format: {json.dumps(response_data)[:500]}...")
            raise ValueError(f"Couldn't extract text from API response: response format not recognized")
            
        except requests.exceptions.RequestException as e:
            error_msg = f"API request failed: {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_details = e.response.json()
                    if "error" in error_details:
                        # Extract and format error information if available
                        error_info = error_details["error"]
                        error_message = error_info.get("message", "Unknown error")
                        error_code = error_info.get("code", e.response.status_code)
                        
                        # Special handling for rate limit errors
                        if error_code == 429 or "rate limit" in error_message.lower():
                            provider = error_info.get("metadata", {}).get("provider_name", "API provider")
                            error_msg = f"Rate limit exceeded for {provider}: {error_message}"
                        else:
                            error_msg = f"API error ({error_code}): {error_message}"
                    else:
                        error_msg += f" - {json.dumps(error_details)}"
                except:
                    error_msg += f" - Status code: {e.response.status_code}"
            raise RuntimeError(error_msg)