# ERP-Agent 技术架构设计文档 (V1.0)

**文档版本**：V1.0
**对应版本**：PRD V6.0
**核心组件**：LangGraph, MCP Server, Chainlit, PostgreSQL (Checkpointer)

---

## 一、LangGraph 节点图

### 混合架构：ToolNode + 显式业务节点

生产模式下，LangGraph 使用 **ToolNode 统一执行 MCP 工具**，**显式业务节点负责逻辑判断与用户交互**：

```mermaid
flowchart TD
    start([用户输入]) --> parse_input[parse_input\nLLM 提取意图/部门/商品]
    parse_input --> call_model[call_model\nLLM 决定调用哪些工具]
    call_model -->|有工具调用| tool_node[ToolNode\n执行 MCP 工具]
    call_model -->|无工具调用| END([结束])

    tool_node --> route_after_tools{route_after_tools\n检查工具结果}

    route_after_tools -->|工具返回错误| stock_error[stock_error\n库存不足处理]
    route_after_tools -->|预算透支| budget_check[budget_check\n预算检查]
    route_after_tools -->|有试算结果| analyze_simulate[analyze_simulate\nLLM 分析试算]
    route_after_tools -->|其他情况| call_model

    analyze_simulate --> route_after_analysis{route_after_analysis\n分析结果路由}

    route_after_analysis -->|发现阶梯价| tier_suggest[tier_suggest\n凑单建议]
    route_after_analysis -->|库存风险| show_alternatives[show_alternatives\n展示替代方案]
    route_after_analysis -->|正常| present_options[present_options\n展示供应商选项]
    route_after_analysis -->|需进一步工具| call_model

    tier_suggest --> present_options
    show_alternatives --> user_resolve[user_resolve\ninterrupt 等待用户选择]
    user_resolve -->|用户选择后| call_model

    present_options --> route_after_user_choice{route_after_user_choice\n用户选择路由}

    route_after_user_choice -->|确认下单| confirm_and_submit[confirm_and_submit\n创建采购单]
    route_after_user_choice -->|重新试算| call_model

    confirm_and_submit --> END

    stock_error --> END

    subgraph hitl [HITL 审批流]
        budget_check --> hitl_gate[hitl_gate\ninterrupt 挂起]
        hitl_gate --> override_po[override_po\n特批建单]
        override_po --> transit_to_pending[transit_to_pending\nDRAFT→PENDING]
        transit_to_pending --> resume_cleanup[resume_cleanup\n状态清理]
    end
    resume_cleanup --> END
```

### 测试模式

测试模式跳过 LLM，直接按 state 字段路由到业务节点：

```mermaid
flowchart TD
    start([测试输入]) --> entry[entry\n空操作]
    entry --> _test_route{_test_route\n按 state 路由}

    _test_route -->|error_context 存在| stock_error
    _test_route -->|simulate_result 存在| tier_suggest
    _test_route -->|pending_approval_type=budget| budget_check
    _test_route -->|其他| route_after_tools

    stock_error --> END
    tier_suggest --> END
    budget_check --> hitl_gate
    hitl_gate --> override_po
    override_po --> transit_to_pending
    transit_to_pending --> resume_cleanup
    resume_cleanup --> END
```

### 节点定义

#### 核心节点（生产模式）

| 节点名 | 类型 | 职责 | 调用 MCP 工具 |
|--------|------|------|---------------|
| `parse_input` | LLM | 从用户自然语言提取 department, product, quantity, intent | 无 |
| `call_model` | LLM | 绑定 tools，让 LLM 决定调用哪些 MCP 工具 | 无（LLM 自动选择） |
| `tool_node` | ToolNode | 统一执行 LLM 选中的 MCP 工具 | 所有 MCP 工具 |
| `analyze_simulate` | LLM | 分析试算结果，判断阶梯价、库存风险、供应商差异 | 无 |
| `present_options` | LLM | 格式化展示供应商选项，等待用户选择 | 无 |
| `confirm_and_submit` | MCP | 最终确认后调用 draft_purchase_order 创建采购单 | `draft_purchase_order` |

#### 异常处理节点

| 节点名 | 类型 | 职责 | 调用 MCP 工具 |
|--------|------|------|---------------|
| `stock_error` | LLM | 解析 INSUFFICIENT_STOCK 错误，生成替代方案 | 无 |
| `show_alternatives` | LLM | 展示替代商品方案 | `GET /products`（搜索替代品） |
| `user_resolve` | Interrupt | interrupt() 等待用户选择恢复方案 | 无 |
| `tier_suggest` | LLM | 检测阶梯价格差距，生成凑单建议 | `GET /suppliers/{id}/pricelists` |
| `budget_check` | LLM | 处理预算不足，设 pending_approval_type | 无 |

#### HITL 审批节点

| 节点名 | 类型 | 职责 | 调用 MCP 工具 |
|--------|------|------|---------------|
| `hitl_gate` | Interrupt | interrupt() 挂起等待 override_token | 无 |
| `override_po` | MCP | resume 后调用 override_purchase_order 创建特批采购单 | `override_purchase_order` |
| `transit_to_pending` | MCP | 将特批 PO 从 DRAFT 流转到 PENDING | `transit_po_status` |
| `resume_cleanup` | LLM | 恢复后状态清理，清除已被消费的临时字段 | 无 |

### 路由条件

```
route_after_tools:
  工具返回 _error + action=self_heal    → stock_error
  工具返回 _error + action=request_override → budget_check
  工具返回 all_quotes                    → analyze_simulate
  工具返回 available < 0                 → budget_check
  其他                                    → call_model

route_after_analysis:
  has_tier_opportunity=true              → tier_suggest
  has_stock_risk=true                    → show_alternatives
  分析结果含 all_quotes                  → present_options
  其他                                   → call_model

route_after_user_choice:
  状态含 selected_supplier_id + cart_items → confirm_and_submit
  其他                                    → call_model

_test_route (测试模式):
  error_context 存在                     → stock_error
  simulate_result 存在                   → tier_suggest
  pending_approval_type=budget           → budget_check
  其他                                   → route_after_tools
```

---

## 二、AgentState 完整定义

```python
from typing import Annotated, TypedDict
from operator import add

class CartItem(TypedDict):
    product_id: str
    product_name: str
    quantity: int

class AgentState(TypedDict):
    # --- LangGraph 核心 ---
    messages: Annotated[list, add_messages]   # 对话历史
    thread_id: str                            # LangGraph 线程 ID (绑定 Langfuse)
    session_id: str                           # 用户会话 ID
    next_node: str                            # 当前/下一节点名 (debug & trace)

    # --- 业务上下文 ---
    department_id: str                        # 提取出的部门 ID
    cart_items: list[CartItem]                # 用户意图采购的商品清单
    selected_supplier_id: str | None          # 用户选择的供应商 ID
    supplier_choice_prompted: bool            # 是否已向用户展示供应商选项

    # --- 试算与建单 ---
    simulate_result: dict                     # 试算引擎返回的裁剪后数据
    po_draft_id: str | None                   # 创建的草稿单 ID
    po_status: str | None                     # 当前 PO 生命周期状态
    po_supplier_id: str | None                # PO 关联的供应商 ID

    # --- HITL / 审批 ---
    override_token: str | None                # 人类提供的特批 Token
    operator_role: str                        # 操作者角色: agent / finance_manager
    pending_approval_type: str | None         # 挂起类型: override / transit_approve

    # --- 智能分析 ---
    tier_suggestion: str | None               # 阶梯凑单建议文本
    user_intent: str | None                   # parse_input 提取的用户意图
    analysis_result: dict | None              # analyze_simulate 的分析结果
    alternative_products: list | None         # show_alternatives 的替代商品列表

    # --- 错误自愈 ---
    error_context: dict | None                # 捕获的结构化错误
    recovery_attempted: bool                  # 是否已尝试过自动恢复
    recovery_path: str | None                 # 恢复路径: reduce_qty / change_product / override
```

---

## 三、MCP Server 结构

### 3.0 MCP vs 传统 Function Calling

选择 MCP 而非 LLM 原生的 function calling（如 OpenAI `tools` 参数），核心考量：

| 维度 | 传统 Function Calling | MCP Server（本项目的选择） |
|------|----------------------|--------------------------|
| 工具定义位置 | 混在 Agent 代码中（`@tool` 装饰器 或 OpenAI `tools` 参数） | 独立进程，基于 `FastMCP` + `@mcp.tool` 装饰器，通过 `langchain-mcp-adapters` 的 `MultiServerMCPClient` 连接 |
| 调用方式 | Agent 直调 Python 函数（内存内） | Agent → `MultiServerMCPClient` → stdio/HTTP → FastMCP Server |
| 部署耦合 | 工具与 Agent 同进程，改工具需重新部署 Agent | MCP Server 可独立部署/更新，Agent 无需重启 |
| 协议标准 | 无统一协议，绑定特定 LLM 厂商 | JSON-RPC 2.0 标准化协议，任何 MCP Client 都可复用 |
| 工具复用 | 只服务于当前 Agent | 同一套工具可同时被 Claude Desktop、VS Code、LangGraph Agent 等消费 |
| 安全边界 | 工具代码与 Agent 共享内存空间 | 进程隔离 + 拦截器矩阵 + `operator_role` 硬编码 |
| 工程复杂度 | 低（函数定义即可） | 高（需维护 MCP Server 进程、stdio 传输、错误包装） |
| 面试展示价值 | "我用了 function calling"（常规操作） | "我用了 MCP Server 做工具层解耦 + 进程隔离 + 多 Client 复用"（架构亮点） |

**结论**：本项目的 10 个工具都是 ERP 业务工具（搜索、预算、报价、建单），天然适合独立部署。MCP 的进程隔离架构也让越权拦截（`operator_role`、`override_token`）有了清晰的实施位置——在 MCP Server 层做，Agent 层不需要碰。

### 3.1 架构

```
┌─────────────────────────────────────────────┐
│              LangGraph Agent                 │
│  (app/agent/mcp_client.py:                    │
│   MultiServerMCPClient → get_tools())         │
└─────────────────┬───────────────────────────┘
                  │ MCP 协议 (JSON-RPC over stdio/HTTP)
┌─────────────────▼───────────────────────────┐
│           FastMCP Server                     │
│  (app/mcp/server.py: @mcp.tool x 10)         │
│  ┌─────────────────────────────────────┐     │
│  │  工具函数 (内部调用)                  │     │
│  │  - pruning.py: 响应裁剪               │     │
│  │  - interceptor.py: 越权拦截+错误包装   │     │
│  │  - client.py: httpx → Mock-ERP       │     │
│  └─────────────────────────────────────┘     │
├──────────────────────────────────────────────┤
│  ┌─ 可被其他 MCP Client 复用 ─────────────┐   │
│  │  Claude Desktop / VS Code / 其他 Agent │   │
│  └────────────────────────────────────────┘   │
└─────────────────┬───────────────────────────┘
                  │ HTTP REST
┌─────────────────▼───────────────────────────┐
│         Mock-ERP (FastAPI + SQLite)           │
│  /api/v1/products, /pricing/simulate, /po... │
└─────────────────────────────────────────────┘
```

### 3.2 Pruning 实现策略

Pruning 在 `@mcp.tool` 函数体内调用 `pruning.py` 的工具函数执行，而非外部 wrapper。每个工具函数先调用 `client.py` 获取原始响应，再调用对应的 prune 函数裁剪后返回。

```python
# MCP 响应裁剪伪代码

def prune_simulate_response(raw: dict) -> dict:
    """裁剪 simulate_purchase 响应 (预计 Token 缩减 80%)"""
    result = {}
    # 1. 预算信息完整保留
    result["department_remaining_budget"] = raw["department_remaining_budget"]
    # 2. 推荐供应商完整保留
    rec = raw["recommended_supplier"]
    result["recommended"] = {
        "name": rec["supplier_name"],
        "total": rec["total_amount"],
        "lead_time": rec["default_lead_time_days"],
        "rating": rec["rating"],
        "details": [
            {"product": d["product_name"], "qty": d["quantity"],
             "unit_price": d["unit_price"], "subtotal": d["subtotal"]}
            for d in rec["line_details"]
        ]
    }
    # 3. 其他供应商: 仅保留摘要 (总价 + 交期 + 评分)
    result["alternatives"] = [
        {
            "name": q["supplier_name"],
            "total": q["total_amount"],
            "lead_time": q["default_lead_time_days"],
            "rating": q["rating"],
            "count": len(q["line_details"]),
        }
        for q in raw["all_quotes"]
        if q["supplier_id"] != raw["recommended_supplier_id"]
    ]
    # 4. skipped 原因完整保留
    result["skipped_reasons"] = [
        f'{s["supplier_name"]}: {s["reason"]}'
        for s in raw.get("skipped_suppliers", [])
    ]
    return result
```

### 3.3 越权拦截矩阵

| MCP 工具                    | 拦截点               | 拦截逻辑                                                          |
| ------------------------- | ----------------- | ------------------------------------------------------------- |
| `draft_purchase_order`    | `agent_reasoning` | 校验字段非空且长度 > 20 字符，否则返回校验失败                                    |
| `override_purchase_order` | `override_token`  | LLM 不可传入此参数，由 MCP 从运行时上下文注入                                   |
| `transit_po_status`       | `operator_role`   | 来源是 Agent → 固定 `"agent"`；来源是 HITL 回调 → 固定 `"finance_manager"` |
| `search_product`          | 查询范围              | 仅允许 `q` 参数，禁止传入 SQL/注入参数                                      |

---

## 四、Chainlit HITL 集成

### 4.1 架构概览

Chainlit 提供开箱即用的对话式 UI，与 LangGraph 的 `interrupt`/`resume` 机制天然集成：

```mermaid
sequenceDiagram
    participant User as 用户 (Chainlit UI)
    participant CL as Chainlit
    participant Agent as LangGraph Agent
    participant MCP as MCP Server
    participant ERP as Mock-ERP

    User->>CL: 发送消息 "买 5 台显示器给 IT 部"
    CL->>Agent: invoke(graph, state)
    Agent->>MCP: search_product / simulate...
    MCP->>ERP: API 调用
    ERP-->>MCP: 响应
    MCP-->>Agent: 裁剪后响应
    Agent->>Agent: check_budget → 预算不足
    Agent->>Agent: interrupt(hitl_gate) → 挂起
    Agent-->>CL: 返回挂起状态
    CL-->>User: AskActionMessage "预算超标，是否申请特批？"

    User->>CL: 点击 "批准"
    CL->>Agent: Command(resume=True, override_token=xxx)
    Agent->>MCP: override_purchase_order
    MCP->>ERP: POST /po/override
    ERP-->>MCP: PO 创建成功
    MCP-->>Agent: 成功
    Agent-->>CL: 返回最终结果
    CL-->>User: "特批已通过，采购单已提交"
```

### 4.2 核心集成模式

```python
import chainlit as cl
from langgraph.graph import StateGraph
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command

# 编译图 (带 checkpointer)
# TODO: Sprint 2 — 切换为 interrupt_before=["hitl_gate"] 替代节点内 interrupt()
checkpointer = PostgresSaver.from_conn_string(DATABASE_URL)
graph = build_graph(checkpointer=checkpointer)

@cl.on_chat_start
async def on_start():
    cl.user_session.set("thread_id", str(uuid4()))

@cl.on_message
async def on_message(message: cl.Message):
    thread_id = cl.user_session.get("thread_id")
    config = {"configurable": {"thread_id": thread_id}}

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=message.content)]},
        config
    )

    # 检查是否触发 HITL
    if result.get("pending_approval"):
        action = await cl.AskActionMessage(
            content=f"预算超标 {result['deficit']} 元，是否申请特批？",
            actions=[
                cl.Action(name="approve", label="批准特批"),
                cl.Action(name="reject", label="拒绝")
            ]
        ).send()

        if action["name"] == "approve":
            await graph.ainvoke(Command(resume=True), config)

    await cl.Message(content=result["final_reply"]).send()
```

### 4.3 角色切换机制

通过 Chainlit 命令实现单人多角色测试，无需复杂的身份伪装：

```python
@cl.on_message
async def on_message(message: cl.Message):
    # 角色切换命令
    if message.content.startswith("/role"):
        role = message.content.split()[1]
        cl.user_session.set("operator_role", role)
        await cl.Message(content=f"已切换到角色: {role}").send()
        return

    # 正常消息处理...
    operator_role = cl.user_session.get("operator_role", "agent")
    # 将 operator_role 注入到 state 中
```

---

## 五、Langfuse 埋点方案

### 5.1 Trace 结构

每次 Agent 执行作为一个 Trace，内部节点作为 Spans：

```
Trace: session_id (用户会话) / thread_id (LangGraph 线程)
├── Span: parse_input           → LLM 调用 (提取意图)
├── Span: call_model            → LLM 调用 (决定工具调用)
├── Span: ToolNode              → MCP 工具执行 (search_product / check_budget / simulate_purchase...)
│   ├── Span: HTTP request      → mock-erp API
│   └── Span: pruning           → 响应裁剪 (记录原始大小 vs 裁剪后大小)
├── Span: analyze_simulate      → LLM 调用 (分析试算结果)
├── Span: present_options       → 格式化展示供应商选项
├── Span: confirm_and_submit    → MCP: draft_purchase_order
│   ├── Span: HTTP request
│   └── Span: error_intercept   → 如果捕获到异常
└── Span: total                 → 汇总
```

### 5.2 关键观测指标

```python
# FastMCP 工具函数内直接埋点
from langfuse.decorators import observe
from app.mcp.client import erp_client
from app.mcp.pruning import prune_simulate_response

@observe(name="simulate_purchase", capture_input=True, capture_output=True)
@mcp.tool
async def simulate_purchase(product_id: str, quantity: int) -> dict:
    """试算采购价格与阶梯报价"""
    raw = await erp_client.post("/api/v1/pricing/simulate", json={
        "product_id": product_id, "quantity": quantity
    })
    # @observe 自动记录 raw 和 pruned 的 token 消耗
    pruned = prune_simulate_response(raw)
    return pruned
```

---

## 六、PO 状态映射

| Agent State `po_status` | Mock-ERP `PurchaseOrder.status` | Agent 可执行的操作                                    | 需 operator_role     |
| ----------------------- | ------------------------------- | ----------------------------------------------- | ------------------- |
| `null`                  | 无 PO                            | `draft_purchase_order`                          | agent               |
| `DRAFT`                 | `DRAFT`                         | `transit_po_status`→PENDING/CANCELLED           | agent               |
| `PENDING`               | `PENDING`                       | `transit_po_status`→APPROVED/REJECTED/CANCELLED | **finance_manager** |
| `APPROVED`              | `APPROVED`                      | `transit_po_status`→ORDERED/CANCELLED           | agent               |
| `ORDERED`               | `ORDERED`                       | `transit_po_status`→SHIPPED/CANCELLED           | agent               |
| `SHIPPED`               | `SHIPPED`                       | `transit_po_status`→RECEIVED/CANCELLED          | agent               |
| `REJECTED`              | `REJECTED`                      | `transit_po_status`→DRAFT                       | agent               |
| `CANCELLED`             | `CANCELLED`                     | 无 (终态)                                          | -                   |

核心变化：**DRAFT→PENDING→APPROVED 之间的 PENDING→APPROVED 需要 finance_manager 角色**，这是第二个 HITL 点。

---

## 七、Checkpointer 设计

使用 LangGraph 内置的 `PostgresSaver`：

```python
from langgraph.checkpoint.postgres import PostgresSaver

checkpointer = PostgresSaver.from_conn_string(
    "postgresql://user:pass@localhost:5432/langgraph_checkpoints"
)
# 自动建表 (checkpoints, checkpoint_blobs, writes, checkpoint_mappings)
await checkpointer.setup()

# Graph 编译时传入
# TODO: Sprint 2 — 切换为 interrupt_before=["hitl_gate"]
graph = StateGraph(AgentState).compile(
    checkpointer=checkpointer,
)
```

PostgreSQL 存储的 State 快照包含：

- `thread_id`, `checkpoint_id`, `parent_checkpoint_id` — 版本链
- `state` — 完整 `AgentState` (JSON 序列化)
- `metadata` — 包含 `session_id`, `source` (chainlit/console), `created_at`

**跨会话恢复**：用户关闭会话后，第二天重新打开 Chainlit，通过 `thread_id` 和 `checkpoint_id` 恢复被挂起的 Thread。

---

## 八、System Prompt 模板

```
你是一个 ERP 智能采购助理。你的职责是帮助用户完成企业采购流程。

## 可用工具
{列出所有 MCP 工具及其用途}

## 工作规范
1. 每次调用工具前，先思考并说明你的推理链（后续会作为 agent_reasoning 持久化）。
2. 向用户展示供应商选项时，必须同时呈现价格、评分、交期三个维度。
3. 如果试算结果中存在更高阶梯价格，主动提示用户调整数量以节省成本。
4. 收到结构化错误时，优先读取 agent_suggestion 字段，据此给出用户可操作的回复。
5. 不要编造数据。如果工具返回空结果或错误，如实告知用户。
6. 用户输入模糊时，根据当前 State 推断意图。例如：用户说"就按这个来"时，使用当前选中的供应商和商品信息。

## 输出格式
每次回复必须按以下结构组织：
- **结论**：一句话概括当前状态
- **详情**：关键数据（价格、库存、预算等）
- **操作**：用户可执行的下一步动作

## 状态提示
当前进度: {po_status 或 "新会话"}
已有信息: {已确定的 department_id / product_id / supplier_id 等}
```

---

## 九、目录结构建议

```
erp-agent/
├── app/
│   ├── agent/
│   │   ├── graph.py              # StateGraph 定义与编译 (build_graph)
│   │   ├── nodes.py              # 所有节点函数 (含 6 个业务节点)
│   │   ├── state.py              # AgentState TypedDict (21 字段)
│   │   ├── routing.py            # 路由条件函数 (route_after_tools/analysis/user_choice)
│   │   ├── prompts.py            # System Prompt 模板
│   │   └── __init__.py           # 导出 build_graph
│   ├── mcp/
│   │   ├── server.py             # MCP Server 入口 + 所有工具实现
│   │   ├── client.py             # HTTP Client (httpx → mock-erp)
│   │   ├── pruning.py            # 响应裁剪逻辑
│   │   └── interceptor.py        # 越权拦截 + 错误包装
│   ├── chainlit_app.py           # Chainlit 入口 + HITL 审批逻辑
│   ├── dashboard/
│   │   └── ...                   # SQLAdmin 管控台
│   └── core/
│       ├── config.py             # 配置 (DB_URL, etc.)
│       └── langfuse.py           # Langfuse 初始化
├── docs/                         # 文档
├── tests/
│   ├── test_agent/
│   │   ├── test_hitl.py          # HITL 审批测试
│   │   ├── test_scenario_s1.py   # S1 常规采购
│   │   ├── test_scenario_s2.py   # S2 库存不足
│   │   ├── test_scenario_s3.py   # S3 HITL
│   │   ├── test_scenario_s4.py   # S4 阶梯凑单
│   │   ├── test_scenario_s5.py   # S5 综合寻源
│   │   └── test_scenarios.py     # 5 个业务陷阱场景测试
│   ├── test_mcp/
│   │   ├── test_pruning.py       # 裁剪效果测试
│   │   └── test_interceptor.py   # 越权拦截测试
│   └── test_chainlit/
│       └── test_hitl.py          # HITL 审批测试
├── scripts/
│   └── seed.py                   # 测试数据注入
├── pyproject.toml
├── chainlit.md                   # Chainlit 配置
└── docker-compose.yml
```
