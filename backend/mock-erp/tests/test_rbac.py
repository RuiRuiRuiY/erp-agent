"""Sprint 3 Task 1.3: 视图级 RBAC 测试"""


class TestDashboardRBAC:
    def test_finance_can_see_purchase_orders(self, client, session):
        """财务经理可以看到采购单页面"""
        from app.model.admin import AdminUser
        session.add(AdminUser(
            username="finance", hashed_password="pw", role="finance_manager",
        ))
        session.commit()

        # 登录获取 token
        resp = client.post("/api/v1/admin/login", json={
            "username": "finance", "password": "pw",
        })
        token = resp.json()["token"]

        # 带 token 访问采购单页面
        resp = client.get("/admin/purchase-order/list", cookies={"session": token})
        assert resp.status_code == 200

    def test_purchaser_cannot_see_admin_users(self, client, session):
        """采购员不能看到管理员用户页面"""
        from app.model.admin import AdminUser
        session.add(AdminUser(
            username="buyer", hashed_password="pw", role="purchaser",
        ))
        session.commit()

        resp = client.post("/api/v1/admin/login", json={
            "username": "buyer", "password": "pw",
        })
        token = resp.json()["token"]

        # 采购员访问管理员用户页面应被拒绝
        resp = client.get("/admin/admin-user/list", cookies={"session": token})
        assert resp.status_code in (302, 403, 401)

    def test_unauthenticated_cannot_see_admin(self, client):
        """未登录不能访问管控台（应重定向到登录页）"""
        resp = client.get("/admin/product/list", follow_redirects=False)
        # 未认证应重定向到登录页
        assert resp.status_code == 302
        assert "login" in resp.headers.get("location", "")
