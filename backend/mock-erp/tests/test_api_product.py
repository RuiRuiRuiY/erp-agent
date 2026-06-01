class TestProductSearchAPI:
    def test_search_hit_by_name(self, client, seed_data):
        resp = client.get("/api/v1/products", params={"q": "鼠标"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) >= 1
        assert any("鼠标" in p["name"] for p in body)

    def test_search_hit_by_category(self, client, seed_data):
        resp = client.get("/api/v1/products", params={"q": "外设"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) >= 1
        assert all(p["category"] == "外设" for p in body)

    def test_search_no_result(self, client, seed_data):
        resp = client.get("/api/v1/products", params={"q": "XX不存在"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_search_empty_q_backward_compat(self, client, seed_data):
        resp = client.get("/api/v1/products")
        assert resp.status_code == 200
        body_all = resp.json()
        assert len(body_all) >= 3

        resp2 = client.get("/api/v1/products", params={"q": ""})
        assert resp2.status_code == 200
        assert resp2.json() == body_all

    def test_search_pagination_still_works(self, client, seed_data):
        resp = client.get("/api/v1/products", params={"q": "鼠", "limit": 1})
        assert resp.status_code == 200
        assert len(resp.json()) == 1
