import os
from typing import Any, Dict, Optional
from google import genai
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class LLMService:

    def __init__(self, model_name: str = "gemini-3-flash-preview"):
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY environment variable not set.")
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.chat = self.client.chats.create(model=self.model_name)

    def send_message(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Send a prompt to the model and return the response.
        Args:
            prompt: The prompt string to send.
            kwargs: Additional config for the model (temperature, max_output_tokens, etc.)
        Returns:
            Dict with the response text and any error encountered.
        """
        try:
            response = self.chat.send_message(
                message=genai.types.Part.from_text(text=prompt),
                config=genai.types.GenerateContentConfig(**kwargs),
            )
            return {"response": response.text}
        except Exception as e:
            print(f"Error in LLMService.send_message: {e}")
            return {"response": None, "error": str(e)}


llm_service = LLMService()
