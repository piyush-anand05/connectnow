from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database import get_db
from auth_utils import get_current_user, now_iso


router = APIRouter(
    prefix="/api/profile",
    tags=["Profile"]
)


class ProfileOut(BaseModel):
    unique_user_id: str
    about_me: Optional[str]
    can_help_with: Optional[str]
    skills: Optional[str]
    experience: Optional[str]
    interests: Optional[str]
    availability: Optional[str]
    profile_completed: int
    created_dt: Optional[str]
    updated_dt: Optional[str]


class ProfileUpdateIn(BaseModel):
    about_me: Optional[str] = ""
    can_help_with: Optional[str] = ""
    skills: Optional[str] = ""
    experience: Optional[str] = ""
    interests: Optional[str] = ""
    availability: Optional[str] = ""


@router.get("/me", response_model=ProfileOut)
def get_my_profile(
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM user_profile_details
            WHERE unique_user_id = ?
            """,
            (current_user,)
        ).fetchone()

        if not row:
            ts = now_iso()

            conn.execute(
                """
                INSERT INTO user_profile_details
                (
                    unique_user_id,
                    about_me,
                    can_help_with,
                    skills,
                    experience,
                    interests,
                    availability,
                    profile_completed,
                    created_dt,
                    updated_dt
                )
                VALUES (?, '', '', '', '', '', '', 0, ?, ?)
                """,
                (
                    current_user,
                    ts,
                    ts
                )
            )

            row = conn.execute(
                """
                SELECT *
                FROM user_profile_details
                WHERE unique_user_id = ?
                """,
                (current_user,)
            ).fetchone()

    return dict(row)


@router.put("/me", response_model=ProfileOut)
def update_my_profile(
    body: ProfileUpdateIn,
    current_user: str = Depends(get_current_user)
):
    ts = now_iso()

    profile_completed = 1 if (
        body.about_me.strip()
        or body.can_help_with.strip()
        or body.skills.strip()
        or body.experience.strip()
        or body.interests.strip()
        or body.availability.strip()
    ) else 0

    with get_db() as conn:
        existing = conn.execute(
            """
            SELECT 1
            FROM user_profile_details
            WHERE unique_user_id = ?
            """,
            (current_user,)
        ).fetchone()

        if not existing:
            conn.execute(
                """
                INSERT INTO user_profile_details
                (
                    unique_user_id,
                    about_me,
                    can_help_with,
                    skills,
                    experience,
                    interests,
                    availability,
                    profile_completed,
                    created_dt,
                    updated_dt
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    current_user,
                    body.about_me,
                    body.can_help_with,
                    body.skills,
                    body.experience,
                    body.interests,
                    body.availability,
                    profile_completed,
                    ts,
                    ts
                )
            )

        else:
            conn.execute(
                """
                UPDATE user_profile_details
                SET
                    about_me = ?,
                    can_help_with = ?,
                    skills = ?,
                    experience = ?,
                    interests = ?,
                    availability = ?,
                    profile_completed = ?,
                    updated_dt = ?
                WHERE unique_user_id = ?
                """,
                (
                    body.about_me,
                    body.can_help_with,
                    body.skills,
                    body.experience,
                    body.interests,
                    body.availability,
                    profile_completed,
                    ts,
                    current_user
                )
            )

        row = conn.execute(
            """
            SELECT *
            FROM user_profile_details
            WHERE unique_user_id = ?
            """,
            (current_user,)
        ).fetchone()

    return dict(row)