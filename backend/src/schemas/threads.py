from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class ThreadCreate(BaseModel):
    title: str
    participants: Optional[List[Dict[str, Any]]] = None
    thread_type: Optional[str] = "group"
    channel_key: Optional[str] = None
    context_type: Optional[str] = None
    context_id: Optional[str] = None


class ChannelCreate(BaseModel):
    title: str
    channel_key: str
    member_ids: Optional[List[str]] = None
    context_type: Optional[str] = None
    context_id: Optional[str] = None


class ThreadMemberCreate(BaseModel):
    user_id: str
    role: Optional[str] = "member"


class PresenceUpdate(BaseModel):
    status: str = "online"


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


class MessageCreate(BaseModel):
    content: str
    metadata: Optional[Dict[str, Any]] = None


class Message(BaseModel):
    id: str
    thread_id: str
    sender: Optional[str]
    content: str
    created_at: Optional[str]
    metadata: Optional[Dict[str, Any]]


class ReadMarker(BaseModel):
    thread_id: str
    user_id: str
    last_read_message_id: Optional[str] = None
    last_read_at: Optional[str] = None


class UnreadSummaryItem(BaseModel):
    thread_id: str
    unread_count: int
    last_message_at: Optional[str] = None


class PresenceItem(BaseModel):
    thread_id: str
    user_id: str
    status: str
    last_seen_at: Optional[str] = None
