import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel

from database import get_db
from auth_utils import get_current_user, now_iso


router = APIRouter(
    prefix="/api/network",
    tags=["Network"]
)


class UserCardOut(BaseModel):
    unique_user_id: str
    name: str
    email: str
    city: Optional[str]
    gender: Optional[str]
    about_me: Optional[str]
    can_help_with: Optional[str]
    skills: Optional[str]
    experience: Optional[str]
    interests: Optional[str]
    availability: Optional[str]
    connection_status: Optional[str]
    connection_id: Optional[str] = None


class ConnectionOut(BaseModel):
    connection_id: str
    requester_user_id: str
    receiver_user_id: str
    status: str
    created_dt: Optional[str]
    updated_dt: Optional[str]


class SimpleOut(BaseModel):
    success: bool
    message: str


def generate_connection_id():
    return "CONN_" + uuid.uuid4().hex[:10].upper()


def generate_block_id():
    return "BLOCK_" + uuid.uuid4().hex[:10].upper()


def generate_notification_id():
    return "NOTIF_" + uuid.uuid4().hex[:10].upper()


def get_existing_connection(conn, user_a: str, user_b: str):
    return conn.execute(
        """
        SELECT *
        FROM connections
        WHERE
            (requester_user_id = ? AND receiver_user_id = ?)
            OR
            (requester_user_id = ? AND receiver_user_id = ?)
        """,
        (user_a, user_b, user_b, user_a)
    ).fetchone()


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


def get_user_name(conn, user_id: str):
    row = conn.execute(
        """
        SELECT name
        FROM user_reg_info
        WHERE unique_user_id = ?
        """,
        (user_id,)
    ).fetchone()

    return row["name"] if row else "Someone"


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


@router.get("/discover", response_model=list[UserCardOut])
def discover_people(
    city: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_user: str = Depends(get_current_user)
):
    search_text = f"%{search.lower()}%" if search else None
    city_filter = city if city else None

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                u.unique_user_id,
                u.name,
                u.email,
                u.city,
                u.gender,
                p.about_me,
                p.can_help_with,
                p.skills,
                p.experience,
                p.interests,
                p.availability,

                (
                    SELECT c.status
                    FROM connections c
                    WHERE
                        (
                            c.requester_user_id = ?
                            AND c.receiver_user_id = u.unique_user_id
                        )
                        OR
                        (
                            c.receiver_user_id = ?
                            AND c.requester_user_id = u.unique_user_id
                        )
                    LIMIT 1
                ) AS connection_status,

                (
                    SELECT c.connection_id
                    FROM connections c
                    WHERE
                        (
                            c.requester_user_id = ?
                            AND c.receiver_user_id = u.unique_user_id
                        )
                        OR
                        (
                            c.receiver_user_id = ?
                            AND c.requester_user_id = u.unique_user_id
                        )
                    LIMIT 1
                ) AS connection_id

            FROM user_reg_info u

            LEFT JOIN user_profile_details p
                ON p.unique_user_id = u.unique_user_id

            WHERE u.unique_user_id != ?

              AND NOT EXISTS (
                  SELECT 1
                  FROM user_blocks b
                  WHERE
                      (
                          b.blocker_user_id = ?
                          AND b.blocked_user_id = u.unique_user_id
                      )
                      OR
                      (
                          b.blocked_user_id = ?
                          AND b.blocker_user_id = u.unique_user_id
                      )
              )

              AND (? IS NULL OR u.city = ?)

              AND (
                    ? IS NULL
                    OR lower(u.name) LIKE ?
                    OR lower(u.city) LIKE ?
                    OR lower(p.can_help_with) LIKE ?
                    OR lower(p.skills) LIKE ?
                    OR lower(p.interests) LIKE ?
                    OR lower(p.experience) LIKE ?
                  )

            ORDER BY u.created_dt DESC
            """,
            (
                current_user,
                current_user,
                current_user,
                current_user,

                current_user,
                current_user,
                current_user,

                city_filter,
                city_filter,

                search_text,
                search_text,
                search_text,
                search_text,
                search_text,
                search_text,
                search_text
            )
        ).fetchall()

    return [dict(row) for row in rows]


@router.get("/connections", response_model=list[UserCardOut])
def my_connections(
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                u.unique_user_id,
                u.name,
                u.email,
                u.city,
                u.gender,
                p.about_me,
                p.can_help_with,
                p.skills,
                p.experience,
                p.interests,
                p.availability,
                c.status AS connection_status,
                c.connection_id AS connection_id

            FROM connections c

            JOIN user_reg_info u
                ON u.unique_user_id =
                    CASE
                        WHEN c.requester_user_id = ?
                        THEN c.receiver_user_id
                        ELSE c.requester_user_id
                    END

            LEFT JOIN user_profile_details p
                ON p.unique_user_id = u.unique_user_id

            WHERE
                (c.requester_user_id = ? OR c.receiver_user_id = ?)
                AND c.status = 'accepted'

                AND NOT EXISTS (
                    SELECT 1
                    FROM user_blocks b
                    WHERE
                        (
                            b.blocker_user_id = ?
                            AND b.blocked_user_id = u.unique_user_id
                        )
                        OR
                        (
                            b.blocked_user_id = ?
                            AND b.blocker_user_id = u.unique_user_id
                        )
                )

            ORDER BY c.updated_dt DESC
            """,
            (
                current_user,
                current_user,
                current_user,
                current_user,
                current_user
            )
        ).fetchall()

    return [dict(row) for row in rows]


@router.get("/requests", response_model=list[UserCardOut])
def my_pending_requests(
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                u.unique_user_id,
                u.name,
                u.email,
                u.city,
                u.gender,
                p.about_me,
                p.can_help_with,
                p.skills,
                p.experience,
                p.interests,
                p.availability,
                c.status AS connection_status,
                c.connection_id AS connection_id

            FROM connections c

            JOIN user_reg_info u
                ON u.unique_user_id = c.requester_user_id

            LEFT JOIN user_profile_details p
                ON p.unique_user_id = u.unique_user_id

            WHERE c.receiver_user_id = ?
              AND c.status = 'pending'

              AND NOT EXISTS (
                  SELECT 1
                  FROM user_blocks b
                  WHERE
                      (
                          b.blocker_user_id = ?
                          AND b.blocked_user_id = u.unique_user_id
                      )
                      OR
                      (
                          b.blocked_user_id = ?
                          AND b.blocker_user_id = u.unique_user_id
                      )
              )

            ORDER BY c.created_dt DESC
            """,
            (
                current_user,
                current_user,
                current_user
            )
        ).fetchall()

    return [dict(row) for row in rows]


@router.post("/request/{receiver_user_id}", response_model=ConnectionOut)
def send_connection_request(
    receiver_user_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    if receiver_user_id == current_user:
        raise HTTPException(
            status_code=400,
            detail="Cannot connect with yourself"
        )

    ts = now_iso()
    connection_id = generate_connection_id()

    with get_db() as conn:
        receiver = conn.execute(
            """
            SELECT 1
            FROM user_reg_info
            WHERE unique_user_id = ?
            """,
            (receiver_user_id,)
        ).fetchone()

        if not receiver:
            raise HTTPException(
                status_code=404,
                detail="Receiver user not found"
            )

        if is_blocked(conn, current_user, receiver_user_id):
            raise HTTPException(
                status_code=403,
                detail="Connection request blocked"
            )

        existing = get_existing_connection(
            conn,
            current_user,
            receiver_user_id
        )

        if existing:
            return dict(existing)

        conn.execute(
            """
            INSERT INTO connections
            (
                connection_id,
                requester_user_id,
                receiver_user_id,
                status,
                created_dt,
                updated_dt
            )
            VALUES (?, ?, ?, 'pending', ?, ?)
            """,
            (
                connection_id,
                current_user,
                receiver_user_id,
                ts,
                ts
            )
        )

        sender_name = get_user_name(conn, current_user)

        create_notification(
            conn=conn,
            unique_user_id=receiver_user_id,
            title="New connection request",
            message=f"{sender_name} wants to connect with you.",
            notification_type="connection_request",
            reference_id=connection_id
        )

        row = conn.execute(
            """
            SELECT *
            FROM connections
            WHERE connection_id = ?
            """,
            (connection_id,)
        ).fetchone()

    return dict(row)


@router.put("/accept/{connection_id}", response_model=ConnectionOut)
def accept_connection(
    connection_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    ts = now_iso()

    with get_db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM connections
            WHERE connection_id = ?
            """,
            (connection_id,)
        ).fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail="Connection request not found"
            )

        if row["receiver_user_id"] != current_user:
            raise HTTPException(
                status_code=403,
                detail="Only receiver can accept this request"
            )

        if is_blocked(
            conn,
            row["requester_user_id"],
            row["receiver_user_id"]
        ):
            raise HTTPException(
                status_code=403,
                detail="Cannot accept blocked connection"
            )

        conn.execute(
            """
            UPDATE connections
            SET status = 'accepted',
                updated_dt = ?
            WHERE connection_id = ?
            """,
            (
                ts,
                connection_id
            )
        )

        receiver_name = get_user_name(conn, current_user)

        create_notification(
            conn=conn,
            unique_user_id=row["requester_user_id"],
            title="Connection accepted",
            message=f"{receiver_name} accepted your connection request.",
            notification_type="connection_accepted",
            reference_id=connection_id
        )

        updated = conn.execute(
            """
            SELECT *
            FROM connections
            WHERE connection_id = ?
            """,
            (connection_id,)
        ).fetchone()

    return dict(updated)


@router.put("/reject/{connection_id}", response_model=ConnectionOut)
def reject_connection(
    connection_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    ts = now_iso()

    with get_db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM connections
            WHERE connection_id = ?
            """,
            (connection_id,)
        ).fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail="Connection request not found"
            )

        if row["receiver_user_id"] != current_user:
            raise HTTPException(
                status_code=403,
                detail="Only receiver can reject this request"
            )

        conn.execute(
            """
            UPDATE connections
            SET status = 'rejected',
                updated_dt = ?
            WHERE connection_id = ?
            """,
            (
                ts,
                connection_id
            )
        )

        updated = conn.execute(
            """
            SELECT *
            FROM connections
            WHERE connection_id = ?
            """,
            (connection_id,)
        ).fetchone()

    return dict(updated)


@router.delete("/remove-user/{other_user_id}", response_model=SimpleOut)
def remove_connection(
    other_user_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        existing = get_existing_connection(
            conn,
            current_user,
            other_user_id
        )

        if not existing:
            raise HTTPException(
                status_code=404,
                detail="Connection not found"
            )

        if existing["status"] != "accepted":
            raise HTTPException(
                status_code=400,
                detail="Only accepted connections can be removed"
            )

        conn.execute(
            """
            DELETE FROM connections
            WHERE connection_id = ?
            """,
            (existing["connection_id"],)
        )

    return {
        "success": True,
        "message": "Connection removed"
    }


@router.post("/block/{blocked_user_id}", response_model=SimpleOut)
def block_user(
    blocked_user_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    if blocked_user_id == current_user:
        raise HTTPException(
            status_code=400,
            detail="Cannot block yourself"
        )

    block_id = generate_block_id()
    ts = now_iso()

    with get_db() as conn:
        user_exists = conn.execute(
            """
            SELECT 1
            FROM user_reg_info
            WHERE unique_user_id = ?
            """,
            (blocked_user_id,)
        ).fetchone()

        if not user_exists:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        conn.execute(
            """
            INSERT OR IGNORE INTO user_blocks
            (
                block_id,
                blocker_user_id,
                blocked_user_id,
                created_dt
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                block_id,
                current_user,
                blocked_user_id,
                ts
            )
        )

        existing = get_existing_connection(
            conn,
            current_user,
            blocked_user_id
        )

        if existing:
            conn.execute(
                """
                DELETE FROM connections
                WHERE connection_id = ?
                """,
                (existing["connection_id"],)
            )

    return {
        "success": True,
        "message": "User blocked"
    }


@router.delete("/unblock/{blocked_user_id}", response_model=SimpleOut)
def unblock_user(
    blocked_user_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        conn.execute(
            """
            DELETE FROM user_blocks
            WHERE blocker_user_id = ?
              AND blocked_user_id = ?
            """,
            (
                current_user,
                blocked_user_id
            )
        )

    return {
        "success": True,
        "message": "User unblocked"
    }


@router.get("/blocked", response_model=list[UserCardOut])
def get_blocked_users(
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                u.unique_user_id,
                u.name,
                u.email,
                u.city,
                u.gender,
                p.about_me,
                p.can_help_with,
                p.skills,
                p.experience,
                p.interests,
                p.availability,
                'blocked' AS connection_status,
                NULL AS connection_id

            FROM user_blocks b

            JOIN user_reg_info u
                ON u.unique_user_id = b.blocked_user_id

            LEFT JOIN user_profile_details p
                ON p.unique_user_id = u.unique_user_id

            WHERE b.blocker_user_id = ?

            ORDER BY b.created_dt DESC
            """,
            (current_user,)
        ).fetchall()

    return [dict(row) for row in rows]
@router.get("/profile/{user_id}", response_model=UserCardOut)
def get_network_profile(
    user_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    if user_id == current_user:
        raise HTTPException(
            status_code=400,
            detail="Use /api/auth/me or /api/profile/me for your own profile"
        )

    with get_db() as conn:
        if is_blocked(conn, current_user, user_id):
            raise HTTPException(
                status_code=403,
                detail="Profile not available"
            )

        row = conn.execute(
            """
            SELECT
                u.unique_user_id,
                u.name,
                u.email,
                u.city,
                u.gender,
                p.about_me,
                p.can_help_with,
                p.skills,
                p.experience,
                p.interests,
                p.availability,

                (
                    SELECT c.status
                    FROM connections c
                    WHERE
                        (
                            c.requester_user_id = ?
                            AND c.receiver_user_id = u.unique_user_id
                        )
                        OR
                        (
                            c.receiver_user_id = ?
                            AND c.requester_user_id = u.unique_user_id
                        )
                    LIMIT 1
                ) AS connection_status,

                (
                    SELECT c.connection_id
                    FROM connections c
                    WHERE
                        (
                            c.requester_user_id = ?
                            AND c.receiver_user_id = u.unique_user_id
                        )
                        OR
                        (
                            c.receiver_user_id = ?
                            AND c.requester_user_id = u.unique_user_id
                        )
                    LIMIT 1
                ) AS connection_id

            FROM user_reg_info u

            LEFT JOIN user_profile_details p
                ON p.unique_user_id = u.unique_user_id

            WHERE u.unique_user_id = ?
            """,
            (
                current_user,
                current_user,
                current_user,
                current_user,
                user_id
            )
        ).fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    return dict(row)


@router.delete("/cancel-request/{other_user_id}", response_model=SimpleOut)
def cancel_connection_request(
    other_user_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM connections
            WHERE requester_user_id = ?
              AND receiver_user_id = ?
              AND status = 'pending'
            """,
            (
                current_user,
                other_user_id
            )
        ).fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail="Pending request not found"
            )

        conn.execute(
            """
            DELETE FROM connections
            WHERE connection_id = ?
            """,
            (row["connection_id"],)
        )

    return {
        "success": True,
        "message": "Connection request cancelled"
    }