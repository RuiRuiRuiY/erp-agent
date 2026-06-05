"""
Sprint 1 / Day 5 . Task 5.4

S3 HITL 全流程终端模拟

模拟场景：超预算 -> 挂起 -> 注入 Token -> 恢复 -> 特批建单 -> 提交审批

用法:
    uv run python scripts/simulate_s3_hitl.py

无需外部依赖（mock-erp 不需要启动，HTTP 调用已 mock）。
"""
import asyncio
import json
import sys
from unittest.mock import patch

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from langgraph.types import Command
from langchain_core.messages import ToolMessage

from app.agent.state import AgentState
from app.agent.graph import graph

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
BOLD = "\033[1m"
RESET = "\033[0m"

passed = 0
failed = 0


def check(label: str, ok: bool):
    global passed, failed
    if ok:
        passed += 1
        print(f"  {PASS} {label}")
    else:
        failed += 1
        print(f"  {FAIL} {label}")


async def _mock_override_po(**kwargs) -> str:
    return json.dumps({
        "id": "po-override-001",
        "po_number": "PO-20260605-OVERRIDE",
        "status": "DRAFT",
        "total_amount": 5000.0,
        "is_override": True,
        "supplier_name": "Shenzhen Hongda Electronics",
        "department_name": "R&D",
        "lines": [
            {"product_id": "p003", "product_name": "Ergonomic Chair", "quantity": 10,
             "unit_price": 500.0, "line_total": 5000.0},
        ],
    })


async def _mock_transit_po(**kwargs) -> str:
    return json.dumps({
        "po_id": "po-override-001",
        "po_number": "PO-20260605-OVERRIDE",
        "old_status": "DRAFT",
        "new_status": "PENDING",
        "budget_impact": "Override bypasses budget check",
    })


async def main():
    global passed, failed
    thread_id = "sim-s3-hitl"
    config = {"configurable": {"thread_id": thread_id}}

    print()
    print("=" * 72)
    print("  S3 - HITL Approval Flow - End-to-End Simulation")
    print("=" * 72)
    print()

    # ================================================================
    # Step 1: Build initial state
    # ================================================================
    print("[Step 1] Build initial state")
    print("  Scenario: purchase order blocked by BUDGET_INSUFFICIENT")
    print()

    initial = AgentState(
        pending_approval_type="budget",
        override_token=None,
        department_id="dept_rd",
        selected_supplier_id="sup_c",
        cart_items=[
            {"product_id": "p003", "product_name": "Ergonomic Chair", "quantity": 10},
        ],
        messages=[ToolMessage(
            content=json.dumps({
                "_error": True,
                "error_code": "BUDGET_INSUFFICIENT",
                "context": {"required": 6000.0, "remaining": 5000.0, "deficit": 1000.0},
            }),
            tool_call_id="t1", name="draft_purchase_order",
        )],
    )

    check("pending_approval_type == 'budget'",
          initial.get("pending_approval_type") == "budget")
    check("override_token is None", initial.get("override_token") is None)
    check("has dept/supplier/items for PO creation",
          all([initial.get("department_id"),
               initial.get("selected_supplier_id"),
               initial.get("cart_items")]))

    print()

    # ================================================================
    # Step 2: Run graph -> budget_check -> hitl_gate -> interrupt
    # ================================================================
    print("[Step 2] Run graph (entry -> budget_check -> hitl_gate -> interrupt)")
    print()

    async for event in graph.astream(initial, config, stream_mode="updates"):
        for node, output in (event or {}).items():
            if node == "budget_check":
                msgs = output.get("messages", [])
                if msgs:
                    print(f"  [{node}] message published")
                if output.get("pending_approval_type") == "budget":
                    print(f"  [{node}] set pending_approval_type=budget")
            elif node == "hitl_gate":
                print(f"  [{node}] interrupt triggered, graph paused")

    state = await graph.aget_state(config)
    print()
    check("graph paused, pending_approval_type == 'budget'",
          state.values.get("pending_approval_type") == "budget")
    check("no PO Draft ID while paused",
          state.values.get("po_draft_id") is None)
    print()

    # ================================================================
    # Step 3: Show paused state
    # ================================================================
    print("[Step 3] Paused state (waiting for finance manager approval)")
    print(f"  thread_id:      {thread_id}")
    print(f"  pending_type:   {state.values.get('pending_approval_type')}")
    print(f"  department_id:  {state.values.get('department_id')}")
    print(f"  supplier_id:    {state.values.get('selected_supplier_id')}")
    print(f"  cart_items:     {state.values.get('cart_items')}")
    print()
    print("  -> Graph waiting for resume with override_token")
    print()

    # ================================================================
    # Step 4: Resume - inject override_token
    # ================================================================
    print("[Step 4] Resume - inject override_token")
    print("  Simulating finance manager approves via Feishu, agent receives token")
    print()

    resume_value = {"override_token": "override-secret-2025"}

    with (
        patch("app.agent.nodes.override_purchase_order", _mock_override_po),
        patch("app.agent.nodes.transit_po_status", _mock_transit_po),
    ):
        async for event in graph.astream(
            Command(resume=resume_value),
            config,
            stream_mode="updates",
        ):
            for node, output in (event or {}).items():
                if node == "hitl_gate":
                    print(f"  [{node}] received override_token, proceeding")
                elif node == "override_po":
                    print(f"  [{node}] created override PO -> {output.get('messages', [''])[-1]}")
                elif node == "transit_to_pending":
                    print(f"  [{node}] submitted for approval -> {output.get('messages', [''])[-1]}")
                elif node == "resume_cleanup":
                    print(f"  [{node}] state cleanup done")

    final = await graph.aget_state(config)
    print()

    # ================================================================
    # Step 5: Verification
    # ================================================================
    print("[Step 5] Verification")
    print()

    print("  -- Task 5.2: Override PO creation --")
    check("po_draft_id == 'po-override-001'",
          final.values.get("po_draft_id") == "po-override-001")
    check("po_status == 'PENDING'",
          final.values.get("po_status") == "PENDING")
    check("po_supplier_id == 'sup_c'",
          final.values.get("po_supplier_id") == "sup_c")
    print()

    print("  -- Task 5.3: Temp fields cleared --")
    check("override_token consumed (None)",
          final.values.get("override_token") is None)
    check("pending_approval_type cleared",
          final.values.get("pending_approval_type") is None)
    check("tier_suggestion cleared",
          final.values.get("tier_suggestion") is None)
    print()

    print("  -- Task 5.3: Business fields preserved --")
    check("department_id preserved",
          final.values.get("department_id") == "dept_rd")
    check("selected_supplier_id preserved",
          final.values.get("selected_supplier_id") == "sup_c")
    print()

    # ================================================================
    # Summary
    # ================================================================
    print("=" * 72)
    total = passed + failed
    if failed == 0:
        print(f"  {BOLD}Result: {passed}/{total} passed{RESET}")
        print("  S3 HITL full flow verification PASSED")
    else:
        print(f"  {BOLD}Result: {passed}/{total} passed, {failed} failed{RESET}")
        print("  Check failed items above")
    print("=" * 72)
    print()
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
