from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr, Field

from database import get_db

from auth_utils import (
    now_iso,
    generate_user_id,
    hash_password,
    verify_password,
    create_access_token,
    get_current_user
)


router = APIRouter(
    prefix="/api/auth",
    tags=["Auth"]
)


# =========================
# SCHEMAS
# =========================

class RegisterIn(BaseModel):
    name: str = Field(..., min_length=2)
    email: EmailStr
    password: str = Field(..., min_length=6)
    city: Optional[str] = ""
    gender: Optional[str] = ""


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class AccountUpdateIn(BaseModel):
    name: Optional[str] = None
    city: Optional[str] = None
    gender: Optional[str] = None


class PasswordChangeIn(BaseModel):
    current_password: str = Field(..., min_length=6)
    new_password: str = Field(..., min_length=6)


class UserOut(BaseModel):
    unique_user_id: str
    name: str
    email: str
    city: Optional[str]
    gender: Optional[str]
    created_dt: str


class AuthOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class SimpleSuccessOut(BaseModel):
    success: bool
    message: str


# =========================
# HELPERS
# =========================

def get_user_by_id(conn, unique_user_id: str):
    return conn.execute(
        """
        SELECT *
        FROM user_reg_info
        WHERE unique_user_id = ?
        """,
        (unique_user_id,)
    ).fetchone()


def get_user_by_email(conn, email: str):
    return conn.execute(
        """
        SELECT *
        FROM user_reg_info
        WHERE email = ?
        """,
        (email,)
    ).fetchone()


# =========================
# REGISTER
# =========================

@router.post("/register", response_model=AuthOut)
def register_user(body: RegisterIn):
    email = body.email.lower().strip()
    created_dt = now_iso()
    unique_user_id = generate_user_id()

    with get_db() as conn:
        existing_user = get_user_by_email(conn, email)

        if existing_user:
            raise HTTPException(
                status_code=409,
                detail="Email already registered"
            )

        password_hash = hash_password(body.password)

        conn.execute(
            """
            INSERT INTO user_reg_info
            (
                unique_user_id,
                name,
                email,
                city,
                gender,
                created_dt,
                updated_dt
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                unique_user_id,
                body.name.strip(),
                email,
                body.city,
                body.gender,
                created_dt,
                created_dt
            )
        )

        conn.execute(
            """
            INSERT INTO user_login_info
            (
                unique_user_id,
                email,
                password_hash,
                is_active,
                created_dt,
                last_login_dt
            )
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            (
                unique_user_id,
                email,
                password_hash,
                created_dt,
                created_dt
            )
        )

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
                unique_user_id,
                created_dt,
                created_dt
            )
        )

        user_row = get_user_by_id(conn, unique_user_id)

    token = create_access_token({
        "unique_user_id": unique_user_id,
        "email": email
    })

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": dict(user_row)
    }


# =========================
# LOGIN
# =========================

@router.post("/login", response_model=AuthOut)
def login_user(body: LoginIn):
    email = body.email.lower().strip()

    with get_db() as conn:
        login_row = conn.execute(
            """
            SELECT *
            FROM user_login_info
            WHERE email = ?
            """,
            (email,)
        ).fetchone()

        if not login_row:
            raise HTTPException(
                status_code=401,
                detail="Incorrect email or password"
            )

        if not login_row["is_active"]:
            raise HTTPException(
                status_code=403,
                detail="Account is inactive"
            )

        valid_password = verify_password(
            body.password,
            login_row["password_hash"]
        )

        if not valid_password:
            raise HTTPException(
                status_code=401,
                detail="Incorrect email or password"
            )

        unique_user_id = login_row["unique_user_id"]
        login_dt = now_iso()

        conn.execute(
            """
            UPDATE user_login_info
            SET last_login_dt = ?
            WHERE unique_user_id = ?
            """,
            (
                login_dt,
                unique_user_id
            )
        )

        user_row = get_user_by_id(conn, unique_user_id)

        if not user_row:
            raise HTTPException(
                status_code=500,
                detail="User registration info missing"
            )

    token = create_access_token({
        "unique_user_id": unique_user_id,
        "email": email
    })

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": dict(user_row)
    }


# =========================
# GET ME
# =========================

@router.get("/me", response_model=UserOut)
def get_me(
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        user_row = get_user_by_id(conn, current_user)

    if not user_row:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    return dict(user_row)


# =========================
# UPDATE ACCOUNT
# =========================

@router.put("/me", response_model=UserOut)
def update_my_account(
    body: AccountUpdateIn,
    current_user: str = Depends(get_current_user)
):
    updated_dt = now_iso()

    with get_db() as conn:
        user_row = get_user_by_id(conn, current_user)

        if not user_row:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        name = body.name if body.name is not None else user_row["name"]
        city = body.city if body.city is not None else user_row["city"]
        gender = body.gender if body.gender is not None else user_row["gender"]

        if not name.strip():
            raise HTTPException(
                status_code=400,
                detail="Name cannot be empty"
            )

        conn.execute(
            """
            UPDATE user_reg_info
            SET
                name = ?,
                city = ?,
                gender = ?,
                updated_dt = ?
            WHERE unique_user_id = ?
            """,
            (
                name.strip(),
                city,
                gender,
                updated_dt,
                current_user
            )
        )

        updated_user = get_user_by_id(conn, current_user)

    return dict(updated_user)


# =========================
# CHANGE PASSWORD
# =========================

@router.put("/change-password", response_model=SimpleSuccessOut)
def change_password(
    body: PasswordChangeIn,
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        login_row = conn.execute(
            """
            SELECT *
            FROM user_login_info
            WHERE unique_user_id = ?
            """,
            (current_user,)
        ).fetchone()

        if not login_row:
            raise HTTPException(
                status_code=404,
                detail="Login info not found"
            )

        valid_password = verify_password(
            body.current_password,
            login_row["password_hash"]
        )

        if not valid_password:
            raise HTTPException(
                status_code=401,
                detail="Current password is incorrect"
            )

        new_hash = hash_password(body.new_password)

        conn.execute(
            """
            UPDATE user_login_info
            SET password_hash = ?
            WHERE unique_user_id = ?
            """,
            (
                new_hash,
                current_user
            )
        )

    return {
        "success": True,
        "message": "Password changed successfully"
    }


# =========================
# SOFT DELETE ACCOUNT
# =========================

@router.delete("/me", response_model=SimpleSuccessOut)
def delete_my_account(
    current_user: str = Depends(get_current_user)
):
    with get_db() as conn:
        login_row = conn.execute(
            """
            SELECT *
            FROM user_login_info
            WHERE unique_user_id = ?
            """,
            (current_user,)
        ).fetchone()

        if not login_row:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        conn.execute(
            """
            UPDATE user_login_info
            SET is_active = 0
            WHERE unique_user_id = ?
            """,
            (current_user,)
        )

    return {
        "success": True,
        "message": "Account deactivated successfully"
    }