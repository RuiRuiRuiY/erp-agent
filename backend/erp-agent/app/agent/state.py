from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages

from app.agent.schemas import AnalysisResult


class CartItem(TypedDict):
    product_id: str
    product_name: str
    quantity: int


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    thread_id: str
    session_id: str
    next_node: str

    department_id: str
    cart_items: list[CartItem]
    selected_supplier_id: str | None
    supplier_choice_prompted: bool

    simulate_result: dict
    po_draft_id: str | None
    po_status: str | None
    po_supplier_id: str | None

    override_token: str | None
    operator_role: str
    action_source: str
    pending_approval_type: str | None

    tier_suggestion: str | None

    user_intent: str | None
    analysis_result: AnalysisResult | None
    alternative_products: list | None

    error_context: dict | None
    recovery_attempted: bool
    recovery_path: str | None
