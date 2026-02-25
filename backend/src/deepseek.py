import requests
import os
import logging
from .constants import BOT_NAME, BOT_BRAND

class DeepSeek:
    def __init__(self, api_key):
        self.api_key = api_key
        self.url = "https://api.deepseek.com/v1/chat/completions"
        # Use a valid DeepSeek model name. Update as needed per DeepSeek docs.
        # Model can be overridden via env; default is generic chat model.
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        logging.info(f"DeepSeek model set to: {self.model}")

    def generate_response(self, context: str, question: str, instruction: str | None = None) -> str:
        if not instruction:
            instruction = (
                f"You are {BOT_NAME}, an intelligent assistant for {BOT_BRAND}. "
                "Use the provided context to answer the user's question accurately. "
                "If the context is empty or insufficient, use your general knowledge to answer helpfuly, "
                "but prioritize the provided context. Be professional and concise."
            )
        if not self.model:
            logging.error("DeepSeek model name is not set. Please set DEEPSEEK_MODEL env variable or update the code.")
            return ""
        
        system_msg = instruction
        user_content = f"Context:\n{context}\n\nQuestion: {question}\n\nProvide the best possible answer."
        
        # If context is explicitly empty/missing, adjust the prompt to allow general knowledge
        if not context or "No specific internal company documents" in context:
            user_content = f"Question: {question}\n\nAnswer the user's question to the best of your ability."

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_content}
            ]
        }
        logging.info(f"Calling DeepSeek with model: {self.model}")
        try:
            response = requests.post(self.url, headers=headers, json=data)
            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"]
                return content
            logging.error(f"DeepSeek API error: {response.status_code} {response.text}")
            return f"I'm sorry, I'm having trouble connecting to my brain right now. (Status: {response.status_code})"
        except Exception as e:
            logging.error(f"DeepSeek exception: {e}")
            return "I'm sorry, an internal error occurred while processing your request."