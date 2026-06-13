from fastapi import APIRouter, Depends, HTTPException
import bcrypt as _bcrypt
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_db_session
from app.model.admin import AdminUser

router = APIRouter(prefix="/admin", tags=["admin"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginRequest, session: Session = Depends(get_db_session)):
    user = session.exec(
        select(AdminUser).where(AdminUser.username == body.username)
    ).first()

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not _bcrypt.checkpw(body.password.encode(), user.hashed_password.encode()):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    from starlette.responses import JSONResponse
    response = JSONResponse(content={"token": f"admin-{user.id}", "role": user.role})
    response.set_cookie(key="session", value=f"admin-{user.id}", httponly=True)
    response.set_cookie(key="role", value=user.role, httponly=True)
    return response
