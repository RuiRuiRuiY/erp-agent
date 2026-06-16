"""
Sprint 2 Task 2.2: 5 场景全链路端到端测试

生产模式图流程：mock LLM + mock tools → 完整图执行 → 验证最终状态
"""
import json
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from app.agent.graph import build_graph
from app.agent.state import AgentState
from tests.fixtures import make_mock_tools, make_mock_llm


def _get_final_msgs(final):
    """从 final state 提取所有消息的 content 列表。"""
    msgs = final.values.get("messages", [])
    return [getattr(m, "content", "") for m in msgs]


# ── S1: 常规采购 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_s1_regular_purchase_e2e():
    """S1: 用户消息 → parse_input → call_model(simulate) → analyze_simulate → present_options → END"""
    tools = make_mock_tools()
    mock_llm = make_mock_llm([
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

    with patch("app.agent.llm._get_llm", return_value=mock_llm):
        graph = await build_graph(tools=tools)
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
    tools = make_mock_tools(inventory_response=inventory_resp)
    mock_llm = make_mock_llm([
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

    with patch("app.agent.llm._get_llm", return_value=mock_llm):
        graph = await build_graph(tools=tools)
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
    tools = make_mock_tools(draft_response=draft_resp)
    mock_llm = make_mock_llm([
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

    with patch("app.agent.llm._get_llm", return_value=mock_llm):
        graph = await build_graph(tools=tools)
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
    tools = make_mock_tools(simulate_response=simulate_resp)
    mock_llm = make_mock_llm([
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

    with patch("app.agent.llm._get_llm", return_value=mock_llm), \
         patch("app.agent.nodes.erp_get", side_effect=mock_erp_get):
        graph = await build_graph(tools=tools)
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
    tools = make_mock_tools(simulate_response=simulate_resp)
    mock_llm = make_mock_llm([
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

    with patch("app.agent.llm._get_llm", return_value=mock_llm):
        graph = await build_graph(tools=tools)
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
    tools = make_mock_tools()
    # parse_input: intent=confirm → 不提取字段
    # call_model: 正常响应
    mock_llm = make_mock_llm([
        AIMessage(content='{"intent": "confirm"}\n用户确认继续当前采购流程'),
        AIMessage(content="继续当前采购流程"),
    ])

    with patch("app.agent.llm._get_llm", return_value=mock_llm):
        graph = await build_graph(tools=tools)
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


# ── S7: 会话重置 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_s7_reset_creates_new_thread_state():
    """S7: /reset 后使用新 thread_id → 状态清空，不受旧会话影响"""
    tools = make_mock_tools()

    mock_llm = make_mock_llm([
        AIMessage(content=json.dumps({
            "intent": "new_request",
            "department_id": "dept_sales",
            "cart_items": [{"product_id": "p001", "product_name": "显示器", "quantity": 2}],
        })),
        AIMessage(content="", tool_calls=[{
            "id": "call_s7_1", "name": "simulate_purchase",
            "args": {"department_id": "dept_sales", "items": [{"product_id": "p001", "quantity": 2}]},
        }]),
        AIMessage(content='{"has_tier_opportunity": false, "has_stock_risk": false}\n显示器报价正常'),
    ])

    with patch("app.agent.llm._get_llm", return_value=mock_llm):
        graph = await build_graph(tools=tools)

        # 模拟旧会话
        old_config = {"configurable": {"thread_id": "e2e-s7-old"}}
        old_initial = AgentState(
            messages=[HumanMessage(content="买显示器")],
            department_id="dept_it",
            cart_items=[{"product_id": "p001", "product_name": "显示器", "quantity": 3}],
        )
        async for _ in graph.astream(old_initial, old_config, stream_mode="updates"):
            pass

        # 模拟 /reset：新 thread_id + 全新初始状态
        new_thread_id = "e2e-s7-new"
        new_config = {"configurable": {"thread_id": new_thread_id}}
        new_initial = AgentState(
            messages=[HumanMessage(content="买椅子")],
            department_id="dept_sales",
            cart_items=[{"product_id": "p002", "product_name": "椅子", "quantity": 5}],
        )
        async for _ in graph.astream(new_initial, new_config, stream_mode="updates"):
            pass

    # 新会话独立：department_id 来自新会话，不被旧会话污染
    final = await graph.aget_state(new_config)
    assert final.values.get("department_id") == "dept_sales"
    assert len(final.values.get("cart_items", [])) == 1
    assert final.values["cart_items"][0]["product_id"] == "p002"
