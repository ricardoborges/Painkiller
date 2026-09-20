"""Authentication routes for Painkiller."""

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/auth", tags=["auth"])

FIXED_USER = "admin"
FIXED_PASSWORD = "123456"
FIXED_TOKEN = "painkiller-admin-token-2026"


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(req: LoginRequest):
    if req.username == FIXED_USER and req.password == FIXED_PASSWORD:
        return {
            "token": FIXED_TOKEN,
            "user": {
                "username": FIXED_USER,
                "name": "Administrador",
                "role": "admin",
            },
        }
    raise HTTPException(status_code=401, detail="Usuário ou senha incorretos")


@router.get("/me")
async def get_current_user(authorization: Optional[str] = Header(None)):
    if authorization and authorization.replace("Bearer ", "") == FIXED_TOKEN:
        return {
            "username": FIXED_USER,
            "name": "Administrador",
            "role": "admin",
        }
    raise HTTPException(status_code=401, detail="Sessão inválida ou expirada")
