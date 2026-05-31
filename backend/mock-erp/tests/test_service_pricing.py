import pytest
from app.core.exceptions import ResourceNotFoundError
from app.schema.pricing import SimulateRequest, SimulateRequestItem
from app.service.pricing import simulate_pricing
from sqlmodel import Session


class TestSimulatePricingService:
    """Service 层试算引擎测试，覆盖正常逻辑及业务陷阱场景。"""

    def test_basic_multiple_products_from_two_suppliers(self, session: Session, seed_data):
        """正常比价：多商品 x 多供应商，全部可 fulfill，推荐总价最低的。"""
        prod = seed_data["products"]
        req = SimulateRequest(
            department_id=seed_data["departments"]["IT"].id,
            items=[
                SimulateRequestItem(product_id=prod["mouse"].id, quantity=5),
                SimulateRequestItem(product_id=prod["monitor"].id, quantity=2),
            ],
        )
        resp = simulate_pricing(session, req)

        assert len(resp.all_quotes) == 2

        quotes = {q.supplier_name: q for q in resp.all_quotes}
        sup_a = quotes["深圳宏达电子"]
        sup_b = quotes["上海极速科技"]

        assert sup_a.can_fulfill is True
        assert sup_b.can_fulfill is True

        assert sup_a.total_amount < sup_b.total_amount
        assert resp.recommended_supplier_id == seed_data["suppliers"]["A"].id
        assert len(resp.skipped_suppliers) == 1
        assert "高于推荐供应商" in resp.skipped_suppliers[0].reason

    def test_tier_matching_differs_by_quantity(self, session: Session, seed_data):
        """阶梯价命中：买 90 个鼠标命中 1-99 阶梯，买 100 个命中 100+ 阶梯。"""
        prod = seed_data["products"]
        sup = seed_data["suppliers"]

        req_90 = SimulateRequest(
            department_id=seed_data["departments"]["IT"].id,
            items=[SimulateRequestItem(product_id=prod["mouse"].id, quantity=90)],
        )
        resp_90 = simulate_pricing(session, req_90)

        req_100 = SimulateRequest(
            department_id=seed_data["departments"]["IT"].id,
            items=[SimulateRequestItem(product_id=prod["mouse"].id, quantity=100)],
        )
        resp_100 = simulate_pricing(session, req_100)

        quote_90 = next(q for q in resp_90.all_quotes if q.supplier_id == sup["A"].id)
        quote_100 = next(q for q in resp_100.all_quotes if q.supplier_id == sup["A"].id)

        assert quote_90.line_details[0].hit_tier_min_qty == 1
        assert quote_90.line_details[0].unit_price == 100.0
        assert quote_90.total_amount == 9000.0

        assert quote_100.line_details[0].hit_tier_min_qty == 100
        assert quote_100.line_details[0].unit_price == 80.0
        assert quote_100.total_amount == 8000.0

    def test_partial_fulfill(self, session: Session, seed_data):
        """部分可 fulfill：某供应商缺一个商品的阶梯，can_fulfill 标记正确。"""
        prod = seed_data["products"]
        sup = seed_data["suppliers"]

        req = SimulateRequest(
            department_id=seed_data["departments"]["IT"].id,
            items=[
                SimulateRequestItem(product_id=prod["chair"].id, quantity=5),
                SimulateRequestItem(product_id=prod["mouse"].id, quantity=1),
            ],
        )
        resp = simulate_pricing(session, req)

        quotes = {q.supplier_id: q for q in resp.all_quotes}
        assert quotes[sup["A"].id].can_fulfill is False
        assert quotes[sup["B"].id].can_fulfill is True

    def test_none_fulfill(self, session: Session, seed_data):
        """全部无 fulfill：引入一个无报价的商品，没有任何供应商能全部满足。"""
        prod = seed_data["products"]
        req = SimulateRequest(
            department_id=seed_data["departments"]["IT"].id,
            items=[
                SimulateRequestItem(product_id=prod["mouse"].id, quantity=5),
                SimulateRequestItem(product_id=prod["server_no_pricelist"].id, quantity=1),
            ],
        )
        resp = simulate_pricing(session, req)

        assert resp.recommended_supplier_id is None
        assert resp.recommendation_reason == "无供应商可满足全部采购需求"

    def test_recommended_supplier_is_lowest_price(self, session: Session, seed_data):
        """推荐算法验证：仅基于价格维度，总是推荐总价最低的供应商。"""
        prod = seed_data["products"]
        req = SimulateRequest(
            department_id=seed_data["departments"]["IT"].id,
            items=[SimulateRequestItem(product_id=prod["monitor"].id, quantity=1)],
        )
        resp = simulate_pricing(session, req)

        assert resp.recommended_supplier_id == seed_data["suppliers"]["A"].id

    def test_skipped_suppliers_detail(self, session: Session, seed_data):
        """skipped_suppliers 字段正确填充了跳过的供应商及其原因。"""
        prod = seed_data["products"]
        req = SimulateRequest(
            department_id=seed_data["departments"]["IT"].id,
            items=[SimulateRequestItem(product_id=prod["monitor"].id, quantity=1)],
        )
        resp = simulate_pricing(session, req)

        assert len(resp.skipped_suppliers) == 1
        assert resp.skipped_suppliers[0].supplier_name == "上海极速科技"
        assert "高于推荐供应商" in resp.skipped_suppliers[0].reason

    def test_unknown_product_raises_error(self, session: Session, seed_data):
        """不存在的 product_id：Repository 层抛 ResourceNotFoundError。"""
        req = SimulateRequest(
            department_id=seed_data["departments"]["IT"].id,
            items=[SimulateRequestItem(product_id="nonexistent-id", quantity=1)],
        )
        with pytest.raises(ResourceNotFoundError):
            simulate_pricing(session, req)

    def test_unknown_department_raises_error(self, session: Session, seed_data):
        """不存在的 department_id：Repository 层抛 ResourceNotFoundError。"""
        prod = seed_data["products"]
        req = SimulateRequest(
            department_id="nonexistent-dept",
            items=[SimulateRequestItem(product_id=prod["mouse"].id, quantity=1)],
        )
        with pytest.raises(ResourceNotFoundError):
            simulate_pricing(session, req)

    def test_budget_calculation_correct(self, session: Session, seed_data):
        """预算计算校验：department_remaining_budget 正确。"""
        prod = seed_data["products"]
        dept_rd = seed_data["departments"]["RD"]

        budget_total = 50_000_00
        budget_used = 45_000_00
        expected_remaining = (budget_total - budget_used) / 100.0

        req = SimulateRequest(
            department_id=dept_rd.id,
            items=[SimulateRequestItem(product_id=prod["mouse"].id, quantity=1)],
        )
        resp = simulate_pricing(session, req)

        assert resp.department_remaining_budget == expected_remaining

    def test_single_product_single_supplier(self, session: Session, seed_data):
        """单一商品单一供应商，推荐明确。"""
        prod = seed_data["products"]
        req = SimulateRequest(
            department_id=seed_data["departments"]["IT"].id,
            items=[SimulateRequestItem(product_id=prod["mouse"].id, quantity=3)],
        )
        resp = simulate_pricing(session, req)

        assert len(resp.all_quotes) == 2
        assert resp.recommended_supplier_id is not None
        assert resp.recommendation_reason is not None

    # ── 阶梯价凑单陷阱验证 ──

    def test_trap_ladder_pricing(self, session: Session, seed_data):
        """陷阱：买 90 鼠标（100元/个） vs 买 100 鼠标（80元/个），引擎如实返回差异。"""
        prod = seed_data["products"]
        sup = seed_data["suppliers"]

        req_90 = SimulateRequest(
            department_id=seed_data["departments"]["IT"].id,
            items=[SimulateRequestItem(product_id=prod["mouse"].id, quantity=90)],
        )
        resp_90 = simulate_pricing(session, req_90)

        req_100 = SimulateRequest(
            department_id=seed_data["departments"]["IT"].id,
            items=[SimulateRequestItem(product_id=prod["mouse"].id, quantity=100)],
        )
        resp_100 = simulate_pricing(session, req_100)

        sup_a_90 = next(q for q in resp_90.all_quotes if q.supplier_id == sup["A"].id)
        sup_a_100 = next(q for q in resp_100.all_quotes if q.supplier_id == sup["A"].id)

        assert sup_a_90.total_amount == 9000.0
        assert sup_a_100.total_amount == 8000.0
        assert sup_a_100.total_amount < sup_a_90.total_amount

    # ── 价格 vs 交期陷阱验证 ──

    def test_trap_price_vs_leadtime(self, session: Session, seed_data):
        """陷阱：戴尔显示器 SUP_A（1000元/15天）vs SUP_B（1200元/2天），引擎推荐价格低的。"""
        prod = seed_data["products"]
        req = SimulateRequest(
            department_id=seed_data["departments"]["IT"].id,
            items=[SimulateRequestItem(product_id=prod["monitor"].id, quantity=1)],
        )
        resp = simulate_pricing(session, req)

        assert resp.recommended_supplier_id == seed_data["suppliers"]["A"].id
        assert resp.recommendation_reason is not None

    # ── 预算红线陷阱验证 ──

    def test_trap_budget_red_line(self, session: Session, seed_data):
        """陷阱：研发部余额 5000 元，采购 600x10=6000 元椅子，引擎如实返回预算和报价。"""
        prod = seed_data["products"]
        dept_rd = seed_data["departments"]["RD"]

        req = SimulateRequest(
            department_id=dept_rd.id,
            items=[SimulateRequestItem(product_id=prod["chair"].id, quantity=10)],
        )
        resp = simulate_pricing(session, req)

        assert resp.department_remaining_budget == 5000.0
        chair_quote = next(
            q for q in resp.all_quotes if q.supplier_id == seed_data["suppliers"]["B"].id
        )
        assert chair_quote.line_details[0].unit_price == 600.0
        assert chair_quote.total_amount == 6000.0
