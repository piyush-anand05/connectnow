import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Path, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ──────────────────────────────────────────────
# READ DB PATH FROM table_path.txt
# ──────────────────────────────────────────────
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
PATH_FILE = os.path.join(BASE_DIR, "table_path.txt")

if not os.path.exists(PATH_FILE):
    raise RuntimeError(
        f"\n[ERROR] table_path.txt not found at: {PATH_FILE}\n"
        "Create it and put the full path to your .db file inside.\n"
        "Example:  C:\\Users\\amitu\\Documents\\connect_now_apis\\connectnow.db"
    )

with open(PATH_FILE, "r", encoding="utf-8-sig") as f:
    DB_PATH = f.read().strip()

if not DB_PATH:
    raise RuntimeError("[ERROR] table_path.txt is empty. Add your DB file path inside it.")

print(f"[DB] Reading database from: {DB_PATH}")

# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────
SECRET_KEY  = os.environ.get("JWT_SECRET", "dev-secret-change-in-prod")
MAX_MSG_LEN = 2000


# ──────────────────────────────────────────────
# APP
# ──────────────────────────────────────────────
app = FastAPI(
    title="ConnectNow Messaging API",
    description="Local opportunity network — messaging module.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # tighten to your UI domain in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
# DATABASE
# ──────────────────────────────────────────────
@contextmanager
def get_db():
    """Opens a SQLite connection to the path in table_path.txt.
    Auto-commits on success, rolls back on error, always closes."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ──────────────────────────────────────────────
# UTILITIES
# ──────────────────────────────────────────────
def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _get_participant_info(conn, user_id: str) -> Optional[dict]:
    row = conn.execute("""
        SELECT u.unique_user_id, u.name, u.city, u.can_help_with,
               COALESCE(p.is_online, 0) AS is_online,
               p.last_seen_at
        FROM   users u
        LEFT JOIN user_presence p ON p.unique_user_id = u.unique_user_id
        WHERE  u.unique_user_id = ?
    """, (user_id,)).fetchone()
    if not row:
        return None
    return {
        "unique_user_id": row["unique_user_id"],
        "name":           row["name"],
        "city":           row["city"],
        "can_help_with":  row["can_help_with"],
        "is_online":      bool(row["is_online"]),
        "last_seen_at":   row["last_seen_at"],
    }


def _find_conversation(conn, uid_a: str, uid_b: str):
    return conn.execute("""
        SELECT * FROM conversations
        WHERE (user_1_id = ? AND user_2_id = ?)
           OR (user_1_id = ? AND user_2_id = ?)
    """, (uid_a, uid_b, uid_b, uid_a)).fetchone()


def _assert_participant(conn, conv_id: str, user_id: str):
    """Returns conversation row; raises 404/403 if not accessible."""
    row = conn.execute(
        "SELECT * FROM conversations WHERE conversation_id = ?", (conv_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if user_id not in (row["user_1_id"], row["user_2_id"]):
        raise HTTPException(status_code=403, detail="Access denied: not a participant")
    return row


# ──────────────────────────────────────────────
# AUTH DEPENDENCY
# ──────────────────────────────────────────────
def get_current_user(authorization: str = Header(...)) -> str:
    """Extracts and validates JWT. Returns unique_user_id."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be 'Bearer <token>'",
        )
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

    uid = payload.get("unique_user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Token missing unique_user_id claim")
    return uid


# ──────────────────────────────────────────────
# PYDANTIC SCHEMAS
# ──────────────────────────────────────────────
class ParticipantOut(BaseModel):
    unique_user_id: str
    name: str
    city: Optional[str]
    can_help_with: Optional[str]
    is_online: bool
    last_seen_at: Optional[str]

class PresenceOut(BaseModel):
    success: bool
    is_online: bool
    last_seen_at: Optional[str]

class PresenceStatusOut(BaseModel):
    unique_user_id: str
    is_online: bool
    last_seen_at: Optional[str]

class StartConversationIn(BaseModel):
    receiver_user_id: str = Field(..., description="unique_user_id of the other person")

class ConversationOut(BaseModel):
    conversation_id: str
    participant: ParticipantOut

class ConversationListItemOut(BaseModel):
    conversation_id: str
    participant: ParticipantOut
    last_message: Optional[str]
    last_message_at: Optional[str]
    unread_count: int

class SendMessageIn(BaseModel):
    message_text: str = Field(..., min_length=1, max_length=MAX_MSG_LEN)

class MessageOut(BaseModel):
    message_id: str
    conversation_id: str
    sender_user_id: str
    receiver_user_id: str
    message_text: str
    is_read: bool
    created_at: str

class MarkReadOut(BaseModel):
    success: bool
    updated_count: int

class HealthOut(BaseModel):
    status: str
    service: str
    db_path: str


# ──────────────────────────────────────────────
# DEMO TOKEN  (dev only — remove in production)
# ──────────────────────────────────────────────
@app.get("/api/auth/demo-token", tags=["Auth (dev only)"],
         summary="Generate a JWT for testing")
def demo_token(user: str):
    """
    **DEVELOPMENT ONLY** — pass `?user=USR_123` to get a JWT for that user.
    The user must already exist in your `users` table.
    Remove this endpoint before going live.
    """
    with get_db() as conn:
        exists = conn.execute(
            "SELECT 1 FROM users WHERE unique_user_id = ?", (user,)
        ).fetchone()
    if not exists:
        raise HTTPException(
            status_code=404,
            detail=f"User '{user}' not found. Insert them into the users table first."
        )
    token = jwt.encode({"unique_user_id": user}, SECRET_KEY, algorithm="HS256")
    return {"token": token, "user": user}


# ──────────────────────────────────────────────
# HEALTH
# ──────────────────────────────────────────────
@app.get("/api/health", response_model=HealthOut, tags=["Health"])
def health():
    """Confirms the API is running and shows which DB file is in use."""
    return {"status": "ok", "service": "ConnectNow Messaging", "db_path": DB_PATH}


# ──────────────────────────────────────────────
# PRESENCE APIS
# ──────────────────────────────────────────────

@app.post("/api/presence/online", response_model=PresenceOut,
          tags=["Presence"], summary="Mark current user as online")
def presence_online(current_user: str = Depends(get_current_user)):
    """Called when user opens the app or logs in."""
    ts = now_iso()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO user_presence (unique_user_id, is_online, last_seen_at, updated_at)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(unique_user_id) DO UPDATE SET
                is_online    = 1,
                last_seen_at = excluded.last_seen_at,
                updated_at   = excluded.updated_at
        """, (current_user, ts, ts))
    return {"success": True, "is_online": True, "last_seen_at": ts}


@app.post("/api/presence/offline", response_model=PresenceOut,
          tags=["Presence"], summary="Mark current user as offline")
def presence_offline(current_user: str = Depends(get_current_user)):
    """Called when user logs out."""
    ts = now_iso()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO user_presence (unique_user_id, is_online, last_seen_at, updated_at)
            VALUES (?, 0, ?, ?)
            ON CONFLICT(unique_user_id) DO UPDATE SET
                is_online    = 0,
                last_seen_at = excluded.last_seen_at,
                updated_at   = excluded.updated_at
        """, (current_user, ts, ts))
    return {"success": True, "is_online": False, "last_seen_at": ts}


@app.get("/api/presence/{unique_user_id}", response_model=PresenceStatusOut,
         tags=["Presence"], summary="Get online status of any user")
def get_presence(
    unique_user_id: str = Path(...),
    current_user: str = Depends(get_current_user),
):
    with get_db() as conn:
        row = conn.execute(
            "SELECT is_online, last_seen_at FROM user_presence WHERE unique_user_id = ?",
            (unique_user_id,),
        ).fetchone()
    if not row:
        return {"unique_user_id": unique_user_id, "is_online": False, "last_seen_at": None}
    return {
        "unique_user_id": unique_user_id,
        "is_online":      bool(row["is_online"]),
        "last_seen_at":   row["last_seen_at"],
    }


# ──────────────────────────────────────────────
# CONVERSATION APIS
# ──────────────────────────────────────────────

@app.post("/api/conversations/start", response_model=ConversationOut,
          tags=["Conversations"], summary="Start or fetch a conversation")
def start_conversation(
    body: StartConversationIn,
    current_user: str = Depends(get_current_user),
):
    receiver = body.receiver_user_id.strip()
    if not receiver:
        raise HTTPException(status_code=400, detail="receiver_user_id is required")
    if receiver == current_user:
        raise HTTPException(status_code=400, detail="Cannot start a conversation with yourself")

    with get_db() as conn:
        if not conn.execute(
            "SELECT 1 FROM users WHERE unique_user_id = ?", (receiver,)
        ).fetchone():
            raise HTTPException(status_code=404, detail="Receiver user not found")

        existing = _find_conversation(conn, current_user, receiver)
        if existing:
            conv_id = existing["conversation_id"]
        else:
            conv_id = "CONV_" + uuid.uuid4().hex[:8].upper()
            ts = now_iso()
            conn.execute("""
                INSERT INTO conversations
                    (conversation_id, user_1_id, user_2_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (conv_id, current_user, receiver, ts, ts))

        participant = _get_participant_info(conn, receiver)

    return {"conversation_id": conv_id, "participant": participant}


@app.get("/api/conversations/me", response_model=list[ConversationListItemOut],
         tags=["Conversations"], summary="Get all conversations for current user")
def list_conversations(current_user: str = Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute("""
            SELECT c.*,
                   CASE WHEN c.user_1_id = ? THEN c.user_2_id ELSE c.user_1_id END AS other_id,
                   m.message_text AS last_msg_text
            FROM   conversations c
            LEFT JOIN messages m ON m.message_id = (
                SELECT message_id FROM messages
                WHERE  conversation_id = c.conversation_id
                ORDER  BY created_at DESC LIMIT 1
            )
            WHERE  c.user_1_id = ? OR c.user_2_id = ?
            ORDER  BY COALESCE(c.last_message_at, c.created_at) DESC
        """, (current_user, current_user, current_user)).fetchall()

        result = []
        for r in rows:
            other_id = r["other_id"]
            unread = conn.execute("""
                SELECT COUNT(*) AS cnt FROM messages
                WHERE  conversation_id  = ?
                  AND  receiver_user_id = ?
                  AND  is_read          = 0
            """, (r["conversation_id"], current_user)).fetchone()["cnt"]

            participant = _get_participant_info(conn, other_id)
            result.append({
                "conversation_id": r["conversation_id"],
                "participant":     participant,
                "last_message":    r["last_msg_text"],
                "last_message_at": r["last_message_at"],
                "unread_count":    unread,
            })

    return result


# ──────────────────────────────────────────────
# MESSAGE APIS
# ──────────────────────────────────────────────

@app.get("/api/conversations/{conversation_id}/messages",
         response_model=list[MessageOut], tags=["Messages"],
         summary="Get all messages in a conversation")
def get_messages(
    conversation_id: str = Path(...),
    current_user: str = Depends(get_current_user),
):
    with get_db() as conn:
        _assert_participant(conn, conversation_id, current_user)
        msgs = conn.execute("""
            SELECT * FROM messages
            WHERE  conversation_id = ?
            ORDER  BY created_at ASC
        """, (conversation_id,)).fetchall()

    return [{
        "message_id":       m["message_id"],
        "conversation_id":  m["conversation_id"],
        "sender_user_id":   m["sender_user_id"],
        "receiver_user_id": m["receiver_user_id"],
        "message_text":     m["message_text"],
        "is_read":          bool(m["is_read"]),
        "created_at":       m["created_at"],
    } for m in msgs]


@app.post("/api/conversations/{conversation_id}/messages",
          response_model=MessageOut, status_code=201, tags=["Messages"],
          summary="Send a message in a conversation")
def send_message(
    body: SendMessageIn,
    conversation_id: str = Path(...),
    current_user: str = Depends(get_current_user),
):
    text = body.message_text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message_text cannot be empty")

    with get_db() as conn:
        conv     = _assert_participant(conn, conversation_id, current_user)
        receiver = conv["user_2_id"] if conv["user_1_id"] == current_user else conv["user_1_id"]
        msg_id   = "MSG_" + uuid.uuid4().hex[:8].upper()
        ts       = now_iso()

        conn.execute("""
            INSERT INTO messages
                (message_id, conversation_id, sender_user_id, receiver_user_id,
                 message_text, is_read, created_at)
            VALUES (?, ?, ?, ?, ?, 0, ?)
        """, (msg_id, conversation_id, current_user, receiver, text, ts))

        conn.execute("""
            UPDATE conversations
            SET last_message_at = ?, updated_at = ?
            WHERE conversation_id = ?
        """, (ts, ts, conversation_id))

    return {
        "message_id":       msg_id,
        "conversation_id":  conversation_id,
        "sender_user_id":   current_user,
        "receiver_user_id": receiver,
        "message_text":     text,
        "is_read":          False,
        "created_at":       ts,
    }


@app.put("/api/conversations/{conversation_id}/read",
         response_model=MarkReadOut, tags=["Messages"],
         summary="Mark all unread messages as read")
def mark_read(
    conversation_id: str = Path(...),
    current_user: str = Depends(get_current_user),
):
    with get_db() as conn:
        _assert_participant(conn, conversation_id, current_user)
        cursor = conn.execute("""
            UPDATE messages
            SET    is_read = 1
            WHERE  conversation_id  = ?
              AND  receiver_user_id = ?
              AND  is_read          = 0
        """, (conversation_id, current_user))

    return {"success": True, "updated_count": cursor.rowcount}
