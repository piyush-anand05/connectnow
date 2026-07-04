import uuid

from datetime import datetime, timedelta, timezone

import jwt

from fastapi import Header, HTTPException, status

from passlib.context import CryptContext

from config import (
    SECRET_KEY,
    ALGORITHM,
    ACCESS_TOKEN_EXPIRE_DAYS
)


pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)


def now_iso():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:-3] + "Z"


def generate_user_id():
    return "USR_" + uuid.uuid4().hex[:10].upper()


def hash_password(password: str):
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str):
    return pwd_context.verify(
        plain_password,
        password_hash
    )


def create_access_token(data: dict):
    payload = data.copy()

    expire = datetime.now(timezone.utc) + timedelta(
        days=ACCESS_TOKEN_EXPIRE_DAYS
    )

    payload.update({
        "exp": expire
    })

    token = jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM
    )

    return token


def get_current_user(
    authorization: str = Header(...)
):
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be Bearer token"
        )

    token = authorization.split(" ", 1)[1]

    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token expired"
        )

    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail="Invalid token"
        )

    unique_user_id = payload.get("unique_user_id")

    if not unique_user_id:
        raise HTTPException(
            status_code=401,
            detail="Token missing unique_user_id"
        )

    return unique_user_id