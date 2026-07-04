import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from database import get_db
from auth_utils import get_current_user, now_iso


router = APIRouter(
    prefix="/api/post-chat",
    tags=["Post Private Replies"]
)


MAX_REPLY_LEN = 2000


class StartPostChatIn(BaseModel):
    post_id: str
    message_text: str = Field(..., min_length=1, max_length=MAX_REPLY_LEN)


class SendPostMessageIn(BaseModel):
    message_text: str = Field(..., min_length=1, max_length=MAX_REPLY_LEN)


class ThreadOut(BaseModel):
    thread_id: str
    post_id: str
    post_title: Optional[str]
    post_status: Optional[str]
    post_owner_id: str
    sender_user_id: str
    other_user_id: str
    other_user_name: Optional[str]
    status: str
    last_message: Optional[str]
    last_message_dt: Optional[str]
    unread_count: int
    created_dt: Optional[str]
    updated_dt: Optional[str]


class MessageOut(BaseModel):
    message_id: str
    thread_id: str
    sender_user_id: str
    receiver_user_id: str
    message_text: str
    is_read: bool
    created_dt: str


class StartPostChatOut(BaseModel):
    thread_id: str
    message: str


class MarkReadOut(BaseModel):
    success: bool
    updated_count: int


def generate_thread_id():
    return "PTHREAD_" + uuid.uuid4().hex[:10].upper()


def generate_message_id():
    return "PMSG_" + uuid.uuid4().hex[:10].upper()


def get_user_name(conn, user_id: str):
    row = conn.execute(
        """
        SELECT name
        FROM user_reg_info
        WHERE unique_user_id = ?
        """,
        (user_id,)
    ).fetchone()

    return row["name"] if row else "ConnectNow User"


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


def generate_notification_id():
    return "NOTIF_" + uuid.uuid4().hex[:10].upper()


def create_notification(
    conn,
    unique_user_id: str,
    title: str,
    message: str,
    notification_type: str,
    reference_id: Optional[str] = None
):
    notification_id = generate_notification_id()
    ts = now_iso()

    conn.execute(
        """
        INSERT INTO notifications
        (
            notification_id,
            unique_user_id,
            title,
            message,
            notification_type,
            reference_id,
            is_read,
            created_dt
        )
        VALUES (?, ?, ?, ?, ?, ?, 0, ?)
        """,
        (
            notification_id,
            unique_user_id,
            title,
            message,
            notification_type,
            reference_id,
            ts
        )
    )


def get_thread_for_post_and_sender(conn, post_id: str, sender_user_id: str):
    return conn.execute(
        """
        SELECT *
        FROM post_private_threads
        WHERE post_id = ?
          AND sender_user_id = ?
        """,
        (
            post_id,
            sender_user_id
        )
    ).fetchone()


def assert_thread_access(conn, thread_id: str, current_user: str):
    row = conn.execute(
        """
        SELECT *
        FROM post_private_threads
        WHERE thread_id = ?
        """,
        (thread_id,)
    ).fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Thread not found"
        )

    if current_user not in (
        row["post_owner_id"],
        row["sender_user_id"]
    ):
        raise HTTPException(
            status_code=403,
            detail="Access denied"
        )

    return row


@router.post("/start", response_model=StartPostChatOut)
def start_post_chat(
    body: StartPostChatIn,
    current_user: str = Depends(get_current_user)
):
    text = body.message_text.strip()

    if not text:
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty"
        )

    ts = now_iso()

    with get_db() as conn:
        post = conn.execute(
            """
            SELECT *
            FROM community_posts
            WHERE post_id = ?
              AND status = 'active'
            """,
            (body.post_id,)
        ).fetchone()

        if not post:
            raise HTTPException(
                status_code=404,
                detail="Post not found"
            )

        post_owner_id = post["unique_user_id"]

        if post_owner_id == current_user:
            raise HTTPException(
                status_code=400,
                detail="You cannot privately reply to your own post"
            )

        if not post["allow_private_replies"]:
            raise HTTPException(
                status_code=403,
                detail="Private replies are disabled for this post"
            )

        if is_blocked(conn, current_user, post_owner_id):
            raise HTTPException(
                status_code=403,
                detail="You cannot reply to this post"
            )

        thread = get_thread_for_post_and_sender(
            conn,
            body.post_id,
            current_user
        )

        if thread:
            thread_id = thread["thread_id"]
        else:
            thread_id = generate_thread_id()

            conn.execute(
                """
                INSERT INTO post_private_threads
                (
                    thread_id,
                    post_id,
                    post_owner_id,
                    sender_user_id,
                    status,
                    created_dt,
                    updated_dt,
                    last_message_dt
                )
                VALUES (?, ?, ?, ?, 'active', ?, ?, NULL)
                """,
                (
                    thread_id,
                    body.post_id,
                    post_owner_id,
                    current_user,
                    ts,
                    ts
                )
            )

        message_id = generate_message_id()

        conn.execute(
            """
            INSERT INTO post_private_messages
            (
                message_id,
                thread_id,
                sender_user_id,
                receiver_user_id,
                message_text,
                is_read,
                is_deleted,
                created_dt,
                updated_dt
            )
            VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?)
            """,
            (
                message_id,
                thread_id,
                current_user,
                post_owner_id,
                text,
                ts,
                ts
            )
        )

        conn.execute(
            """
            UPDATE post_private_threads
            SET updated_dt = ?,
                last_message_dt = ?
            WHERE thread_id = ?
            """,
            (
                ts,
                ts,
                thread_id
            )
        )

        sender_name = get_user_name(conn, current_user)

        create_notification(
            conn=conn,
            unique_user_id=post_owner_id,
            title="New private reply",
            message=f"{sender_name} replied privately to your post: {post['title']}",
            notification_type="post_private_reply",
            reference_id=thread_id
        )

    return {
        "thread_id": thread_id,
        "message": "Private reply sent"
    }


@router.get("/threads", response_model=list[ThreadOut])
def get_my_post_threads(
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                t.*,
                p.title AS post_title,
                p.status AS post_status,

                CASE
                    WHEN t.post_owner_id = ?
                    THEN t.sender_user_id
                    ELSE t.post_owner_id
                END AS other_user_id,

                u.name AS other_user_name,

                (
                    SELECT message_text
                    FROM post_private_messages m
                    WHERE m.thread_id = t.thread_id
                      AND m.is_deleted = 0
                    ORDER BY m.created_dt DESC
                    LIMIT 1
                ) AS last_message,

                (
                    SELECT COUNT(*)
                    FROM post_private_messages m
                    WHERE m.thread_id = t.thread_id
                      AND m.receiver_user_id = ?
                      AND m.is_read = 0
                      AND m.is_deleted = 0
                ) AS unread_count

            FROM post_private_threads t

            LEFT JOIN community_posts p
                ON p.post_id = t.post_id

            LEFT JOIN user_reg_info u
                ON u.unique_user_id =
                    CASE
                        WHEN t.post_owner_id = ?
                        THEN t.sender_user_id
                        ELSE t.post_owner_id
                    END

            WHERE t.post_owner_id = ?
               OR t.sender_user_id = ?

            ORDER BY COALESCE(t.last_message_dt, t.created_dt) DESC
            """,
            (
                current_user,
                current_user,
                current_user,
                current_user,
                current_user
            )
        ).fetchall()

        result = []

        for row in rows:
            if is_blocked(conn, current_user, row["other_user_id"]):
                continue

            result.append({
                "thread_id": row["thread_id"],
                "post_id": row["post_id"],
                "post_title": row["post_title"],
                "post_status": row["post_status"],
                "post_owner_id": row["post_owner_id"],
                "sender_user_id": row["sender_user_id"],
                "other_user_id": row["other_user_id"],
                "other_user_name": row["other_user_name"],
                "status": row["status"],
                "last_message": row["last_message"],
                "last_message_dt": row["last_message_dt"],
                "unread_count": row["unread_count"],
                "created_dt": row["created_dt"],
                "updated_dt": row["updated_dt"]
            })

    return result


@router.get("/thread/{thread_id}", response_model=list[MessageOut])
def get_thread_messages(
    thread_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        thread = assert_thread_access(
            conn,
            thread_id,
            current_user
        )

        other_user_id = (
            thread["sender_user_id"]
            if current_user == thread["post_owner_id"]
            else thread["post_owner_id"]
        )

        if is_blocked(conn, current_user, other_user_id):
            raise HTTPException(
                status_code=403,
                detail="This conversation is not available"
            )

        rows = conn.execute(
            """
            SELECT *
            FROM post_private_messages
            WHERE thread_id = ?
              AND is_deleted = 0
            ORDER BY created_dt ASC
            """,
            (thread_id,)
        ).fetchall()

    return [
        {
            "message_id": row["message_id"],
            "thread_id": row["thread_id"],
            "sender_user_id": row["sender_user_id"],
            "receiver_user_id": row["receiver_user_id"],
            "message_text": row["message_text"],
            "is_read": bool(row["is_read"]),
            "created_dt": row["created_dt"]
        }
        for row in rows
    ]


@router.post("/thread/{thread_id}", response_model=MessageOut)
def send_thread_message(
    body: SendPostMessageIn,
    thread_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    text = body.message_text.strip()

    if not text:
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty"
        )

    ts = now_iso()

    with get_db() as conn:
        thread = assert_thread_access(
            conn,
            thread_id,
            current_user
        )

        if thread["status"] != "active":
            raise HTTPException(
                status_code=403,
                detail="This thread is closed"
            )

        post = conn.execute(
            """
            SELECT *
            FROM community_posts
            WHERE post_id = ?
            """,
            (thread["post_id"],)
        ).fetchone()

        if not post or post["status"] == "deleted":
            raise HTTPException(
                status_code=403,
                detail="This post is no longer available"
            )

        receiver_user_id = (
            thread["sender_user_id"]
            if current_user == thread["post_owner_id"]
            else thread["post_owner_id"]
        )

        if is_blocked(conn, current_user, receiver_user_id):
            raise HTTPException(
                status_code=403,
                detail="You cannot send message in this thread"
            )

        message_id = generate_message_id()

        conn.execute(
            """
            INSERT INTO post_private_messages
            (
                message_id,
                thread_id,
                sender_user_id,
                receiver_user_id,
                message_text,
                is_read,
                is_deleted,
                created_dt,
                updated_dt
            )
            VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?)
            """,
            (
                message_id,
                thread_id,
                current_user,
                receiver_user_id,
                text,
                ts,
                ts
            )
        )

        conn.execute(
            """
            UPDATE post_private_threads
            SET updated_dt = ?,
                last_message_dt = ?
            WHERE thread_id = ?
            """,
            (
                ts,
                ts,
                thread_id
            )
        )

        sender_name = get_user_name(conn, current_user)

        create_notification(
            conn=conn,
            unique_user_id=receiver_user_id,
            title="New post reply message",
            message=f"{sender_name} sent a message about: {post['title']}",
            notification_type="post_private_reply_message",
            reference_id=thread_id
        )

    return {
        "message_id": message_id,
        "thread_id": thread_id,
        "sender_user_id": current_user,
        "receiver_user_id": receiver_user_id,
        "message_text": text,
        "is_read": False,
        "created_dt": ts
    }


@router.put("/thread/{thread_id}/read", response_model=MarkReadOut)
def mark_thread_read(
    thread_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        assert_thread_access(
            conn,
            thread_id,
            current_user
        )

        cursor = conn.execute(
            """
            UPDATE post_private_messages
            SET is_read = 1,
                updated_dt = ?
            WHERE thread_id = ?
              AND receiver_user_id = ?
              AND is_read = 0
              AND is_deleted = 0
            """,
            (
                now_iso(),
                thread_id,
                current_user
            )
        )

    return {
        "success": True,
        "updated_count": cursor.rowcount
    }