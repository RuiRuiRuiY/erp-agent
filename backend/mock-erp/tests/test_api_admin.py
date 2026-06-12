"""Sprint 3 Task 1.1: AdminUser 登录接口测试"""


class TestAdminLogin:
    def test_login_success(self, client, session):
        # 先通过 seed 或直接插入创建 admin 用户
        from app.model.admin import AdminUser
        session.add(AdminUser(
            username="admin", hashed_password="hashed_123", role="admin",
        ))
        session.commit()

        resp = client.post("/api/v1/admin/login", json={
            "username": "admin", "password": "hashed_123",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "token" in body
        assert body["role"] == "admin"

    def test_login_wrong_password(self, client, session):
        from app.model.admin import AdminUser
        session.add(AdminUser(
            username="admin", hashed_password="hashed_123", role="admin",
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
            username="inactive", hashed_password="hashed_123",
            role="admin", is_active=False,
        ))
        session.commit()

        resp = client.post("/api/v1/admin/login", json={
            "username": "inactive", "password": "hashed_123",
        })
        assert resp.status_code == 401
