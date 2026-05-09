import os
import anthropic
from typing import List, Dict

class BrainManager:
    """
    Lily's Brain.
    Powered by Anthropic's Claude API (claude-sonnet-4-6).
    Handles the conversational logic, tool calling, and empathy formatting.
    """
    def __init__(self):
        self.client = anthropic.Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY")
        )
        self.model = "claude-sonnet-4-6" # Specified in the implementation plan

    def generate_response(self, system_prompt: str, messages: List[Dict[str, str]], tools: List[Dict] = None) -> Dict:
        """
        Sends the conversation history to Claude and gets Lily's next response or tool call.
        """
        # Anthropic expects 'user' and 'assistant' roles
        formatted_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            # Ensure proper alternating format if needed, but basic append works for now
            formatted_messages.append({"role": role, "content": msg.get("content")})

        kwargs = {
            "model": self.model,
            "max_tokens": 512,
            "system": system_prompt,
            "messages": formatted_messages,
            "temperature": 0.3, # Low temperature for medical consistency
        }

        if tools:
            kwargs["tools"] = tools

        response = self.client.messages.create(**kwargs)
        
        # Parse response to see if Claude wants to call a tool or just speak
        if response.stop_reason == "tool_use":
            tool_calls = [c for c in response.content if c.type == "tool_use"]
            return {"type": "tool", "tool_calls": tool_calls}
        
        # Standard text response
        text_content = next((c.text for c in response.content if c.type == "text"), "")
        return {"type": "text", "content": text_content}
