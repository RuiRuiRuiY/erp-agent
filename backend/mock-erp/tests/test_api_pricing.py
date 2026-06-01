from fastapi.testclient import TestClient


class TestPricingAPI:
    """API 层集成测试，验证路由、参数校验、HTTP 状态码。"""

    def test_simulate_success(self, client: TestClient, seed_data):
        """POST /pricing/simulate 正常请求 → 200 + 完整响应结构。"""
        prod = seed_data["products"]
        dept = seed_data["departments"]["IT"]

        resp = client.post(
            "/api/v1/pricing/simulate",
            json={
                "department_id": dept.id,
                "items": [
                    {"product_id": prod["mouse"].id, "quantity": 5},
                    {"product_id": prod["monitor"].id, "quantity": 2},
                ],
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert "department_remaining_budget" in body
        assert "all_quotes" in body
        assert "recommended_supplier_id" in body
        assert "recommendation_reason" in body
        assert "skipped_suppliers" in body
        assert len(body["all_quotes"]) > 0
        assert body["recommended_supplier_id"] is not None

        for quote in body["all_quotes"]:
            assert "default_lead_time_days" in quote
            assert "rating" in quote
            assert isinstance(quote["default_lead_time_days"], int)
            assert isinstance(quote["rating"], float)

    def test_empty_items_returns_422(self, client: TestClient):
        """items 为空列表 → 422 Unprocessable Entity。"""
        resp = client.post(
            "/api/v1/pricing/simulate",
            json={
                "department_id": "any",
                "items": [],
            },
        )
        assert resp.status_code == 422

    def test_quantity_zero_returns_422(self, client: TestClient, seed_data):
        """quantity=0 → Pydantic gt=0 校验 → 422。"""
        prod = seed_data["products"]
        resp = client.post(
            "/api/v1/pricing/simulate",
            json={
                "department_id": "any",
                "items": [
                    {"product_id": prod["mouse"].id, "quantity": 0},
                ],
            },
        )
        assert resp.status_code == 422

    def test_unknown_product_returns_404(self, client: TestClient, seed_data):
        """不存在的 product_id → ResourceNotFoundError → 404。"""
        resp = client.post(
            "/api/v1/pricing/simulate",
            json={
                "department_id": seed_data["departments"]["IT"].id,
                "items": [
                    {"product_id": "non-existent-id", "quantity": 1},
                ],
            },
        )
        assert resp.status_code == 404
        body = resp.json()
        assert body["error_code"] == "RESOURCE_NOT_FOUND"

    def test_unknown_department_returns_404(self, client: TestClient, seed_data):
        """不存在的 department_id → ResourceNotFoundError → 404。"""
        prod = seed_data["products"]
        resp = client.post(
            "/api/v1/pricing/simulate",
            json={
                "department_id": "non-existent-dept",
                "items": [
                    {"product_id": prod["mouse"].id, "quantity": 1},
                ],
            },
        )
        assert resp.status_code == 404
        body = resp.json()
        assert body["error_code"] == "RESOURCE_NOT_FOUND"

    def test_response_structure_contains_skipped(self, client: TestClient, seed_data):
        """响应中包含 skipped_suppliers 字段。"""
        prod = seed_data["products"]
        resp = client.post(
            "/api/v1/pricing/simulate",
            json={
                "department_id": seed_data["departments"]["IT"].id,
                "items": [
                    {"product_id": prod["monitor"].id, "quantity": 1},
                ],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["skipped_suppliers"], list)
        if body["skipped_suppliers"]:
            entry = body["skipped_suppliers"][0]
            assert "supplier_id" in entry
            assert "supplier_name" in entry
            assert "reason" in entry
