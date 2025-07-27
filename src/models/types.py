"""
Pydantic models for type validation
"""
from pydantic import BaseModel
from typing import  Any , Optional
from enum import Enum


class WSEventType(str, Enum):
    """
    WebSocket event types
    """
    SUBSCRIBE = "subscribe"
    NEW_MESSAGE = "new-message"
    MESSAGE_UPDATE = "message-update"
    MESSAGE_DELETE = "message-delete"
    MEMBER_TYPING = "member-typing"
    MEMBER_STOP_TYPING = "member-stop-typing"
    MEMBER_STATUS_UPDATE = "MEMBER_STATUS_UPDATE"


class User(BaseModel):
    """
    User model
    """
    id: str
    name: Optional[str] = None
    email: str
    image: Optional[str] = None


class Member(BaseModel):
    """
    Member model
    """
    id: str
    userId: str
    user: Optional[User] = None


class Message(BaseModel):
    """
    Message model
    """
    id: str
    content: str
    fileUrl: Optional[str] = None
    fileType: Optional[str] = None
    fileName: Optional[str] = None
    memberId: str
    member: Optional[Member] = None
    deleted: bool = False
    edited: bool = False
    createdAt: str
    updatedAt: str


class WebSocketAuthToken(BaseModel):
    """
    JWT token payload structure
    """
    userId: str
    name: Optional[str] = None
    image: Optional[str] = None
    exp: int  # expiration timestamp


class BroadcastMessage(BaseModel):
    """
    Message structure for broadcasting
    """
    id: str
    content: str
    fileUrl: Optional[str] = None
    fileType: Optional[str] = None
    fileName: Optional[str] = None
    memberId: str
    userId: str
    username: str
    userImage: Optional[str] = None
    timestamp: str
    member: dict[str, Any]  # Member object with role and user info


class BroadcastRequest(BaseModel):
    """
    HTTP broadcast request body 
    """
    type: WSEventType
    channelName: str
    message: BroadcastMessage


class TypingUser(BaseModel):
    """
    Typing indicator data structure
    """
    userId: str
    username: str
    timestamp: float  # Unix timestamp for cleanup


class ChannelStats(BaseModel):
    """
    Channel statistics for health endpoint
    """
    name: str
    subscribers: int


class HealthResponse(BaseModel):
    """
    Health check response structure
    """
    status: str
    timestamp: str
    activeConnections: int
    totalConnections: int
    channels: dict[str, Any]