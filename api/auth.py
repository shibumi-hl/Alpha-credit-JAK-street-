"""
Упрощённый вход для демо: учётки из USERS, токен - HMAC-SHA256 (SECRET_KEY) от роли, имени и срока действия.
В банке здесь будет корпоративный IdP (OIDC); контракт для API тот же - Bearer-токен с ролью.
"""
import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import Header, HTTPException

USERS = {  # логин: (пароль, роль, имя)
    "client": ("client", "client", "Марина Соколова"),
    "client2": ("client2", "client", "Второй клиент"),
    "analyst": ("analyst", "analyst", "Аналитик МСБ"),
}
TTL = 12 * 3600


def _key() -> bytes:
    return os.environ.get("SECRET_KEY", "change-me-demo").encode()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def issue(username: str, password: str) -> dict:
    u = USERS.get(username)
    if not u or not hmac.compare_digest(u[0], password):
        raise HTTPException(401, "Неверный логин или пароль")
    body = _b64(json.dumps({"sub": username, "role": u[1], "exp": int(time.time()) + TTL}).encode())
    sig = _b64(hmac.new(_key(), body.encode(), hashlib.sha256).digest())
    return {"token": f"{body}.{sig}", "role": u[1], "name": u[2]}


def verify(token: str) -> dict:
    try:
        body, sig = token.split(".")
        good = _b64(hmac.new(_key(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(good, sig):
            raise ValueError
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if claims["exp"] < time.time() or claims["sub"] not in USERS:
            raise ValueError
        return claims
    except (ValueError, KeyError, json.JSONDecodeError):
        raise HTTPException(401, "Нужно войти заново") from None


def user(authorization: str = Header(None)) -> dict:
    """Зависимость FastAPI: {sub, role} из Bearer-токена или 401."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Нужно войти")
    return verify(authorization[7:])
