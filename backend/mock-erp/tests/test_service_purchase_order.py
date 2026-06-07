import pytest
from app.core.exceptions import (
    BudgetInsufficientError,
    BusinessException,
    InvalidStateTransitionError,
    PermissionDeniedError,
    PricingTierNotFoundError,
    ResourceNotFoundError,
)
from app.repository.budget import get_budget_by_department_id
from app.repository.inventory import get_inventory_by_product_id
from app.schema.purchase_order import POCreateItem, POCreateOverrideRequest, POCreateRequest
from app.service.purchase_order import (
    create_purchase_order,
    create_purchase_order_override,
    transit_po,
)


class TestCreatePurchaseOrder:
    def test_success(self, session, seed_data):
        req = POCreateRequest(
            department_id=seed_data["departments"]["IT"].id,
            supplier_id=seed_data["suppliers"]["A"].id,
            items=[
                POCreateItem(product_id=seed_data["products"]["mouse"].id, quantity=5),
            ],
        )
        result = create_purchase_order(session, req)

        assert result.status == "DRAFT"
        assert result.po_number.startswith("PO-")
        assert result.supplier_name == "深圳宏达电子"
        assert result.department_name == "IT 部"
        assert result.total_amount == 500.0
        assert len(result.lines) == 1
        assert result.lines[0].product_name == "罗技无线鼠标"
        assert result.lines[0].quantity == 5
        assert result.lines[0].unit_price == 100.0
        assert result.lines[0].line_total == 500.0

    def test_agent_reasoning_recorded(self, session, seed_data):
        req = POCreateRequest(
            department_id=seed_data["departments"]["IT"].id,
            supplier_id=seed_data["suppliers"]["A"].id,
            items=[
                POCreateItem(product_id=seed_data["products"]["mouse"].id, quantity=5),
            ],
            agent_reasoning="cheapest option",
        )
        result = create_purchase_order(session, req)

        assert result.created_by_agent is True
        assert result.agent_reasoning == "cheapest option"

    def test_budget_and_stock_updated(self, session, seed_data):
        req = POCreateRequest(
            department_id=seed_data["departments"]["IT"].id,
            supplier_id=seed_data["suppliers"]["A"].id,
            items=[
                POCreateItem(product_id=seed_data["products"]["mouse"].id, quantity=5),
            ],
        )
        create_purchase_order(session, req)

        budget = get_budget_by_department_id(session, seed_data["departments"]["IT"].id)
        assert budget.frozen_budget == 50_000

        inv = get_inventory_by_product_id(session, seed_data["products"]["mouse"].id)
        assert inv.locked_qty == 5

    def test_budget_insufficient(self, session, seed_data):
        req = POCreateRequest(
            department_id=seed_data["departments"]["RD"].id,
            supplier_id=seed_data["suppliers"]["B"].id,
            items=[
                POCreateItem(product_id=seed_data["products"]["chair"].id, quantity=9),
            ],
        )
        with pytest.raises(BudgetInsufficientError) as exc:
            create_purchase_order(session, req)
        assert exc.value.context["required"] == 540_000
        assert exc.value.context["remaining"] == 500_000

    def test_stock_insufficient(self, session, seed_data):
        req = POCreateRequest(
            department_id=seed_data["departments"]["IT"].id,
            supplier_id=seed_data["suppliers"]["A"].id,
            items=[
                POCreateItem(product_id=seed_data["products"]["monitor"].id, quantity=10),
            ],
        )
        with pytest.raises(BusinessException) as exc:
            create_purchase_order(session, req)
        assert exc.value.error_code == "INSUFFICIENT_STOCK"

    def test_no_pricing_tier(self, session, seed_data):
        req = POCreateRequest(
            department_id=seed_data["departments"]["IT"].id,
            supplier_id=seed_data["suppliers"]["A"].id,
            items=[
                POCreateItem(product_id=seed_data["products"]["chair"].id, quantity=5),
            ],
        )
        with pytest.raises(PricingTierNotFoundError):
            create_purchase_order(session, req)

    def test_unknown_supplier(self, session, seed_data):
        req = POCreateRequest(
            department_id=seed_data["departments"]["IT"].id,
            supplier_id="nonexistent-supplier",
            items=[
                POCreateItem(product_id=seed_data["products"]["mouse"].id, quantity=1),
            ],
        )
        with pytest.raises(ResourceNotFoundError) as exc:
            create_purchase_order(session, req)
        assert exc.value.context["resource"] == "Supplier"

    def test_unknown_department(self, session, seed_data):
        req = POCreateRequest(
            department_id="nonexistent-dept",
            supplier_id=seed_data["suppliers"]["A"].id,
            items=[
                POCreateItem(product_id=seed_data["products"]["mouse"].id, quantity=1),
            ],
        )
        with pytest.raises(ResourceNotFoundError) as exc:
            create_purchase_order(session, req)
        assert exc.value.context["resource"] == "Department"

    def test_unknown_product(self, session, seed_data):
        req = POCreateRequest(
            department_id=seed_data["departments"]["IT"].id,
            supplier_id=seed_data["suppliers"]["A"].id,
            items=[
                POCreateItem(product_id="nonexistent-product", quantity=1),
            ],
        )
        with pytest.raises(ResourceNotFoundError) as exc:
            create_purchase_order(session, req)
        assert exc.value.context["resource"] == "Product"


class TestTransitPurchaseOrder:
    """DRAFT 创建时已冻结合约——transit 只做重新校验和状态变更。"""

    def _create_po(self, session, seed_data, department_key="IT", supplier_key="A",
                   product_key="mouse", qty=5) -> str:
        req = POCreateRequest(
            department_id=seed_data["departments"][department_key].id,
            supplier_id=seed_data["suppliers"][supplier_key].id,
            items=[POCreateItem(product_id=seed_data["products"][product_key].id, quantity=qty)],
        )
        return create_purchase_order(session, req).id

    def test_draft_to_pending(self, session, seed_data):
        po_id = self._create_po(session, seed_data)
        result = transit_po(session, po_id, "PENDING", "purchaser")

        assert result.old_status == "DRAFT"
        assert result.new_status == "PENDING"
        assert result.budget_impact is None

        budget = get_budget_by_department_id(session, seed_data["departments"]["IT"].id)
        assert budget.frozen_budget == 50_000  # unchanged from creation

    def test_draft_to_cancelled(self, session, seed_data):
        po_id = self._create_po(session, seed_data)
        result = transit_po(session, po_id, "CANCELLED", "purchaser")

        assert result.old_status == "DRAFT"
        assert result.new_status == "CANCELLED"
        assert "已释放冻结预算" in result.budget_impact

        budget = get_budget_by_department_id(session, seed_data["departments"]["IT"].id)
        assert budget.frozen_budget == 0  # unfrozen

        inv = get_inventory_by_product_id(session, seed_data["products"]["mouse"].id)
        assert inv.locked_qty == 0

    def test_pending_to_approved(self, session, seed_data):
        po_id = self._create_po(session, seed_data)
        transit_po(session, po_id, "PENDING", "purchaser")
        result = transit_po(session, po_id, "APPROVED", "finance_manager")

        assert result.new_status == "APPROVED"
        assert "已扣减预算" in result.budget_impact

        budget = get_budget_by_department_id(session, seed_data["departments"]["IT"].id)
        assert budget.frozen_budget == 0
        assert budget.used_budget == 50_000

        inv = get_inventory_by_product_id(session, seed_data["products"]["mouse"].id)
        assert inv.total_qty == 195
        assert inv.locked_qty == 0

    def test_pending_to_rejected(self, session, seed_data):
        po_id = self._create_po(session, seed_data)
        transit_po(session, po_id, "PENDING", "purchaser")
        result = transit_po(session, po_id, "REJECTED", "finance_manager")

        assert result.new_status == "REJECTED"
        assert "已释放冻结预算" in result.budget_impact

        budget = get_budget_by_department_id(session, seed_data["departments"]["IT"].id)
        assert budget.frozen_budget == 0

    def test_pending_to_cancelled(self, session, seed_data):
        po_id = self._create_po(session, seed_data)
        transit_po(session, po_id, "PENDING", "purchaser")
        result = transit_po(session, po_id, "CANCELLED", "purchaser")

        assert result.new_status == "CANCELLED"
        assert "已释放冻结预算" in result.budget_impact

    def test_rejected_to_draft(self, session, seed_data):
        po_id = self._create_po(session, seed_data)
        transit_po(session, po_id, "PENDING", "purchaser")
        transit_po(session, po_id, "REJECTED", "finance_manager")
        result = transit_po(session, po_id, "DRAFT", "purchaser")

        assert result.new_status == "DRAFT"
        assert result.budget_impact is None

    def test_approved_to_cancelled(self, session, seed_data):
        po_id = self._create_po(session, seed_data)
        transit_po(session, po_id, "PENDING", "purchaser")
        transit_po(session, po_id, "APPROVED", "finance_manager")
        result = transit_po(session, po_id, "CANCELLED", "purchaser")

        assert result.new_status == "CANCELLED"
        assert "已退回预算" in result.budget_impact

        budget = get_budget_by_department_id(session, seed_data["departments"]["IT"].id)
        assert budget.used_budget == 0

        inv = get_inventory_by_product_id(session, seed_data["products"]["mouse"].id)
        assert inv.total_qty == 200  # restored

    def test_full_lifecycle(self, session, seed_data):
        po_id = self._create_po(session, seed_data)
        transit_po(session, po_id, "PENDING", "purchaser")
        transit_po(session, po_id, "APPROVED", "finance_manager")
        transit_po(session, po_id, "ORDERED", "purchaser")
        transit_po(session, po_id, "SHIPPED", "purchaser")
        result = transit_po(session, po_id, "RECEIVED", "purchaser")

        assert result.new_status == "RECEIVED"

    def test_invalid_transition(self, session, seed_data):
        po_id = self._create_po(session, seed_data)
        with pytest.raises(InvalidStateTransitionError) as exc:
            transit_po(session, po_id, "APPROVED", "purchaser")
        assert exc.value.context["current_status"] == "DRAFT"
        assert exc.value.context["target_status"] == "APPROVED"

    def test_permission_denied(self, session, seed_data):
        po_id = self._create_po(session, seed_data)
        transit_po(session, po_id, "PENDING", "purchaser")
        with pytest.raises(PermissionDeniedError) as exc:
            transit_po(session, po_id, "APPROVED", "purchaser")
        assert exc.value.context["required_role"] == "finance_manager"

    def test_recheck_budget_insufficient(self, session, seed_data):
        po_id = self._create_po(session, seed_data, department_key="RD",
                                supplier_key="B", product_key="chair", qty=3)
        budget = get_budget_by_department_id(session, seed_data["departments"]["RD"].id)
        budget.used_budget = 4_900_000
        session.add(budget)
        session.flush()

        with pytest.raises(BudgetInsufficientError) as exc:
            transit_po(session, po_id, "PENDING", "purchaser")
        assert exc.value.context["required"] == 180_000

    def test_recheck_stock_insufficient(self, session, seed_data):
        po_id = self._create_po(session, seed_data, product_key="monitor", qty=3)
        inv = get_inventory_by_product_id(session, seed_data["products"]["monitor"].id)
        inv.locked_qty = 3
        session.add(inv)
        session.flush()

        with pytest.raises(BusinessException) as exc:
            transit_po(session, po_id, "PENDING", "purchaser")
        assert exc.value.error_code == "INSUFFICIENT_STOCK"


class TestCreatePurchaseOrderOverride:
    def test_override_success_budget_insufficient_dept(self, session, seed_data):
        req = POCreateOverrideRequest(
            department_id=seed_data["departments"]["RD"].id,
            supplier_id=seed_data["suppliers"]["B"].id,
            items=[
                POCreateItem(product_id=seed_data["products"]["mouse"].id, quantity=53),
            ],
            override_token="override-secret-2025",
        )
        result = create_purchase_order_override(session, req)

        assert result.status == "DRAFT"
        assert result.total_amount == 5035.0
        assert result.created_by_agent is False

        budget = get_budget_by_department_id(session, seed_data["departments"]["RD"].id)
        assert budget.frozen_budget == 503_500

    def test_override_invalid_token(self, session, seed_data):
        req = POCreateOverrideRequest(
            department_id=seed_data["departments"]["RD"].id,
            supplier_id=seed_data["suppliers"]["B"].id,
            items=[
                POCreateItem(product_id=seed_data["products"]["chair"].id, quantity=1),
            ],
            override_token="wrong-token",
        )
        with pytest.raises(PermissionDeniedError) as exc:
            create_purchase_order_override(session, req)
        assert exc.value.context["required_role"] == "valid override_token"

    def test_override_stock_insufficient_still_fails(self, session, seed_data):
        req = POCreateOverrideRequest(
            department_id=seed_data["departments"]["IT"].id,
            supplier_id=seed_data["suppliers"]["A"].id,
            items=[
                POCreateItem(product_id=seed_data["products"]["monitor"].id, quantity=10),
            ],
            override_token="override-secret-2025",
        )
        with pytest.raises(BusinessException) as exc:
            create_purchase_order_override(session, req)
        assert exc.value.error_code == "INSUFFICIENT_STOCK"

    def test_override_no_pricing_tier_still_fails(self, session, seed_data):
        req = POCreateOverrideRequest(
            department_id=seed_data["departments"]["IT"].id,
            supplier_id=seed_data["suppliers"]["A"].id,
            items=[
                POCreateItem(product_id=seed_data["products"]["chair"].id, quantity=5),
            ],
            override_token="override-secret-2025",
        )
        with pytest.raises(PricingTierNotFoundError):
            create_purchase_order_override(session, req)


class TestTransitOverridePurchaseOrder:
    def _create_override_po(self, session, seed_data) -> str:
        req = POCreateOverrideRequest(
            department_id=seed_data["departments"]["RD"].id,
            supplier_id=seed_data["suppliers"]["B"].id,
            items=[
                POCreateItem(product_id=seed_data["products"]["chair"].id, quantity=1),
            ],
            override_token="override-secret-2025",
        )
        return create_purchase_order_override(session, req).id

    def test_override_skips_budget_recheck(self, session, seed_data):
        po_id = self._create_override_po(session, seed_data)
        result = transit_po(session, po_id, "PENDING", "purchaser")

        assert result.old_status == "DRAFT"
        assert result.new_status == "PENDING"

        budget = get_budget_by_department_id(session, seed_data["departments"]["RD"].id)
        assert budget.frozen_budget == 60_000

    def test_override_stock_check_still_enforced(self, session, seed_data):
        po_id = self._create_override_po(session, seed_data)
        inv = get_inventory_by_product_id(session, seed_data["products"]["chair"].id)
        inv.locked_qty = 5
        session.add(inv)
        session.flush()

        with pytest.raises(BusinessException) as exc:
            transit_po(session, po_id, "PENDING", "purchaser")
        assert exc.value.error_code == "INSUFFICIENT_STOCK"

    def test_normal_po_transit_still_fails_budget_check(self, session, seed_data):
        req = POCreateRequest(
            department_id=seed_data["departments"]["RD"].id,
            supplier_id=seed_data["suppliers"]["B"].id,
            items=[
                POCreateItem(product_id=seed_data["products"]["chair"].id, quantity=1),
            ],
        )
        po_id = create_purchase_order(session, req).id
        budget = get_budget_by_department_id(session, seed_data["departments"]["RD"].id)
        budget.used_budget = 4_940_000
        session.add(budget)
        session.flush()

        with pytest.raises(BudgetInsufficientError) as exc:
            transit_po(session, po_id, "PENDING", "purchaser")
        assert exc.value.context["required"] == 60_000
