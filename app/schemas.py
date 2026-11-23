import time
from typing import List, Optional, Union, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

# --- OpenAI Compatible Models ---

class ChatMessage(BaseModel):
    role: str = Field(description="Role of the message sender: system, user, assistant, function, tool")
    content: Union[str, List[Any]] = Field(description="Content of the message")
    name: Optional[str] = Field(default=None, description="Optional name of author")

    model_config = ConfigDict(extra="allow")

    def get_text_content(self) -> str:
        """Extract plain text string from content."""
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            parts = []
            for item in self.content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
            return "\n".join(parts)
        return str(self.content)


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = Field(default="gemini-3.8-flash-high", description="Model name or alias")
    messages: List[ChatMessage] = Field(description="List of conversation messages")
    stream: Optional[bool] = Field(default=False, description="Whether to stream response tokens")
    temperature: Optional[float] = Field(default=None, description="Sampling temperature (accepted for compatibility)")
    top_p: Optional[float] = Field(default=None, description="Top-p sampling")
    max_tokens: Optional[int] = Field(default=None, description="Maximum tokens to generate")
    user: Optional[str] = Field(default=None, description="User or session identifier for multi-turn continuity")
    conversation_id: Optional[str] = Field(default=None, description="Explicit AGY conversation ID")
    effort: Optional[str] = Field(default=None, description="Reasoning effort: low, medium, high, xhigh, max")

    model_config = ConfigDict(extra="allow")


class ChatCompletionResponseChoice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: Optional[str] = "stop"


class ChatCompletionUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: List[ChatCompletionResponseChoice]
    usage: Optional[ChatCompletionUsage] = None
    conversation_id: Optional[str] = None


class DeltaMessage(BaseModel):
    role: Optional[str] = None
    content: Optional[str] = None


class ChatCompletionChunkChoice(BaseModel):
    index: int = 0
    delta: DeltaMessage
    finish_reason: Optional[str] = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: List[ChatCompletionChunkChoice]


class ModelCard(BaseModel):
    id: str
    object: str = "model"
    created: int = 1700000000
    owned_by: str = "google-antigravity"


class ModelListResponse(BaseModel):
    object: str = "list"
    data: List[ModelCard]


# --- Native AGY Models ---

class NativeChatRequest(BaseModel):
    prompt: str = Field(description="Prompt text")
    model: Optional[str] = Field(default=None, description="AGY model")
    conversation_id: Optional[str] = Field(default=None, description="Session ID to continue conversation")
    stream: Optional[bool] = Field(default=False, description="Stream output tokens")
    effort: Optional[str] = Field(default=None, description="Reasoning effort (low, medium, high, xhigh, max)")


class NativeChatResponse(BaseModel):
    response: str
    conversation_id: str
    model: str
    duration_seconds: float
    usage: Dict[str, Any]
    status: str = "SUCCESS"
