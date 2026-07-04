import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from database import get_db
from auth_utils import get_current_user, now_iso


router = APIRouter(
    prefix="/api/notifications",
    tags=["Notifications"]
)


class NotificationCreateIn(BaseModel):
    unique_user_id: str
    title: str = Field(..., min_length=2)
    message: str = Field(..., min_length=2)
    notification_type: Optional[str] = "general"
    reference_id: Optional[str] = None


class NotificationOut(BaseModel):
    notification_id: str
    unique_user_id: str
    title: str
    message: str
    notification_type: Optional[str]
    reference_id: Optional[str] = None
    is_read: int
    created_dt: Optional[str]


def generate_notification_id():
    return "NOTIF_" + uuid.uuid4().hex[:10].upper()


@router.get("/me", response_model=list[NotificationOut])
def get_my_notifications(current_user: str = Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM notifications
            WHERE unique_user_id = ?
            ORDER BY created_dt DESC
            """,
            (current_user,)
        ).fetchall()

    return [dict(row) for row in rows]


@router.get("/unread-count")
def get_unread_notification_count(current_user: str = Depends(get_current_user)):
    with get_db() as conn:
        count = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM notifications
            WHERE unique_user_id = ?
              AND is_read = 0
            """,
            (current_user,)
        ).fetchone()["cnt"]

    return {"unread_count": count}


@router.put("/mark-all-read")
def mark_all_notifications_read(current_user: str = Depends(get_current_user)):
    with get_db() as conn:
        cursor = conn.execute(
            """
            UPDATE notifications
            SET is_read = 1
            WHERE unique_user_id = ?
              AND is_read = 0
            """,
            (current_user,)
        )

    return {
        "success": True,
        "updated_count": cursor.rowcount
    }


@router.put("/{notification_id}/read")
def mark_notification_read(
    notification_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM notifications
            WHERE notification_id = ?
            """,
            (notification_id,)
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Notification not found")

        if row["unique_user_id"] != current_user:
            raise HTTPException(status_code=403, detail="Access denied")

        conn.execute(
            """
            UPDATE notifications
            SET is_read = 1
            WHERE notification_id = ?
            """,
            (notification_id,)
        )

    return {
        "success": True,
        "notification_id": notification_id
    }


@router.post("/create", response_model=NotificationOut)
def create_notification(body: NotificationCreateIn):
    notification_id = generate_notification_id()
    ts = now_iso()

    with get_db() as conn:
        user_exists = conn.execute(
            """
            SELECT 1
            FROM user_reg_info
            WHERE unique_user_id = ?
            """,
            (body.unique_user_id,)
        ).fetchone()

        if not user_exists:
            raise HTTPException(status_code=404, detail="User not found")

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
                body.unique_user_id,
                body.title,
                body.message,
                body.notification_type,
                body.reference_id,
                ts
            )
        )

        row = conn.execute(
            """
            SELECT *
            FROM notifications
            WHERE notification_id = ?
            """,
            (notification_id,)
        ).fetchone()

    return dict(row)