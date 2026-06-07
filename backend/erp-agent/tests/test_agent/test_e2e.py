"""
Sprint 2 Task 2.2: 5 场景全链路端到端测试

生产模式图流程：mock LLM + mock tools → 完整图执行 → 验证最终状态
"""
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.types import Command

from app.agent.graph import build_graph
from app.agent.state import AgentState


# ── 工具工厂 ──────────────────────────────────────────────────────────────


def _make_tools(*, simulate_response=None, draft_response=None, inventory_response=None):
    """创建 mock 工具集，simulate/draft/inventory 可按场景覆盖。"""

    @tool(description="搜索商品列表")
    async def search_product(q: str = "", product_id: str = "") -> str:
        return json.dumps([{"id": "p001", "name": "显示器", "sku": "MON-001"}])

    @tool(description="查询部门预算")
    async def check_budget(department_id: str = "") -> str:
        return json.dumps({
            "department_id": department_id,
            "total_budget": 100000.0, "used_budget": 50000.0, "available": 50000.0,
        })

    @tool(description="查询库存")
    async def check_inventory(product_id: str = "") -> str:
        if inventory_response:
            return inventory_response
        return json.dumps({"product_id": product_id, "total_qty": 20, "available_qty": 20})

    @tool(description="模拟采购试算")
    async def simulate_purchase(department_id: str = "", items: Any = "[]") -> str:
        if simulate_response:
            return simulate_response
        item_list = json.loads(items) if isinstance(items, str) else items
        total = sum(1000.0 * i.get("quantity", 1) for i in item_list)
        return json.dumps({
            "department_remaining_budget": 50000.0,
            "all_quotes": [{
                "supplier_id": "sup_a", "supplier_name": "深圳宏达电子",
                "default_lead_time_days": 15, "rating": 4.5, "total_amount": total,
                "line_details": [{"product_id": i.get("product_id", "p001"), "product_name": "显示器",
                                  "quantity": i.get("quantity", 1), "unit_price": 1000.0,
                                  "subtotal": 1000.0 * i.get("quantity", 1)} for i in item_list],
            }],
        })

    @tool(description="创建采购单")
    async def draft_purchase_order(
        department_id: str = "", supplier_id: str = "",
        items: Any = "[]", agent_reasoning: str = "",
    ) -> str:
        if draft_response:
            return draft_response
        return json.dumps({"id": "po-001", "po_number": "PO-20260607-001", "status": "DRAFT", "total_amount": 5000.0})

    return [search_product, check_budget, check_inventory, simulate_purchase, draft_purchase_order]


def _mock_llm_factory(responses):
    """创建 mock LLM，responses 是按调用顺序返回的 AIMessage 列表。"""
    call_idx = [0]

    async def mock_ainvoke(messages, **kwargs):
        idx = min(call_idx[0], len(responses) - 1)
        call_idx[0] += 1
        return responses[idx]

    mock_llm = MagicMock()
    mock_llm.ainvoke = mock_ainvoke
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    return mock_llm


def _get_final_msgs(final):
    """从 final state 提取所有消息的 content 列表。"""
    msgs = final.values.get("messages", [])
    return [getattr(m, "content", "") for m in msgs]


# ── S1: 常规采购 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_s1_regular_purchase_e2e():
    """S1: 用户消息 → parse_input → call_model(simulate) → analyze_simulate → present_options → END"""
    tools = _make_tools()
    mock_llm = _mock_llm_factory([
        AIMessage(content=json.dumps({
            "intent": "new_request",
            "department_id": "dept_it",
            "cart_items": [{"product_id": "p001", "product_name": "显示器", "quantity": 5}],
        })),
        AIMessage(content="", tool_calls=[{
            "id": "call_001", "name": "simulate_purchase",
            "args": {"department_id": "dept_it", "items": [{"product_id": "p001", "quantity": 5}]},
        }]),
        AIMessage(content='{"has_tier_opportunity": false, "has_stock_risk": false}\n单供应商报价，无阶梯价机会，库存充足'),
    ])

    with patch("app.agent.graph._get_llm", return_value=mock_llm):
        graph = build_graph(tools=tools)
        initial = AgentState(messages=[HumanMessage(content="买5台显示器给IT部")])
        config = {"configurable": {"thread_id": "e2e-s1"}}

        async for _ in graph.astream(initial, config, stream_mode="updates"):
            pass

    final = await graph.aget_state(config)
    assert final.values.get("department_id") == "dept_it"
    assert final.values.get("cart_items")
    contents = _get_final_msgs(final)
    assert any("供应商选项" in c for c in contents), f"应展示供应商选项, got: {contents}"


# ── S2: 库存不足 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_s2_insufficient_stock_e2e():
    """S2: inventory 返回 INSUFFICIENT_STOCK → stock_error → recovery"""
    inventory_resp = json.dumps({
        "_error": True, "error_code": "INSUFFICIENT_STOCK", "action": "self_heal",
        "context": {"product_id": "p003", "requested": 10, "available": 5},
    })
    tools = _make_tools(inventory_response=inventory_resp)
    mock_llm = _mock_llm_factory([
        AIMessage(content=json.dumps({
            "intent": "new_request",
            "department_id": "dept_it",
            "cart_items": [{"product_id": "p003", "product_name": "椅子", "quantity": 10}],
        })),
        AIMessage(content="", tool_calls=[{
            "id": "call_002", "name": "check_inventory",
            "args": {"product_id": "p003"},
        }]),
    ])

    with patch("app.agent.graph._get_llm", return_value=mock_llm):
        graph = build_graph(tools=tools)
        initial = AgentState(
            messages=[HumanMessage(content="买10把椅子")],
            department_id="dept_it",
            cart_items=[{"product_id": "p003", "product_name": "椅子", "quantity": 10}],
        )
        config = {"configurable": {"thread_id": "e2e-s2"}}

        async for _ in graph.astream(initial, config, stream_mode="updates"):
            pass

    final = await graph.aget_state(config)
    assert final.values.get("recovery_attempted") is True
    assert final.values.get("recovery_path") == "reduce_qty"
    contents = _get_final_msgs(final)
    assert any("库存不足" in c for c in contents), f"应提示库存不足, got: {contents}"


# ── S3: HITL 审批 ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_s3_hitl_approval_e2e():
    """S3: draft → BUDGET_INSUFFICIENT → budget_check → hitl_gate (interrupt) → resume → override → END"""
    draft_resp = json.dumps({
        "_error": True, "error_code": "BUDGET_INSUFFICIENT", "action": "request_override",
        "context": {"required": 6000.0, "remaining": 5000.0, "deficit": 1000.0},
    })
    tools = _make_tools(draft_response=draft_resp)
    mock_llm = _mock_llm_factory([
        AIMessage(content=json.dumps({
            "intent": "new_request",
            "department_id": "dept_rd",
            "cart_items": [{"product_id": "p003", "product_name": "椅子", "quantity": 10}],
        })),
        AIMessage(content="", tool_calls=[{
            "id": "call_003", "name": "draft_purchase_order",
            "args": {"department_id": "dept_rd", "supplier_id": "sup_c",
                     "items": [{"product_id": "p003", "quantity": 10}]},
        }]),
    ])

    with patch("app.agent.graph._get_llm", return_value=mock_llm):
        graph = build_graph(tools=tools)
        initial = AgentState(
            messages=[HumanMessage(content="为研发部买10把椅子")],
            department_id="dept_rd",
            selected_supplier_id="sup_c",
            cart_items=[{"product_id": "p003", "product_name": "椅子", "quantity": 10}],
        )
        config = {"configurable": {"thread_id": "e2e-s3"}}

        # Step 1: 运行到 hitl_gate interrupt
        async for _ in graph.astream(initial, config, stream_mode="updates"):
            pass

        state = await graph.aget_state(config)
        assert state.values.get("pending_approval_type") == "budget", \
            f"应挂起, got: {state.values}"

        # Step 2: resume with override_token
        with (
            patch("app.agent.nodes.override_purchase_order", AsyncMock(return_value=json.dumps({
                "id": "po-override-s3", "po_number": "PO-S3-001",
                "status": "DRAFT", "total_amount": 6000.0, "is_override": True,
            }))),
            patch("app.agent.nodes.transit_po_status", AsyncMock(return_value=json.dumps({
                "po_id": "po-override-s3", "po_number": "PO-S3-001",
                "old_status": "DRAFT", "new_status": "PENDING",
            }))),
        ):
            async for _ in graph.astream(
                Command(resume={"override_token": "override-secret-2025"}),
                config, stream_mode="updates",
            ):
                pass

    final = await graph.aget_state(config)
    assert final.values.get("po_draft_id") == "po-override-s3"
    assert final.values.get("po_status") == "PENDING"
    assert final.values.get("override_token") is None
    assert final.values.get("action_source") == "human"


# ── S4: 阶梯凑单 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_s4_tiered_pricing_e2e():
    """S4: simulate 返回阶梯价报价 → analyze → tier_suggest → 凑单建议"""
    simulate_resp = json.dumps({
        "department_remaining_budget": 50000.0,
        "all_quotes": [{
            "supplier_id": "sup_c", "supplier_name": "广州万通商贸",
            "default_lead_time_days": 7, "rating": 4.8, "total_amount": 8000.0,
            "line_details": [{"product_id": "p004", "product_name": "Logitech Mouse",
                              "quantity": 80, "unit_price": 100.0, "subtotal": 8000.0}],
        }],
    })
    tools = _make_tools(simulate_response=simulate_resp)
    mock_llm = _mock_llm_factory([
        AIMessage(content=json.dumps({
            "intent": "new_request",
            "department_id": "dept_it",
            "cart_items": [{"product_id": "p004", "product_name": "鼠标", "quantity": 80}],
        })),
        AIMessage(content="", tool_calls=[{
            "id": "call_004", "name": "simulate_purchase",
            "args": {"department_id": "dept_it", "items": [{"product_id": "p004", "quantity": 80}]},
        }]),
        AIMessage(content='{"has_tier_opportunity": true, "has_stock_risk": false}\n有阶梯价机会：80个×100元 vs 100个×80元'),
    ])

    async def mock_erp_get(path, params=None):
        if "/pricelists" in path:
            return [
                {"min_qty": 1, "unit_price": 100.0},
                {"min_qty": 100, "unit_price": 80.0},
            ]
        return []

    with patch("app.agent.graph._get_llm", return_value=mock_llm), \
         patch("app.agent.nodes.erp_get", side_effect=mock_erp_get):
        graph = build_graph(tools=tools)
        initial = AgentState(
            messages=[HumanMessage(content="买80个鼠标给IT部")],
            department_id="dept_it",
            cart_items=[{"product_id": "p004", "product_name": "鼠标", "quantity": 80}],
        )
        config = {"configurable": {"thread_id": "e2e-s4"}}

        async for _ in graph.astream(initial, config, stream_mode="updates"):
            pass

    final = await graph.aget_state(config)
    ts = final.values.get("tier_suggestion", "")
    assert ts, f"应生成凑单建议, got: {final.values}"
    assert "100" in ts, f"建议应提及 100 个阶梯, got: {ts}"


# ── S5: 综合寻源 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_s5_multi_supplier_e2e():
    """S5: simulate 返回多供应商报价 → analyze → present_options → 展示对比"""
    simulate_resp = json.dumps({
        "department_remaining_budget": 50000.0,
        "all_quotes": [
            {"supplier_id": "sup_a", "supplier_name": "深圳宏达电子",
             "default_lead_time_days": 15, "rating": 4.5, "total_amount": 2250.0,
             "line_details": [{"product_id": "p005", "quantity": 5, "unit_price": 450.0, "subtotal": 2250.0}]},
            {"supplier_id": "sup_c", "supplier_name": "广州万通商贸",
             "default_lead_time_days": 7, "rating": 4.8, "total_amount": 2500.0,
             "line_details": [{"product_id": "p005", "quantity": 5, "unit_price": 500.0, "subtotal": 2500.0}]},
        ],
    })
    tools = _make_tools(simulate_response=simulate_resp)
    mock_llm = _mock_llm_factory([
        AIMessage(content=json.dumps({
            "intent": "new_request",
            "department_id": "dept_it",
            "cart_items": [{"product_id": "p005", "product_name": "键盘", "quantity": 5}],
        })),
        AIMessage(content="", tool_calls=[{
            "id": "call_005", "name": "simulate_purchase",
            "args": {"department_id": "dept_it", "items": [{"product_id": "p005", "quantity": 5}]},
        }]),
        AIMessage(content='{"has_tier_opportunity": false, "has_stock_risk": false}\n多供应商报价，各有优势：SUP_A价格低，SUP_C交期快评分高'),
    ])

    with patch("app.agent.graph._get_llm", return_value=mock_llm):
        graph = build_graph(tools=tools)
        initial = AgentState(
            messages=[HumanMessage(content="买5个键盘")],
            department_id="dept_it",
            cart_items=[{"product_id": "p005", "product_name": "键盘", "quantity": 5}],
        )
        config = {"configurable": {"thread_id": "e2e-s5"}}

        async for _ in graph.astream(initial, config, stream_mode="updates"):
            pass

    final = await graph.aget_state(config)
    contents = _get_final_msgs(final)
    assert any("供应商选项" in c for c in contents), f"应展示供应商选项, got: {contents}"


# ── S6: 模糊输入 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_s6_fuzzy_input_preserves_state():
    """S6: 模糊输入（'就按这个来'）→ intent=confirm → 沿用当前 State"""
    tools = _make_tools()
    # parse_input: intent=confirm → 不提取字段
    # call_model: 正常响应
    mock_llm = _mock_llm_factory([
        AIMessage(content='{"intent": "confirm"}\n用户确认继续当前采购流程'),
        AIMessage(content="继续当前采购流程"),
    ])

    with patch("app.agent.graph._get_llm", return_value=mock_llm):
        graph = build_graph(tools=tools)
        initial = AgentState(
            messages=[HumanMessage(content="就按这个来")],
            department_id="dept_it",
            cart_items=[{"product_id": "p001", "product_name": "显示器", "quantity": 5}],
        )
        config = {"configurable": {"thread_id": "e2e-s6"}}

        async for _ in graph.astream(initial, config, stream_mode="updates"):
            pass

    final = await graph.aget_state(config)
    # parse_input 返回 user_intent + messages，不覆盖 department_id / cart_items
    assert final.values.get("department_id") == "dept_it"
    assert len(final.values.get("cart_items", [])) == 1
