from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class ThreadCreate(BaseModel):
    title: str
    participants: Optional[List[Dict[str, Any]]] = None


class Thread(BaseModel):
    id: str
    title: str
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    last_activity_at: Optional[str] = None


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
