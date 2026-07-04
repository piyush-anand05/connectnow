import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from database import get_db
from auth_utils import get_current_user, now_iso


router = APIRouter(
    prefix="/api",
    tags=["Messages"]
)

MAX_MSG_LEN = 2000


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


class StartConversationIn(BaseModel):
    receiver_user_id: str


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
    message_text: Optional[str]
    is_read: bool
    created_dt: Optional[str]


class MarkReadOut(BaseModel):
    success: bool
    updated_count: int


def generate_conversation_id():
    return "CONV_" + uuid.uuid4().hex[:10].upper()


def generate_message_id():
    return "MSG_" + uuid.uuid4().hex[:10].upper()


def is_blocked(conn, user_a: str, user_b: str):
    row = conn.execute(
        """
        SELECT 1
        FROM user_blocks
        WHERE
            (blocker_user_id = ? AND blocked_user_id = ?)
            OR
            (blocker_user_id = ? AND blocked_user_id = ?)
        """,
        (user_a, user_b, user_b, user_a)
    ).fetchone()

    return row is not None


def has_accepted_connection(conn, user_a: str, user_b: str):
    row = conn.execute(
        """
        SELECT 1
        FROM connections
        WHERE status = 'accepted'
          AND (
                (requester_user_id = ? AND receiver_user_id = ?)
                OR
                (requester_user_id = ? AND receiver_user_id = ?)
              )
        """,
        (user_a, user_b, user_b, user_a)
    ).fetchone()

    return row is not None


def get_participant_info(conn, user_id: str):
    row = conn.execute(
        """
        SELECT
            u.unique_user_id,
            u.name,
            u.city,
            p.can_help_with,
            COALESCE(pr.is_online, 0) AS is_online,
            pr.last_seen_at
        FROM user_reg_info u
        LEFT JOIN user_profile_details p
            ON p.unique_user_id = u.unique_user_id
        LEFT JOIN user_presence pr
            ON pr.unique_user_id = u.unique_user_id
        WHERE u.unique_user_id = ?
        """,
        (user_id,)
    ).fetchone()

    if not row:
        return None

    return {
        "unique_user_id": row["unique_user_id"],
        "name": row["name"],
        "city": row["city"],
        "can_help_with": row["can_help_with"],
        "is_online": bool(row["is_online"]),
        "last_seen_at": row["last_seen_at"]
    }


def find_conversation(conn, user_a: str, user_b: str):
    return conn.execute(
        """
        SELECT *
        FROM conversations
        WHERE
            (user_1_id = ? AND user_2_id = ?)
            OR
            (user_1_id = ? AND user_2_id = ?)
        """,
        (user_a, user_b, user_b, user_a)
    ).fetchone()


def assert_participant(conn, conversation_id: str, user_id: str):
    row = conn.execute(
        """
        SELECT *
        FROM conversations
        WHERE conversation_id = ?
        """,
        (conversation_id,)
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if user_id not in (row["user_1_id"], row["user_2_id"]):
        raise HTTPException(status_code=403, detail="Access denied")

    return row


@router.post("/presence/online", response_model=PresenceOut)
def mark_online(current_user: str = Depends(get_current_user)):
    ts = now_iso()

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO user_presence
            (
                unique_user_id,
                is_online,
                last_seen_at,
                updated_dt
            )
            VALUES (?, 1, ?, ?)
            ON CONFLICT(unique_user_id)
            DO UPDATE SET
                is_online = 1,
                last_seen_at = excluded.last_seen_at,
                updated_dt = excluded.updated_dt
            """,
            (current_user, ts, ts)
        )

    return {
        "success": True,
        "is_online": True,
        "last_seen_at": ts
    }


@router.post("/presence/offline", response_model=PresenceOut)
def mark_offline(current_user: str = Depends(get_current_user)):
    ts = now_iso()

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO user_presence
            (
                unique_user_id,
                is_online,
                last_seen_at,
                updated_dt
            )
            VALUES (?, 0, ?, ?)
            ON CONFLICT(unique_user_id)
            DO UPDATE SET
                is_online = 0,
                last_seen_at = excluded.last_seen_at,
                updated_dt = excluded.updated_dt
            """,
            (current_user, ts, ts)
        )

    return {
        "success": True,
        "is_online": False,
        "last_seen_at": ts
    }


@router.post("/conversations/start", response_model=ConversationOut)
def start_conversation(
    body: StartConversationIn,
    current_user: str = Depends(get_current_user)
):
    receiver = body.receiver_user_id.strip()

    if receiver == current_user:
        raise HTTPException(
            status_code=400,
            detail="Cannot start conversation with yourself"
        )

    with get_db() as conn:
        receiver_exists = conn.execute(
            """
            SELECT 1
            FROM user_reg_info
            WHERE unique_user_id = ?
            """,
            (receiver,)
        ).fetchone()

        if not receiver_exists:
            raise HTTPException(
                status_code=404,
                detail="Receiver user not found"
            )

        if is_blocked(conn, current_user, receiver):
            raise HTTPException(
                status_code=403,
                detail="You cannot message this user"
            )

        if not has_accepted_connection(conn, current_user, receiver):
            raise HTTPException(
                status_code=403,
                detail="You can message only accepted connections"
            )

        existing = find_conversation(conn, current_user, receiver)

        if existing:
            conversation_id = existing["conversation_id"]
        else:
            conversation_id = generate_conversation_id()
            ts = now_iso()

            conn.execute(
                """
                INSERT INTO conversations
                (
                    conversation_id,
                    user_1_id,
                    user_2_id,
                    created_dt,
                    updated_dt,
                    last_message_dt
                )
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (
                    conversation_id,
                    current_user,
                    receiver,
                    ts,
                    ts
                )
            )

        participant = get_participant_info(conn, receiver)

    return {
        "conversation_id": conversation_id,
        "participant": participant
    }


@router.get("/conversations/me", response_model=list[ConversationListItemOut])
def my_conversations(current_user: str = Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                c.*,
                CASE
                    WHEN c.user_1_id = ?
                    THEN c.user_2_id
                    ELSE c.user_1_id
                END AS other_id,

                m.message_text AS last_message_text

            FROM conversations c

            LEFT JOIN messages m
                ON m.message_id = (
                    SELECT message_id
                    FROM messages
                    WHERE conversation_id = c.conversation_id
                      AND is_deleted = 0
                    ORDER BY created_dt DESC
                    LIMIT 1
                )

            WHERE (c.user_1_id = ? OR c.user_2_id = ?)

            ORDER BY COALESCE(c.last_message_dt, c.created_dt) DESC
            """,
            (
                current_user,
                current_user,
                current_user
            )
        ).fetchall()

        result = []

        for row in rows:
            other_id = row["other_id"]

            if is_blocked(conn, current_user, other_id):
                continue

            unread = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM messages
                WHERE conversation_id = ?
                  AND receiver_user_id = ?
                  AND is_read = 0
                  AND is_deleted = 0
                """,
                (
                    row["conversation_id"],
                    current_user
                )
            ).fetchone()["cnt"]

            participant = get_participant_info(conn, other_id)

            result.append({
                "conversation_id": row["conversation_id"],
                "participant": participant,
                "last_message": row["last_message_text"],
                "last_message_at": row["last_message_dt"],
                "unread_count": unread
            })

    return result


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[MessageOut]
)
def get_conversation_messages(
    conversation_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        conv = assert_participant(conn, conversation_id, current_user)

        other_user = (
            conv["user_2_id"]
            if conv["user_1_id"] == current_user
            else conv["user_1_id"]
        )

        if is_blocked(conn, current_user, other_user):
            raise HTTPException(
                status_code=403,
                detail="You cannot view this conversation"
            )

        rows = conn.execute(
            """
            SELECT *
            FROM messages
            WHERE conversation_id = ?
              AND is_deleted = 0
            ORDER BY created_dt ASC
            """,
            (conversation_id,)
        ).fetchall()

    return [
        {
            "message_id": row["message_id"],
            "conversation_id": row["conversation_id"],
            "sender_user_id": row["sender_user_id"],
            "receiver_user_id": row["receiver_user_id"],
            "message_text": row["message_text"],
            "is_read": bool(row["is_read"]),
            "created_dt": row["created_dt"]
        }
        for row in rows
    ]


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageOut
)
def send_message(
    body: SendMessageIn,
    conversation_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    text = body.message_text.strip()

    if not text:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    with get_db() as conn:
        conv = assert_participant(conn, conversation_id, current_user)

        receiver = (
            conv["user_2_id"]
            if conv["user_1_id"] == current_user
            else conv["user_1_id"]
        )

        if is_blocked(conn, current_user, receiver):
            raise HTTPException(
                status_code=403,
                detail="You cannot message this user"
            )

        if not has_accepted_connection(conn, current_user, receiver):
            raise HTTPException(
                status_code=403,
                detail="You can message only accepted connections"
            )

        message_id = generate_message_id()
        ts = now_iso()

        conn.execute(
            """
            INSERT INTO messages
            (
                message_id,
                conversation_id,
                sender_user_id,
                receiver_user_id,
                message_type,
                message_text,
                attachment_url,
                reply_to_message_id,
                is_read,
                is_deleted,
                created_dt,
                updated_dt
            )
            VALUES (?, ?, ?, ?, 'text', ?, NULL, NULL, 0, 0, ?, ?)
            """,
            (
                message_id,
                conversation_id,
                current_user,
                receiver,
                text,
                ts,
                ts
            )
        )

        conn.execute(
            """
            UPDATE conversations
            SET last_message_dt = ?,
                updated_dt = ?
            WHERE conversation_id = ?
            """,
            (
                ts,
                ts,
                conversation_id
            )
        )

    return {
        "message_id": message_id,
        "conversation_id": conversation_id,
        "sender_user_id": current_user,
        "receiver_user_id": receiver,
        "message_text": text,
        "is_read": False,
        "created_dt": ts
    }


@router.put(
    "/conversations/{conversation_id}/read",
    response_model=MarkReadOut
)
def mark_conversation_read(
    conversation_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        conv = assert_participant(conn, conversation_id, current_user)

        other_user = (
            conv["user_2_id"]
            if conv["user_1_id"] == current_user
            else conv["user_1_id"]
        )

        if is_blocked(conn, current_user, other_user):
            raise HTTPException(
                status_code=403,
                detail="You cannot update this conversation"
            )

        cursor = conn.execute(
            """
            UPDATE messages
            SET is_read = 1,
                updated_dt = ?
            WHERE conversation_id = ?
              AND receiver_user_id = ?
              AND is_read = 0
              AND is_deleted = 0
            """,
            (
                now_iso(),
                conversation_id,
                current_user
            )
        )

    return {
        "success": True,
        "updated_count": cursor.rowcount
    }