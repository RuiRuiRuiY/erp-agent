class TestSupplierPricelistAPI:
    def test_list_pricelists_success(self, client, seed_data):
        supplier_id = seed_data["suppliers"]["A"].id
        resp = client.get(f"/api/v1/suppliers/{supplier_id}/pricelists")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) >= 2
        for item in body:
            assert "id" in item
            assert "supplier_id" in item
            assert "product_id" in item
            assert "min_qty" in item
            assert "unit_price" in item
            assert "valid_from" in item
            assert isinstance(item["unit_price"], float)

    def test_list_pricelists_filter_by_product(self, client, seed_data):
        supplier_id = seed_data["suppliers"]["A"].id
        product_id = seed_data["products"]["mouse"].id
        resp = client.get(
            f"/api/v1/suppliers/{supplier_id}/pricelists",
            params={"product_id": product_id},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) >= 1
        for item in body:
            assert item["product_id"] == product_id

    def test_list_pricelists_no_match_filter(self, client, seed_data):
        supplier_id = seed_data["suppliers"]["A"].id
        resp = client.get(
            f"/api/v1/suppliers/{supplier_id}/pricelists",
            params={"product_id": "nonexistent-product"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_pricelists_supplier_not_found_404(self, client):
        resp = client.get("/api/v1/suppliers/nonexistent-supplier/pricelists")
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "RESOURCE_NOT_FOUND"

    def test_pricelist_unit_price_in_yuan(self, client, seed_data):
        supplier_id = seed_data["suppliers"]["B"].id
        resp = client.get(f"/api/v1/suppliers/{supplier_id}/pricelists")
        assert resp.status_code == 200
        body = resp.json()
        for item in body:
            assert item["unit_price"] > 0
