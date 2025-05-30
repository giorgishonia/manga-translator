import base64
import cv2
import numpy as np
import requests
import json

from .base import OCREngine
from ..utils.textblock import TextBlock, adjust_text_line_coordinates
from ..utils.translator_utils import MODEL_MAP


class GPTOCR(OCREngine):
    """OCR engine using GPT vision capabilities via direct REST API calls."""
    
    def __init__(self):
        self.api_key = None
        self.expansion_percentage = 0
        self.model = 'GPT-4o'
        self.api_base_url = 'https://api.openai.com/v1/chat/completions'
        self.max_tokens = 5000
        
    def initialize(self, api_key: str, model: str = 'GPT-4o', 
                  expansion_percentage: int = 0) -> None:
        """
        Initialize the GPT OCR with API key and parameters.
        
        Args:
            api_key: OpenAI API key for authentication
            model: GPT model to use for OCR (defaults to gpt-4o)
            expansion_percentage: Percentage to expand text bounding boxes
        """
        self.api_key = api_key
        self.model = MODEL_MAP.get(model)
        self.expansion_percentage = expansion_percentage
        
    def process_image(self, img: np.ndarray, blk_list: list[TextBlock]) -> list[TextBlock]:
        """
        Process an image with GPT-based OCR by processing individual text regions.
        
        Args:
            img: Input image as numpy array
            blk_list: List of TextBlock objects to update with OCR text
            
        Returns:
            List of updated TextBlock objects with recognized text
        """
        for blk in blk_list:
            try:
                # Get box coordinates
                if blk.bubble_xyxy is not None:
                    x1, y1, x2, y2 = blk.bubble_xyxy
                else:
                    x1, y1, x2, y2 = adjust_text_line_coordinates(
                        blk.xyxy, 
                        self.expansion_percentage, 
                        self.expansion_percentage, 
                        img
                    )
                
                # Check if coordinates are valid
                if x1 < x2 and y1 < y2 and x1 >= 0 and y1 >= 0 and x2 <= img.shape[1] and y2 <= img.shape[0]:
                    # Crop image and encode
                    cropped_img = img[y1:y2, x1:x2]
                    cv2_to_gpt = cv2.imencode('.png', cropped_img)[1]
                    cv2_to_gpt = base64.b64encode(cv2_to_gpt).decode('utf-8')
                    
                    # Get OCR result from GPT
                    blk.text = self._get_gpt_ocr(cv2_to_gpt)
            except Exception as e:
                print(f"GPT OCR error on block: {str(e)}")
                blk.text = ""
                
        return blk_list
    
    def _get_gpt_ocr(self, base64_image: str) -> str:
        """
        Get OCR result from GPT model using direct REST API call.
        
        Args:
            base64_image: Base64 encoded image
            
        Returns:
            OCR result text
        """
        if not self.api_key:
            raise ValueError("API key not initialized. Call initialize() first.")
            
        try:
            # Prepare request headers
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            # Prepare request payload
            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Write out the text in this image. Do NOT Translate. Do not write anything else"},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                        ]
                    }
                ],
                "max_tokens": self.max_tokens
            }
            
            # Make POST request to OpenAI API
            response = requests.post(
                self.api_base_url,
                headers=headers,
                data=json.dumps(payload)
            )
            
            # Parse response
            if response.status_code == 200:
                response_json = response.json()
                text = self._extract_text_from_response(response_json)
                # Replace newlines with spaces
                return text.replace('\n', ' ') if '\n' in text else text
            else:
                print(f"API error: {response.status_code} {response.text}")
                return ""
                
        except Exception as e:
            print(f"GPT API request error: {str(e)}")
            return ""
            
    def _extract_text_from_response(self, response_data):
        """
        Extract text from API response, handling different response formats.
        
        Args:
            response_data: JSON response from the API
            
        Returns:
            Extracted text
        """
        # First check for error responses
        if "error" in response_data:
            error_info = response_data["error"]
            error_message = error_info.get("message", "Unknown API error")
            error_code = error_info.get("code", "unknown")
            
            # Handle rate limiting specifically
            if error_code == 429 or "rate limit" in error_message.lower():
                provider = error_info.get("metadata", {}).get("provider_name", "API provider")
                error_msg = f"Rate limit exceeded for {provider}: {error_message}"
            else:
                error_msg = f"API error ({error_code}): {error_message}"
                
            print(f"API error during OCR: {error_msg}")
            return f"[OCR Error: {error_msg}]"
            
        # Standard OpenAI format
        if "choices" in response_data:
            if len(response_data["choices"]) > 0:
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
            
        # If we can't find a standard format, log and return empty
        print(f"Unexpected API response format: {json.dumps(response_data)[:500]}...")
        return "[OCR Error: Unrecognized API response format]"