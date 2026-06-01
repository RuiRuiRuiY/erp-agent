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


class TestTransitPurchaseOrderAPI:
    def _create_po(self, client, seed_data) -> str:
        payload = {
            "department_id": seed_data["departments"]["IT"].id,
            "supplier_id": seed_data["suppliers"]["A"].id,
            "items": [
                {"product_id": seed_data["products"]["mouse"].id, "quantity": 5},
            ],
        }
        resp = client.post("/api/v1/po", json=payload)
        return resp.json()["id"]

    def test_transit_draft_to_pending(self, client, seed_data):
        po_id = self._create_po(client, seed_data)
        resp = client.post(f"/api/v1/po/{po_id}/transit", json={
            "target_status": "PENDING",
            "operator_role": "agent",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["old_status"] == "DRAFT"
        assert body["new_status"] == "PENDING"

    def test_transit_pending_to_approved(self, client, seed_data):
        po_id = self._create_po(client, seed_data)
        client.post(f"/api/v1/po/{po_id}/transit", json={
            "target_status": "PENDING", "operator_role": "agent",
        })
        resp = client.post(f"/api/v1/po/{po_id}/transit", json={
            "target_status": "APPROVED", "operator_role": "finance_manager",
        })
        assert resp.status_code == 200
        assert resp.json()["new_status"] == "APPROVED"
        assert "已扣减预算" in resp.json()["budget_impact"]

    def test_invalid_transition_returns_409(self, client, seed_data):
        po_id = self._create_po(client, seed_data)
        resp = client.post(f"/api/v1/po/{po_id}/transit", json={
            "target_status": "APPROVED",
            "operator_role": "agent",
        })
        assert resp.status_code == 409
        assert resp.json()["error_code"] == "INVALID_STATE_TRANSITION"

    def test_permission_denied_returns_403(self, client, seed_data):
        po_id = self._create_po(client, seed_data)
        client.post(f"/api/v1/po/{po_id}/transit", json={
            "target_status": "PENDING", "operator_role": "agent",
        })
        resp = client.post(f"/api/v1/po/{po_id}/transit", json={
            "target_status": "APPROVED", "operator_role": "agent",
        })
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "PERMISSION_DENIED"

    def test_nonexistent_po_returns_404(self, client):
        resp = client.post("/api/v1/po/nonexistent-id/transit", json={
            "target_status": "PENDING",
            "operator_role": "agent",
        })
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "RESOURCE_NOT_FOUND"


class TestOverridePurchaseOrderAPI:
    def test_override_success(self, client, seed_data):
        payload = {
            "department_id": seed_data["departments"]["RD"].id,
            "supplier_id": seed_data["suppliers"]["B"].id,
            "items": [
                {"product_id": seed_data["products"]["mouse"].id, "quantity": 53},
            ],
            "override_token": "override-secret-2025",
        }
        resp = client.post("/api/v1/po/override", json=payload)
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "DRAFT"
        assert body["po_number"].startswith("PO-")
        assert body["total_amount"] == 5035.0

    def test_override_invalid_token_returns_403(self, client, seed_data):
        payload = {
            "department_id": seed_data["departments"]["RD"].id,
            "supplier_id": seed_data["suppliers"]["B"].id,
            "items": [
                {"product_id": seed_data["products"]["chair"].id, "quantity": 1},
            ],
            "override_token": "wrong-token",
        }
        resp = client.post("/api/v1/po/override", json=payload)
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "PERMISSION_DENIED"

    def test_override_stock_insufficient_returns_409(self, client, seed_data):
        payload = {
            "department_id": seed_data["departments"]["RD"].id,
            "supplier_id": seed_data["suppliers"]["B"].id,
            "items": [
                {"product_id": seed_data["products"]["monitor"].id, "quantity": 10},
            ],
            "override_token": "override-secret-2025",
        }
        resp = client.post("/api/v1/po/override", json=payload)
        assert resp.status_code == 409
        assert resp.json()["error_code"] == "INSUFFICIENT_STOCK"

    def test_override_po_transit_skips_budget_recheck(self, client, seed_data):
        payload = {
            "department_id": seed_data["departments"]["RD"].id,
            "supplier_id": seed_data["suppliers"]["B"].id,
            "items": [
                {"product_id": seed_data["products"]["chair"].id, "quantity": 1},
            ],
            "override_token": "override-secret-2025",
        }
        resp = client.post("/api/v1/po/override", json=payload)
        po_id = resp.json()["id"]

        resp = client.post(f"/api/v1/po/{po_id}/transit", json={
            "target_status": "PENDING",
            "operator_role": "agent",
        })
        assert resp.status_code == 200
        assert resp.json()["old_status"] == "DRAFT"
        assert resp.json()["new_status"] == "PENDING"
