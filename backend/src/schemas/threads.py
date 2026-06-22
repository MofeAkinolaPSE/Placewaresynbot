from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any


class ThreadCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(..., max_length=200)
    participants: Optional[List[Dict[str, Any]]] = None
    thread_type: Optional[str] = Field("group", max_length=20)
    channel_key: Optional[str] = Field(None, max_length=100)
    context_type: Optional[str] = Field(None, max_length=50)
    context_id: Optional[str] = Field(None, max_length=64)


class ChannelCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(..., max_length=200)
    channel_key: str = Field(..., max_length=100)
    member_ids: Optional[List[str]] = None
    context_type: Optional[str] = Field(None, max_length=50)
    context_id: Optional[str] = Field(None, max_length=64)


class ThreadMemberCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_id: str = Field(..., max_length=64)
    role: Optional[str] = Field("member", max_length=20)


class PresenceUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: str = Field("online", max_length=20)


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    # 4000 char cap prevents context-flooding attacks on the LLM pipeline
    content: str = Field(..., min_length=1, max_length=4000)
    metadata: Optional[Dict[str, Any]] = None


# --- Response models (extra fields allowed from DB) ---

class Thread(BaseModel):
    id: str
    title: str
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    last_activity_at: Optional[str] = None
    thread_type: Optional[str] = "group"
    channel_key: Optional[str] = None
    context_type: Optional[str] = None
    context_id: Optional[str] = None


class Participant(BaseModel):
    id: str
    thread_id: str
    user_id: str
    role: Optional[str] = None
    joined_at: Optional[str] = None


class Message(BaseModel):
    id: str
    thread_id: str
    sender: Optional[str]
    content: str
    created_at: Optional[str]
    metadata: Optional[Dict[str, Any]]


class ReadMarker(BaseModel):
    model_config = ConfigDict(extra='forbid')
    thread_id: str = Field(..., max_length=64)
    user_id: str = Field(..., max_length=64)
    last_read_message_id: Optional[str] = Field(None, max_length=64)
    last_read_at: Optional[str] = Field(None, max_length=32)


class UnreadSummaryItem(BaseModel):
    thread_id: str
    unread_count: int
    last_message_at: Optional[str] = None


class PresenceItem(BaseModel):
    thread_id: str
    user_id: str
    status: str
    last_seen_at: Optional[str] = None
