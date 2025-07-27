
import os
import json
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from datetime import datetime
import jwt
import logging
import traceback

from pydantic import ValidationError

from channel_manager import ChannelManager
from models.types import BroadcastRequest, WSEventType

# Load environment variables from .env file
load_dotenv()

# Get configuration from environment variables
PORT = int(os.getenv("PORT", 3001))  # Default to 3001
WS_JWT_SECRET = os.getenv("WS_JWT_SECRET")
if not WS_JWT_SECRET:
    raise ValueError("WS_JWT_SECRET environment variable is required!")

# Create FastAPI app instance
app = FastAPI(
    title="Channels WebSocket Server",
    description="Python WebSocket server for Discord-like real-time messaging",
    version="1.0.0"
)

# Configure CORS
allowed_origins = [
    "https://channels-livid.vercel.app",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S'
)

logger = logging.getLogger(__name__)

# Connection statistics
total_connections = 0
active_connections = 0

# Create ChannelManager instance
channel_manager = ChannelManager()

@app.on_event("startup")
async def startup_event():
    """
    Start background tasks when the server starts
    """
    logger.info("Starting background tasks...")
    await channel_manager.start_cleanup_task()
    logger.info("Background tasks started successfully")


@app.post("/api/broadcast")
async def broadcast_message(request: Request):
    """
    HTTP endpoint for broadcasting messages - handles different message types
    """
    try:
        # Get the raw request body
        body = await request.json()
        logger.info(f"Raw request body: {body}")

        # Extract basic fields
        event_type = body.get("type")
        channel_name = body.get("channelName")
        message_data = body.get("message", {})

        # Validate required fields
        if not event_type or not channel_name:
            raise HTTPException(status_code=400, detail="Missing type or channelName")

        # Convert string event type to enum
        try:
            ws_event_type = WSEventType(event_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid event type. Must be one of: {[e.value for e in WSEventType]}"
            )

        logger.info(f"Received broadcast request for channel {channel_name}, type: {ws_event_type}")

        # Broadcast the message data directly (no Pydantic validation for typing events)
        await channel_manager.broadcast(
            channel_name,
            ws_event_type,
            message_data  # Send the raw message data for typing events
        )

        logger.info(f"Successfully broadcasted {ws_event_type} to {channel_name}")
        return {"success": True}

    except Exception as e:
        logger.error(f"Unexpected error in broadcast: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to broadcast message")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint - equivalent to your TypeScript WebSocket connection handler
    Handles authentication, subscriptions, and connection management
    """
    global total_connections, active_connections

    user_id = None

    try:
        # Extract JWT token from query parameters (same as TypeScript version)
        token = websocket.query_params.get("token")

        if not token:
            logger.warning("WebSocket connection rejected: No authentication token provided")
            await websocket.close(code=1008, reason="Authentication required")
            return

        # Verify JWT token (equivalent to verify(token, WS_JWT_SECRET) in TypeScript)
        try:
            decoded_token = jwt.decode(token, WS_JWT_SECRET, algorithms=["HS256"])
            user_id = decoded_token.get("userId")
            user_name = decoded_token.get("name")
            user_image = decoded_token.get("image")

            if not user_id:
                raise jwt.InvalidTokenError("Missing userId in token")

        except jwt.InvalidTokenError as e:
            logger.warning(f"WebSocket authentication failed: {e}")
            await websocket.close(code=1008, reason="Invalid authentication token")
            return

        # Accept the WebSocket connection
        await websocket.accept()

        # Update connection statistics (same as TypeScript)
        total_connections += 1
        active_connections += 1

        # Log successful connection (equivalent to your TypeScript logging)
        logger.info(f"New authenticated WebSocket connection established. "
                    f"Total: {total_connections}, Active: {active_connections}, "
                    f"User ID: {user_id}")

        # Keep connection alive and handle messages
        while True:
            try:
                # Wait for messages from client (equivalent to ws.on('message') in TypeScript)
                message_text = await websocket.receive_text()
                logger.debug(f"Received message from user {user_id}: {message_text}")

                # Parse the message
                message_data = {}
                try:
                    message_data = json.loads(message_text)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON message from user {user_id}: {message_text}")
                    continue

                # Handle different message types (equivalent to your TypeScript message handling)
                message_type = message_data.get("type")

                if message_type == "subscribe":
                    # Handle channel subscription (equivalent to your TypeScript subscribe handling)
                    channel_name = message_data.get("channelName")
                    user_info = {
                        "name": user_name,
                        "image": user_image,
                        "userId": user_id
                    }

                    if channel_name:
                        logger.info(f"User {user_id} subscribing to channel {channel_name}")
                        await channel_manager.subscribe(channel_name, websocket, user_id, user_info)
                    else:
                        logger.warning(f"Subscribe request missing channelName from user {user_id}")

                elif message_type == "typing":
                    # Handle typing indicators (you can implement this later)
                    channel_name = message_data.get("channelName")
                    is_typing = message_data.get("isTyping", True)
                    username = user_name or "Anonymous"
                    if channel_name:
                        logger.debug(f"User {user_id} typing in {channel_name}: {is_typing}")
                        await channel_manager.handle_typing(channel_name, user_id, username, is_typing)
                    else:
                        logger.warning(f"Typing request missing channelName from user {user_id}")
                else:
                    logger.warning(f"Unknown message type '{message_type}' from user {user_id}")

            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected for user {user_id}")
                break
            except Exception as e:
                logger.error(f"Error processing WebSocket message from user {user_id}: {e}")
                break

    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
        try:
            await websocket.close(code=1011, reason="Internal server error")
        except:
            pass

    finally:
        # Connection cleanup (equivalent to ws.on('close') in TypeScript)
        if user_id:
            active_connections -= 1
            logger.info(f"WebSocket connection closed for user {user_id}. Active connections: {active_connections}")

            # Remove user from all channel subscriptions
            await channel_manager.handle_websocket_closure(websocket)






@app.get("/health")
@app.head("/health")
async def health_check():
    """
    Health check endpoint
    Returns server status and connection statistics
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "activeConnections": active_connections,
        "totalConnections": total_connections,
        "channels": channel_manager.get_channel_stats(),  # Use real stats!
    }


@app.get("/")
async def root():
    """
    Root endpoint for basic server confirmation
    """
    return {"message": "Channels WebSocket Server Running", "version": "1.0.0"}




if __name__ == "__main__":
    import uvicorn

    logger.info(f"Starting server on port {PORT}")

    # Start the server (equivalent to server.listen() in TypeScript)
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        reload=True,  # Auto-reload on code changes (like nodemon)
        log_level="info"
    )