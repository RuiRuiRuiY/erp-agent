"""Sprint 3 Task 1.1: AdminUser 登录接口测试"""
import bcrypt as _bcrypt


class TestAdminLogin:
    def test_login_success(self, client, session):
        from app.model.admin import AdminUser
        session.add(AdminUser(
            username="admin",
            hashed_password=_bcrypt.hashpw(b"test123", _bcrypt.gensalt()).decode(),
            role="admin",
        ))
        session.commit()

        resp = client.post("/api/v1/admin/login", json={
            "username": "admin", "password": "test123",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "token" in body
        assert body["role"] == "admin"

    def test_login_wrong_password(self, client, session):
        from app.model.admin import AdminUser
        session.add(AdminUser(
            username="admin",
            hashed_password=_bcrypt.hashpw(b"test123", _bcrypt.gensalt()).decode(),
            role="admin",
        ))
        session.commit()

        resp = client.post("/api/v1/admin/login", json={
            "username": "admin", "password": "wrong",
        })
        assert resp.status_code == 401

    def test_login_user_not_found(self, client):
        resp = client.post("/api/v1/admin/login", json={
            "username": "nonexistent", "password": "xxx",
        })
        assert resp.status_code == 401

    def test_login_inactive_user(self, client, session):
        from app.model.admin import AdminUser
        session.add(AdminUser(
            username="inactive",
            hashed_password=_bcrypt.hashpw(b"test123", _bcrypt.gensalt()).decode(),
            role="admin", is_active=False,
        ))
        session.commit()

        resp = client.post("/api/v1/admin/login", json={
            "username": "inactive", "password": "test123",
        })
        assert resp.status_code == 401
