import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from database import get_db
from auth_utils import get_current_user, now_iso


router = APIRouter(
    prefix="/api/posts",
    tags=["Community Posts"]
)


class PostCreateIn(BaseModel):
    title: str = Field(..., min_length=2)
    short_description: str = Field(..., min_length=2)
    detailed_description: Optional[str] = ""
    category: Optional[str] = "Community"
    custom_category: Optional[str] = ""
    event_date: Optional[str] = ""
    event_time: Optional[str] = ""
    location: Optional[str] = ""
    post_type: Optional[str] = "community"
    allow_private_replies: Optional[int] = 1


class PostUpdateIn(BaseModel):
    title: Optional[str] = ""
    short_description: Optional[str] = ""
    detailed_description: Optional[str] = ""
    category: Optional[str] = ""
    custom_category: Optional[str] = ""
    event_date: Optional[str] = ""
    event_time: Optional[str] = ""
    location: Optional[str] = ""
    post_type: Optional[str] = "community"
    allow_private_replies: Optional[int] = 1


class ReportPostIn(BaseModel):
    reason: str
    other_reason: Optional[str] = ""


class PostOut(BaseModel):
    post_id: str
    unique_user_id: str
    user_name: Optional[str]
    title: Optional[str]
    short_description: Optional[str]
    detailed_description: Optional[str]
    category: Optional[str]
    custom_category: Optional[str]
    event_date: Optional[str]
    event_time: Optional[str]
    location: Optional[str]
    post_type: Optional[str]
    allow_private_replies: Optional[int] = 1
    status: Optional[str]
    created_dt: Optional[str]
    updated_dt: Optional[str]
    like_count: Optional[int] = 0
    is_liked_by_me: Optional[int] = 0


def generate_post_id():
    return "POST_" + uuid.uuid4().hex[:10].upper()


def generate_like_id():
    return "LIKE_" + uuid.uuid4().hex[:10].upper()


def generate_report_id():
    return "REPORT_" + uuid.uuid4().hex[:10].upper()


def fetch_post_by_id(conn, post_id: str, current_user: Optional[str] = None):
    return conn.execute(
        """
        SELECT 
            p.*,
            u.name AS user_name,

            (
                SELECT COUNT(*)
                FROM post_likes l
                WHERE l.post_id = p.post_id
            ) AS like_count,

            (
                SELECT COUNT(*)
                FROM post_likes l
                WHERE l.post_id = p.post_id
                  AND l.unique_user_id = ?
            ) AS is_liked_by_me

        FROM community_posts p

        LEFT JOIN user_reg_info u
            ON u.unique_user_id = p.unique_user_id

        WHERE p.post_id = ?
        """,
        (
            current_user or "",
            post_id
        )
    ).fetchone()


@router.post("", response_model=PostOut)
def create_post(
    body: PostCreateIn,
    current_user: str = Depends(get_current_user)
):
    post_id = generate_post_id()
    ts = now_iso()

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO community_posts
            (
                post_id,
                unique_user_id,
                title,
                short_description,
                detailed_description,
                category,
                custom_category,
                event_date,
                event_time,
                location,
                post_type,
                allow_private_replies,
                status,
                created_dt,
                updated_dt
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                post_id,
                current_user,
                body.title.strip(),
                body.short_description.strip(),
                body.detailed_description,
                body.category,
                body.custom_category,
                body.event_date,
                body.event_time,
                body.location,
                body.post_type,
                body.allow_private_replies,
                ts,
                ts
            )
        )

        row = fetch_post_by_id(conn, post_id, current_user)

    return dict(row)


@router.get("", response_model=list[PostOut])
def get_home_posts(
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT 
                p.*,
                u.name AS user_name,

                (
                    SELECT COUNT(*)
                    FROM post_likes l
                    WHERE l.post_id = p.post_id
                ) AS like_count,

                (
                    SELECT COUNT(*)
                    FROM post_likes l
                    WHERE l.post_id = p.post_id
                      AND l.unique_user_id = ?
                ) AS is_liked_by_me

            FROM community_posts p

            LEFT JOIN user_reg_info u
                ON u.unique_user_id = p.unique_user_id

            WHERE p.status = 'active'

            ORDER BY p.created_dt DESC
            """,
            (current_user,)
        ).fetchall()

    return [dict(row) for row in rows]


@router.get("/me", response_model=list[PostOut])
def get_my_posts(
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT 
                p.*,
                u.name AS user_name,

                (
                    SELECT COUNT(*)
                    FROM post_likes l
                    WHERE l.post_id = p.post_id
                ) AS like_count,

                (
                    SELECT COUNT(*)
                    FROM post_likes l
                    WHERE l.post_id = p.post_id
                      AND l.unique_user_id = ?
                ) AS is_liked_by_me

            FROM community_posts p

            LEFT JOIN user_reg_info u
                ON u.unique_user_id = p.unique_user_id

            WHERE p.unique_user_id = ?
              AND p.status != 'deleted'

            ORDER BY p.created_dt DESC
            """,
            (
                current_user,
                current_user
            )
        ).fetchall()

    return [dict(row) for row in rows]


@router.get("/{post_id}", response_model=PostOut)
def get_post(
    post_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        row = fetch_post_by_id(conn, post_id, current_user)

    if not row or row["status"] == "deleted":
        raise HTTPException(
            status_code=404,
            detail="Post not found"
        )

    return dict(row)


@router.put("/{post_id}", response_model=PostOut)
def update_post(
    body: PostUpdateIn,
    post_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    ts = now_iso()

    with get_db() as conn:
        existing = conn.execute(
            """
            SELECT *
            FROM community_posts
            WHERE post_id = ?
            """,
            (post_id,)
        ).fetchone()

        if not existing or existing["status"] == "deleted":
            raise HTTPException(
                status_code=404,
                detail="Post not found"
            )

        if existing["unique_user_id"] != current_user:
            raise HTTPException(
                status_code=403,
                detail="You can update only your own post"
            )

        conn.execute(
            """
            UPDATE community_posts
            SET
                title = ?,
                short_description = ?,
                detailed_description = ?,
                category = ?,
                custom_category = ?,
                event_date = ?,
                event_time = ?,
                location = ?,
                post_type = ?,
                allow_private_replies = ?,
                updated_dt = ?
            WHERE post_id = ?
            """,
            (
                body.title,
                body.short_description,
                body.detailed_description,
                body.category,
                body.custom_category,
                body.event_date,
                body.event_time,
                body.location,
                body.post_type,
                body.allow_private_replies,
                ts,
                post_id
            )
        )

        row = fetch_post_by_id(conn, post_id, current_user)

    return dict(row)


@router.delete("/{post_id}")
def delete_post(
    post_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    ts = now_iso()

    with get_db() as conn:
        existing = conn.execute(
            """
            SELECT *
            FROM community_posts
            WHERE post_id = ?
            """,
            (post_id,)
        ).fetchone()

        if not existing or existing["status"] == "deleted":
            raise HTTPException(
                status_code=404,
                detail="Post not found"
            )

        if existing["unique_user_id"] != current_user:
            raise HTTPException(
                status_code=403,
                detail="You can delete only your own post"
            )

        conn.execute(
            """
            UPDATE community_posts
            SET status = 'deleted',
                updated_dt = ?
            WHERE post_id = ?
            """,
            (
                ts,
                post_id
            )
        )

        conn.execute(
            """
            UPDATE post_private_threads
            SET status = 'archived',
                updated_dt = ?
            WHERE post_id = ?
            """,
            (
                ts,
                post_id
            )
        )

    return {
        "success": True,
        "message": "Post deleted",
        "post_id": post_id
    }


@router.post("/{post_id}/like")
def like_post(
    post_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    like_id = generate_like_id()
    ts = now_iso()

    with get_db() as conn:
        post = conn.execute(
            """
            SELECT *
            FROM community_posts
            WHERE post_id = ?
              AND status = 'active'
            """,
            (post_id,)
        ).fetchone()

        if not post:
            raise HTTPException(
                status_code=404,
                detail="Post not found"
            )

        conn.execute(
            """
            INSERT OR IGNORE INTO post_likes
            (
                like_id,
                post_id,
                unique_user_id,
                created_dt
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                like_id,
                post_id,
                current_user,
                ts
            )
        )

        count = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM post_likes
            WHERE post_id = ?
            """,
            (post_id,)
        ).fetchone()["cnt"]

    return {
        "success": True,
        "post_id": post_id,
        "like_count": count,
        "is_liked_by_me": 1
    }


@router.delete("/{post_id}/like")
def unlike_post(
    post_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        conn.execute(
            """
            DELETE FROM post_likes
            WHERE post_id = ?
              AND unique_user_id = ?
            """,
            (
                post_id,
                current_user
            )
        )

        count = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM post_likes
            WHERE post_id = ?
            """,
            (post_id,)
        ).fetchone()["cnt"]

    return {
        "success": True,
        "post_id": post_id,
        "like_count": count,
        "is_liked_by_me": 0
    }


@router.post("/{post_id}/report")
def report_post(
    body: ReportPostIn,
    post_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    allowed_reasons = ["Abuse", "Sexual", "Fraud", "Other"]

    if body.reason not in allowed_reasons:
        raise HTTPException(
            status_code=400,
            detail="Invalid report reason"
        )

    if body.reason == "Other":
        words = (body.other_reason or "").strip().split()

        if len(words) == 0:
            raise HTTPException(
                status_code=400,
                detail="Please specify reason"
            )

        if len(words) > 15:
            raise HTTPException(
                status_code=400,
                detail="Other reason must be within 15 words"
            )

    report_id = generate_report_id()
    ts = now_iso()

    with get_db() as conn:
        post = conn.execute(
            """
            SELECT *
            FROM community_posts
            WHERE post_id = ?
              AND status = 'active'
            """,
            (post_id,)
        ).fetchone()

        if not post:
            raise HTTPException(
                status_code=404,
                detail="Post not found"
            )

        if post["unique_user_id"] == current_user:
            raise HTTPException(
                status_code=400,
                detail="You cannot report your own post"
            )

        existing = conn.execute(
            """
            SELECT 1
            FROM post_reports
            WHERE post_id = ?
              AND reporter_user_id = ?
            """,
            (
                post_id,
                current_user
            )
        ).fetchone()

        if existing:
            raise HTTPException(
                status_code=409,
                detail="You have already reported this post"
            )

        conn.execute(
            """
            INSERT INTO post_reports
            (
                report_id,
                post_id,
                reporter_user_id,
                reason,
                other_reason,
                status,
                created_dt
            )
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                report_id,
                post_id,
                current_user,
                body.reason,
                body.other_reason,
                ts
            )
        )

    return {
        "success": True,
        "message": "Post reported",
        "report_id": report_id
    }