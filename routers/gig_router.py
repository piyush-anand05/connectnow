import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from database import get_db
from auth_utils import get_current_user, now_iso


router = APIRouter(
    prefix="/api/gigs",
    tags=["Gigs"]
)


# =========================
# SCHEMAS
# =========================

class GigCreateIn(BaseModel):
    title: str = Field(..., min_length=2)
    short_description: str = Field(..., min_length=2)
    detailed_description: Optional[str] = ""
    category: Optional[str] = "General"
    custom_category: Optional[str] = ""
    budget: Optional[float] = 0
    location: Optional[str] = ""
    deadline_date: Optional[str] = ""


class GigUpdateIn(BaseModel):
    title: Optional[str] = ""
    short_description: Optional[str] = ""
    detailed_description: Optional[str] = ""
    category: Optional[str] = ""
    custom_category: Optional[str] = ""
    budget: Optional[float] = 0
    location: Optional[str] = ""
    deadline_date: Optional[str] = ""
    status: Optional[str] = "open"


class GigOut(BaseModel):
    gig_id: str
    unique_user_id: str
    user_name: Optional[str]
    title: Optional[str]
    short_description: Optional[str]
    detailed_description: Optional[str]
    category: Optional[str]
    custom_category: Optional[str]
    budget: Optional[float]
    location: Optional[str]
    deadline_date: Optional[str]
    status: Optional[str]
    created_dt: Optional[str]
    updated_dt: Optional[str]


class GigApplyIn(BaseModel):
    message: Optional[str] = ""


class GigApplicationOut(BaseModel):
    application_id: str
    gig_id: str
    applicant_user_id: str
    applicant_name: Optional[str]
    message: Optional[str]
    status: Optional[str]
    created_dt: Optional[str]
    updated_dt: Optional[str]


class ApplicationStatusIn(BaseModel):
    status: str = Field(..., description="shortlisted / rejected / accepted")


# =========================
# HELPERS
# =========================

def generate_gig_id():
    return "GIG_" + uuid.uuid4().hex[:10].upper()


def generate_application_id():
    return "APP_" + uuid.uuid4().hex[:10].upper()


def fetch_gig_by_id(conn, gig_id: str):
    return conn.execute(
        """
        SELECT
            g.*,
            u.name AS user_name
        FROM gigs g
        LEFT JOIN user_reg_info u
            ON u.unique_user_id = g.unique_user_id
        WHERE g.gig_id = ?
        """,
        (gig_id,)
    ).fetchone()


# =========================
# GIG CRUD
# =========================

@router.post("", response_model=GigOut)
def create_gig(
    body: GigCreateIn,
    current_user: str = Depends(get_current_user)
):
    gig_id = generate_gig_id()
    ts = now_iso()

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO gigs
            (
                gig_id,
                unique_user_id,
                title,
                short_description,
                detailed_description,
                category,
                custom_category,
                budget,
                location,
                deadline_date,
                status,
                created_dt,
                updated_dt
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
            """,
            (
                gig_id,
                current_user,
                body.title.strip(),
                body.short_description.strip(),
                body.detailed_description,
                body.category,
                body.custom_category,
                body.budget,
                body.location,
                body.deadline_date,
                ts,
                ts
            )
        )

        row = fetch_gig_by_id(conn, gig_id)

    return dict(row)


@router.get("", response_model=list[GigOut])
def browse_gigs():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                g.*,
                u.name AS user_name
            FROM gigs g
            LEFT JOIN user_reg_info u
                ON u.unique_user_id = g.unique_user_id
            WHERE g.status = 'open'
            ORDER BY g.created_dt DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


@router.get("/me", response_model=list[GigOut])
def my_gigs(
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                g.*,
                u.name AS user_name
            FROM gigs g
            LEFT JOIN user_reg_info u
                ON u.unique_user_id = g.unique_user_id
            WHERE g.unique_user_id = ?
              AND g.status != 'deleted'
            ORDER BY g.created_dt DESC
            """,
            (current_user,)
        ).fetchall()

    return [dict(row) for row in rows]


@router.get("/{gig_id}", response_model=GigOut)
def get_gig(
    gig_id: str = Path(...)
):
    with get_db() as conn:
        row = fetch_gig_by_id(conn, gig_id)

    if not row or row["status"] == "deleted":
        raise HTTPException(
            status_code=404,
            detail="Gig not found"
        )

    return dict(row)


@router.put("/{gig_id}", response_model=GigOut)
def update_gig(
    body: GigUpdateIn,
    gig_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    ts = now_iso()

    with get_db() as conn:
        existing = conn.execute(
            """
            SELECT *
            FROM gigs
            WHERE gig_id = ?
            """,
            (gig_id,)
        ).fetchone()

        if not existing or existing["status"] == "deleted":
            raise HTTPException(
                status_code=404,
                detail="Gig not found"
            )

        if existing["unique_user_id"] != current_user:
            raise HTTPException(
                status_code=403,
                detail="You can update only your own gig"
            )

        conn.execute(
            """
            UPDATE gigs
            SET
                title = ?,
                short_description = ?,
                detailed_description = ?,
                category = ?,
                custom_category = ?,
                budget = ?,
                location = ?,
                deadline_date = ?,
                status = ?,
                updated_dt = ?
            WHERE gig_id = ?
            """,
            (
                body.title,
                body.short_description,
                body.detailed_description,
                body.category,
                body.custom_category,
                body.budget,
                body.location,
                body.deadline_date,
                body.status,
                ts,
                gig_id
            )
        )

        row = fetch_gig_by_id(conn, gig_id)

    return dict(row)


@router.delete("/{gig_id}")
def delete_gig(
    gig_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    ts = now_iso()

    with get_db() as conn:
        existing = conn.execute(
            """
            SELECT *
            FROM gigs
            WHERE gig_id = ?
            """,
            (gig_id,)
        ).fetchone()

        if not existing or existing["status"] == "deleted":
            raise HTTPException(
                status_code=404,
                detail="Gig not found"
            )

        if existing["unique_user_id"] != current_user:
            raise HTTPException(
                status_code=403,
                detail="You can delete only your own gig"
            )

        conn.execute(
            """
            UPDATE gigs
            SET status = 'deleted',
                updated_dt = ?
            WHERE gig_id = ?
            """,
            (
                ts,
                gig_id
            )
        )

    return {
        "success": True,
        "message": "Gig deleted",
        "gig_id": gig_id
    }


# =========================
# APPLICATIONS
# =========================

@router.post("/{gig_id}/apply", response_model=GigApplicationOut)
def apply_to_gig(
    body: GigApplyIn,
    gig_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    application_id = generate_application_id()
    ts = now_iso()

    with get_db() as conn:
        gig = conn.execute(
            """
            SELECT *
            FROM gigs
            WHERE gig_id = ?
              AND status = 'open'
            """,
            (gig_id,)
        ).fetchone()

        if not gig:
            raise HTTPException(
                status_code=404,
                detail="Gig not found or not open"
            )

        if gig["unique_user_id"] == current_user:
            raise HTTPException(
                status_code=400,
                detail="You cannot apply to your own gig"
            )

        existing = conn.execute(
            """
            SELECT *
            FROM gig_applications
            WHERE gig_id = ?
              AND applicant_user_id = ?
            """,
            (
                gig_id,
                current_user
            )
        ).fetchone()

        if existing:
            return dict(existing)

        conn.execute(
            """
            INSERT INTO gig_applications
            (
                application_id,
                gig_id,
                applicant_user_id,
                message,
                status,
                created_dt,
                updated_dt
            )
            VALUES (?, ?, ?, ?, 'applied', ?, ?)
            """,
            (
                application_id,
                gig_id,
                current_user,
                body.message,
                ts,
                ts
            )
        )

        row = conn.execute(
            """
            SELECT
                a.*,
                u.name AS applicant_name
            FROM gig_applications a
            LEFT JOIN user_reg_info u
                ON u.unique_user_id = a.applicant_user_id
            WHERE a.application_id = ?
            """,
            (application_id,)
        ).fetchone()

    return dict(row)


@router.get("/{gig_id}/applications", response_model=list[GigApplicationOut])
def get_gig_applications(
    gig_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        gig = conn.execute(
            """
            SELECT *
            FROM gigs
            WHERE gig_id = ?
            """,
            (gig_id,)
        ).fetchone()

        if not gig:
            raise HTTPException(
                status_code=404,
                detail="Gig not found"
            )

        if gig["unique_user_id"] != current_user:
            raise HTTPException(
                status_code=403,
                detail="Only gig owner can view applications"
            )

        rows = conn.execute(
            """
            SELECT
                a.*,
                u.name AS applicant_name
            FROM gig_applications a
            LEFT JOIN user_reg_info u
                ON u.unique_user_id = a.applicant_user_id
            WHERE a.gig_id = ?
            ORDER BY a.created_dt DESC
            """,
            (gig_id,)
        ).fetchall()

    return [dict(row) for row in rows]


@router.get("/applications/me", response_model=list[GigApplicationOut])
def my_applications(
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                a.*,
                u.name AS applicant_name
            FROM gig_applications a
            LEFT JOIN user_reg_info u
                ON u.unique_user_id = a.applicant_user_id
            WHERE a.applicant_user_id = ?
            ORDER BY a.created_dt DESC
            """,
            (current_user,)
        ).fetchall()

    return [dict(row) for row in rows]


@router.put("/applications/{application_id}/status", response_model=GigApplicationOut)
def update_application_status(
    body: ApplicationStatusIn,
    application_id: str = Path(...),
    current_user: str = Depends(get_current_user)
):
    allowed = {"shortlisted", "rejected", "accepted"}

    if body.status not in allowed:
        raise HTTPException(
            status_code=400,
            detail="Invalid status"
        )

    ts = now_iso()

    with get_db() as conn:
        application = conn.execute(
            """
            SELECT *
            FROM gig_applications
            WHERE application_id = ?
            """,
            (application_id,)
        ).fetchone()

        if not application:
            raise HTTPException(
                status_code=404,
                detail="Application not found"
            )

        gig = conn.execute(
            """
            SELECT *
            FROM gigs
            WHERE gig_id = ?
            """,
            (application["gig_id"],)
        ).fetchone()

        if not gig or gig["unique_user_id"] != current_user:
            raise HTTPException(
                status_code=403,
                detail="Only gig owner can update application status"
            )

        conn.execute(
            """
            UPDATE gig_applications
            SET status = ?,
                updated_dt = ?
            WHERE application_id = ?
            """,
            (
                body.status,
                ts,
                application_id
            )
        )

        row = conn.execute(
            """
            SELECT
                a.*,
                u.name AS applicant_name
            FROM gig_applications a
            LEFT JOIN user_reg_info u
                ON u.unique_user_id = a.applicant_user_id
            WHERE a.application_id = ?
            """,
            (application_id,)
        ).fetchone()

    return dict(row)