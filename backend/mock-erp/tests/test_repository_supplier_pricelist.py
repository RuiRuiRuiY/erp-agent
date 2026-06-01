from datetime import date, timedelta

from app.model.supplier_pricelist import SupplierPricelist
from app.repository.supplier_pricelist import (
    get_pricelists_by_product,
    get_pricelists_by_product_ids,
    get_pricelists_by_supplier,
    get_pricelists_by_supplier_and_products,
)


class TestActiveFilter:
    """验证 _active_filter 正确过滤过期/未来报价。"""

    def _add_expired_and_future(
        self, session, seed_data,
    ) -> dict[str, str]:
        sup = seed_data["suppliers"]["A"]
        prod = seed_data["products"]["mouse"]
        expired_id = None
        future_id = None

        past = (date.today() - timedelta(days=365)).isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        future = (date.today() + timedelta(days=365)).isoformat()

        expired = SupplierPricelist(
            supplier_id=sup.id, product_id=prod.id,
            min_qty=200, unit_price=5_000,
            valid_from=past, valid_to=yesterday,
        )
        session.add(expired)
        session.flush()
        expired_id = expired.id

        future_pl = SupplierPricelist(
            supplier_id=sup.id, product_id=prod.id,
            min_qty=300, unit_price=99_999,
            valid_from=future, valid_to=None,
        )
        session.add(future_pl)
        session.flush()
        future_id = future_pl.id

        session.commit()

        return {"expired_id": expired_id, "future_id": future_id}

    def test_expired_not_returned_by_supplier(self, session, seed_data):
        ids = self._add_expired_and_future(session, seed_data)
        sup_id = seed_data["suppliers"]["A"].id
        results = get_pricelists_by_supplier(session, sup_id)
        result_ids = {r.id for r in results}
        assert ids["expired_id"] not in result_ids
        assert ids["future_id"] not in result_ids

    def test_expired_not_returned_by_product(self, session, seed_data):
        ids = self._add_expired_and_future(session, seed_data)
        prod_id = seed_data["products"]["mouse"].id
        results = get_pricelists_by_product(session, prod_id)
        result_ids = {r.id for r in results}
        assert ids["expired_id"] not in result_ids
        assert ids["future_id"] not in result_ids

    def test_expired_not_returned_by_product_ids(self, session, seed_data):
        ids = self._add_expired_and_future(session, seed_data)
        prod_id = seed_data["products"]["mouse"].id
        results = get_pricelists_by_product_ids(session, [prod_id])
        result_ids = {r.id for r in results}
        assert ids["expired_id"] not in result_ids
        assert ids["future_id"] not in result_ids

    def test_expired_not_returned_by_supplier_and_products(self, session, seed_data):
        ids = self._add_expired_and_future(session, seed_data)
        sup_id = seed_data["suppliers"]["A"].id
        prod_id = seed_data["products"]["mouse"].id
        results = get_pricelists_by_supplier_and_products(session, sup_id, [prod_id])
        all_ids = set()
        for plist in results.values():
            all_ids.update(p.id for p in plist)
        assert ids["expired_id"] not in all_ids
        assert ids["future_id"] not in all_ids

    def test_valid_pricelists_still_returned(self, session, seed_data):
        ids = self._add_expired_and_future(session, seed_data)
        sup_id = seed_data["suppliers"]["A"].id
        results = get_pricelists_by_supplier(session, sup_id)
        assert len(results) >= 2
        result_ids = {r.id for r in results}
        assert ids["expired_id"] not in result_ids
        assert ids["future_id"] not in result_ids

    def test_mixed_data_only_valid(self, session, seed_data):
        sup = seed_data["suppliers"]["A"]
        prod = seed_data["products"]["mouse"]
        today = date.today().isoformat()
        valid = SupplierPricelist(
            supplier_id=sup.id, product_id=prod.id,
            min_qty=400, unit_price=7_500,
            valid_from=today, valid_to=None,
        )
        session.add(valid)
        session.commit()

        ids = self._add_expired_and_future(session, seed_data)
        results = get_pricelists_by_supplier(session, sup.id)
        result_ids = {r.id for r in results}
        assert valid.id in result_ids
        assert ids["expired_id"] not in result_ids
        assert ids["future_id"] not in result_ids
