"""
Handles WebSocket connections, channel subscriptions, and message broadcasting
"""
import asyncio
import json
import logging
import time
from typing import Any, Optional
from fastapi import WebSocket
from models.types import WSEventType, TypingUser

logger = logging.getLogger(__name__)


class ChannelSubscription:
    """
    Represents a single WebSocket subscription to a channel
    Equivalent to your TypeScript ChannelSubscription interface
    """

    def __init__(self, websocket: WebSocket, user_id: str, user_info: dict[str, Any]):
        self.websocket = websocket
        self.user_id = user_id
        self.user_info = user_info


class ChannelManager:
    """
    Manages all real-time communication for the chat application

    Responsibilities:
    - Channel subscription management
    - Real-time message broadcasting
    - Typing indicator handling
    - Online status tracking
    - Connection cleanup
    """

    def __init__(self):
        # Channel subscriptions: channel_name -> Set of ChannelSubscription
        self.channels: dict[str, set[ChannelSubscription]] = {}

        # WebSocket to channels mapping for cleanup
        self.ws_to_channels: dict[WebSocket, set[str]] = {}

        # Typing indicators: channel_name -> user_id -> TypingUser
        self.typing_users: dict[str, dict[str, TypingUser]] = {}

        # WebSocket to user ID mapping
        self.ws_to_user: dict[WebSocket, str] = {}

        # Online users: server_id -> set of user_ids
        self.online_users: dict[str, set[str]] = {}

        # Start background tasks
        self._start_typing_cleanup()

        logger.info("ChannelManager initialized")

    def _start_typing_cleanup(self):
        """
        Prepares the cleanup task but doesn't start it yet
        We'll start it when the event loop is running
        """
        self._cleanup_task = None  # Store task reference
        logger.info("ChannelManager typing cleanup prepared (will start with event loop)")

    async def start_cleanup_task(self):
        """
        Actually starts the cleanup task when event loop is running
        Call this after the server starts
        """
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._typing_cleanup_loop())
            logger.info("ChannelManager typing cleanup task started")

    async def _typing_cleanup_loop(self):
        """
        Background task loop for cleaning up stale typing indicators
        """
        TYPING_TIMEOUT = 3.0  # 3 seconds (same as TypeScript)

        while True:
            try:
                await asyncio.sleep(1)  # Check every second
                current_time = time.time()

                # Clean up stale typing indicators
                channels_to_remove = []
                for channel_name, typing_map in self.typing_users.items():
                    users_to_remove = []

                    for user_id, typing_user in typing_map.items():
                        if current_time - typing_user.timestamp > TYPING_TIMEOUT:
                            users_to_remove.append(user_id)

                            # Broadcast stop typing
                            await self.broadcast(
                                channel_name,
                                WSEventType.MEMBER_STOP_TYPING,
                                {
                                    "userId": user_id,
                                    "username": typing_user.username,
                                    "remainingTypingUsers": [
                                        u.model_dump() for u in typing_map.values()
                                        if u.userId != user_id
                                    ]
                                }
                            )

                    # Remove stale users
                    for user_id in users_to_remove:
                        del typing_map[user_id]

                    # Mark empty channels for removal
                    if not typing_map:
                        channels_to_remove.append(channel_name)

                # Remove empty typing channels
                for channel_name in channels_to_remove:
                    del self.typing_users[channel_name]

            except Exception as e:
                logger.error(f"Error in typing cleanup loop: {e}")
                await asyncio.sleep(5)  # Wait before retrying

    async def subscribe(self, channel_name: str, websocket: WebSocket, user_id: str, user_info: dict[str, Any]):
        """
        Adds a WebSocket subscription to a channel
        Equivalent to your TypeScript subscribe method

        Args:
            channel_name: Channel to subscribe to
            websocket: WebSocket connection
            user_id: User ID from JWT token
            user_info: Additional user information
        """
        # Create subscription
        subscription = ChannelSubscription(websocket, user_id, user_info)

        # Initialize channel if it doesn't exist
        if channel_name not in self.channels:
            self.channels[channel_name] = set()

        # Check for duplicate subscription
        channel = self.channels[channel_name]
        existing_sub = None
        for sub in channel:
            if sub.websocket == websocket and sub.user_id == user_id:
                existing_sub = sub
                break

        if existing_sub:
            logger.debug(f"Skipping duplicate subscription for channel {channel_name}, user {user_id}")
            return

        # Add subscription
        channel.add(subscription)

        # Update WebSocket mappings
        self.ws_to_user[websocket] = user_id
        if websocket not in self.ws_to_channels:
            self.ws_to_channels[websocket] = set()
        self.ws_to_channels[websocket].add(channel_name)

        # Update online status
        await self._update_online_status(channel_name, user_id, True)

        logger.info(f"New subscription added to {channel_name}. Subscribers: {len(channel)}")

    async def unsubscribe(self, channel_name: str, websocket: WebSocket):
        """
        Removes a WebSocket subscription from a channel
        Equivalent to your TypeScript unsubscribe method
        """
        try:
            channel = self.channels.get(channel_name)
            if not channel:
                logger.warning(f"Attempted to unsubscribe from non-existent channel: {channel_name}")
                return

            # Find and remove subscription
            unsubscribed_user = None
            sub_to_remove = None
            for sub in channel:
                if sub.websocket == websocket:
                    unsubscribed_user = sub.user_id
                    sub_to_remove = sub
                    break

            if sub_to_remove:
                channel.remove(sub_to_remove)

            # Update WebSocket mappings
            if websocket in self.ws_to_channels:
                self.ws_to_channels[websocket].discard(channel_name)
                if not self.ws_to_channels[websocket]:
                    del self.ws_to_channels[websocket]
                    self.ws_to_user.pop(websocket, None)

            if unsubscribed_user:
                logger.info(f"Client unsubscribed from {channel_name}. "
                            f"User: {unsubscribed_user}, Remaining: {len(channel)}")

            # Remove empty channel
            if not channel:
                del self.channels[channel_name]
                logger.debug(f"Removed empty channel: {channel_name}")

        except Exception as e:
            logger.error(f"Failed to unsubscribe from channel {channel_name}: {e}")

    async def handle_websocket_closure(self, websocket: WebSocket):
        """
        Handles WebSocket connection closure and cleanup
        Equivalent to your TypeScript handleWebSocketClosure method
        """
        subscribed_channels = self.ws_to_channels.get(websocket, set())
        user_id = self.ws_to_user.get(websocket)

        if subscribed_channels and user_id:
            # Clean up each channel subscription
            for channel_name in list(subscribed_channels):
                # Update online status
                await self._update_online_status(channel_name, user_id, False)

                # Remove typing indicators
                typing_map = self.typing_users.get(channel_name, {})
                if user_id in typing_map:
                    typing_user = typing_map[user_id]
                    del typing_map[user_id]

                    await self.broadcast(
                        channel_name,
                        WSEventType.MEMBER_STOP_TYPING,
                        {
                            "userId": user_id,
                            "username": typing_user.username,
                            "remainingTypingUsers": [u.model_dump() for u in typing_map.values()]
                        }
                    )

                # Unsubscribe from channel
                await self.unsubscribe(channel_name, websocket)

            # Clean up WebSocket mappings
            self.ws_to_channels.pop(websocket, None)
            self.ws_to_user.pop(websocket, None)

            logger.info(f"Cleaned up disconnected user {user_id} from {len(subscribed_channels)} channels")

    async def broadcast(self, channel_name: str, event: WSEventType, data: Any, exclude_ws: Optional[WebSocket] = None):
        """
        Broadcasts a message to all subscribers in a channel
        Equivalent to your TypeScript broadcast method

        Args:
            channel_name: Channel to broadcast to
            event: Event type
            data: Message data
            exclude_ws: Optional WebSocket to exclude from broadcast
        """
        try:
            channel = self.channels.get(channel_name)
            if not channel:
                logger.warning(f"Attempted to broadcast to non-existent channel: {channel_name}")
                return

            # Create message
            message = json.dumps({
                "event": event.value,
                "data": data
            })

            # Send to all subscribers
            sent_count = 0
            excluded_count = 0
            closed_count = 0

            for subscription in channel:
                if subscription.websocket == exclude_ws:
                    excluded_count += 1
                elif subscription.websocket.client_state.value == 1:  # WebSocket.OPEN
                    try:
                        await subscription.websocket.send_text(message)
                        sent_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to send message to subscriber: {e}")
                        closed_count += 1
                else:
                    closed_count += 1

            logger.debug(f"Message broadcast complete for {channel_name}. "
                         f"Event: {event.value}, Sent: {sent_count}, "
                         f"Excluded: {excluded_count}, Closed: {closed_count}")

        except Exception as e:
            logger.error(f"Failed to broadcast message to channel {channel_name}: {e}")

    async def handle_typing(self, channel_name: str, user_id: str, username: str, is_typing: bool):
        """
        Manages user typing status and broadcasts updates to channel members
        Equivalent to your TypeScript handleTyping method
        """
        logger.debug(f"Handling typing event: {channel_name}, {user_id}, {username}, {is_typing}")

        if channel_name not in self.typing_users:
            self.typing_users[channel_name] = {}

        channel_typing = self.typing_users[channel_name]

        if is_typing:
            # User started typing
            channel_typing[user_id] = TypingUser(
                userId=user_id,
                username=username,
                timestamp=time.time()
            )

            # Broadcast typing status with all currently typing users
            await self.broadcast(
                channel_name,
                WSEventType.MEMBER_TYPING,
                {
                    "typingUsers": [u.model_dump() for u in channel_typing.values()]
                }
            )
        else:
            # User stopped typing
            if user_id in channel_typing:
                del channel_typing[user_id]

            # Broadcast stop typing with updated list
            await self.broadcast(
                channel_name,
                WSEventType.MEMBER_STOP_TYPING,
                {
                    "userId": user_id,
                    "username": username,
                    "remainingTypingUsers": [u.model_dump() for u in channel_typing.values()]
                }
            )

        logger.debug(f"Typing users in {channel_name}: {len(channel_typing)}")
    async def _update_online_status(self, server_id: str, user_id: str, is_online: bool):
        """
        Updates and broadcasts user online status
        Equivalent to your TypeScript updateOnlineStatus method
        """
        if server_id not in self.online_users:
            self.online_users[server_id] = set()

        server_users = self.online_users[server_id]

        if is_online:
            server_users.add(user_id)
        else:
            server_users.discard(user_id)

        # Broadcast status update
        await self.broadcast(
            server_id,
            WSEventType.MEMBER_STATUS_UPDATE,
            {
                "userId": user_id,
                "isOnline": is_online,
                "onlineUsers": list(server_users)
            }
        )

        logger.debug(f"Updated online status for {user_id} in {server_id}: {is_online}")

    def get_channel_stats(self) -> dict[str, Any]:
        """
        Returns channel statistics for monitoring
        Equivalent to your TypeScript getChannelStats method
        """
        stats = {
            "totalChannels": len(self.channels),
            "channels": [
                {"name": name, "subscribers": len(subs)}
                for name, subs in self.channels.items()
            ]
        }
        logger.debug(f"Channel statistics: {stats}")
        return stats