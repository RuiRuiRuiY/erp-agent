import pytest
from app.core.exceptions import (
    BudgetInsufficientError,
    BusinessException,
    PricingTierNotFoundError,
    ResourceNotFoundError,
)
from app.repository.budget import get_budget_by_department_id
from app.repository.inventory import get_inventory_by_product_id
from app.schema.purchase_order import POCreateItem, POCreateRequest
from app.service.purchase_order import create_purchase_order


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
