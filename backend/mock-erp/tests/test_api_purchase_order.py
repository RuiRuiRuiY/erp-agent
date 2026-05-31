class TestCreatePurchaseOrderAPI:
    def test_success(self, client, seed_data):
        payload = {
            "department_id": seed_data["departments"]["IT"].id,
            "supplier_id": seed_data["suppliers"]["A"].id,
            "items": [
                {"product_id": seed_data["products"]["mouse"].id, "quantity": 5},
            ],
        }
        resp = client.post("/api/v1/po", json=payload)
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "DRAFT"
        assert body["po_number"].startswith("PO-")
        assert body["total_amount"] == 500.0
        assert len(body["lines"]) == 1
        assert body["lines"][0]["line_total"] == 500.0
        assert body["created_by_agent"] is False

    def test_empty_items_returns_422(self, client, seed_data):
        payload = {
            "department_id": seed_data["departments"]["IT"].id,
            "supplier_id": seed_data["suppliers"]["A"].id,
            "items": [],
        }
        resp = client.post("/api/v1/po", json=payload)
        assert resp.status_code == 422

    def test_invalid_supplier_returns_404(self, client, seed_data):
        payload = {
            "department_id": seed_data["departments"]["IT"].id,
            "supplier_id": "no-such-supplier",
            "items": [
                {"product_id": seed_data["products"]["mouse"].id, "quantity": 1},
            ],
        }
        resp = client.post("/api/v1/po", json=payload)
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "RESOURCE_NOT_FOUND"

    def test_invalid_department_returns_404(self, client, seed_data):
        payload = {
            "department_id": "no-such-dept",
            "supplier_id": seed_data["suppliers"]["A"].id,
            "items": [
                {"product_id": seed_data["products"]["mouse"].id, "quantity": 1},
            ],
        }
        resp = client.post("/api/v1/po", json=payload)
        assert resp.status_code == 404

    def test_budget_insufficient_returns_409(self, client, seed_data):
        payload = {
            "department_id": seed_data["departments"]["RD"].id,
            "supplier_id": seed_data["suppliers"]["B"].id,
            "items": [
                {"product_id": seed_data["products"]["chair"].id, "quantity": 9},
            ],
        }
        resp = client.post("/api/v1/po", json=payload)
        assert resp.status_code == 409
        assert resp.json()["error_code"] == "BUDGET_INSUFFICIENT"

    def test_stock_insufficient_returns_409(self, client, seed_data):
        payload = {
            "department_id": seed_data["departments"]["IT"].id,
            "supplier_id": seed_data["suppliers"]["A"].id,
            "items": [
                {"product_id": seed_data["products"]["monitor"].id, "quantity": 10},
            ],
        }
        resp = client.post("/api/v1/po", json=payload)
        assert resp.status_code == 409
        assert resp.json()["error_code"] == "INSUFFICIENT_STOCK"
