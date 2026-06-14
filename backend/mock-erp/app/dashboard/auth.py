"""SQLAdmin 认证后端：基于 session 的简单认证"""
import os

import bcrypt as _bcrypt
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request


class AdminAuth(AuthenticationBackend):
    """管控台认证：检查 session 中的登录状态"""

    def __init__(self):
        super().__init__(secret_key=os.getenv("SECRET_KEY", "erp-agent-demo-secret-key"))

    async def login(self, request: Request) -> bool:
        """验证登录表单提交的用户名密码"""
        form = await request.form()
        username = form.get("username", "")
        password = form.get("password", "")

        if not username or not password:
            return False

        from sqlmodel import Session, select

        from app.core.database import engine
        from app.model.admin import AdminUser

        with Session(engine) as session:
            user = session.exec(
                select(AdminUser).where(AdminUser.username == username)
            ).first()

        if not user or not user.is_active:
            return False
        if not _bcrypt.checkpw(password.encode(), user.hashed_password.encode()):
            return False

        request.session["token"] = f"admin-{user.id}"
        request.session["role"] = user.role
        return True

    async def logout(self, request: Request) -> bool:
        """清除 session"""
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        """检查用户是否已登录"""
        session_token = request.session.get("token")
        if session_token and session_token.startswith("admin-"):
            return True
        return False
