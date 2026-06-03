# ERP-Agent 技术架构设计文档 (V1.0)

**文档版本**：V1.0
**对应版本**：PRD V6.0
**核心组件**：LangGraph, MCP Server, FastAPI (Feishu Gateway), PostgreSQL (Checkpointer)

---

## 一、LangGraph 节点图

```mermaid
flowchart TD
    start([用户输入]) --> parse_input[parse_input\n提取意图/部门/商品]
    parse_input --> route_check{route_check\n判断场景}

    route_check -->|需要查品| search_product[search_product\nMCP: GET /products]
    search_product --> check_dept[check_department\nMCP: GET /departments]
    check_dept --> check_bgt[check_budget\nMCP: GET /budgets/id]

    route_check -->|已有商品信息| check_dept

    check_bgt --> budget_check{budget_check\n预算是否充足?}
    budget_check -->|充足| simulate[simulate_purchase\nMCP: POST /pricing/simulate]
    budget_check -->|不足但无需挂起| simulate

    budget_check -->|不足且需挂起| hitl_gate

    simulate --> analyze_sim[analyze_simulate\n分析试算结果\n检查阶梯价/库存/供应商]
    analyze_sim -->|发现阶梯价优化| tier_suggest[tier_suggest\n主动建议凑单]
    analyze_sim -->|库存风险预判| stock_warn[stock_warn\n预判库存, 提前提示]
    analyze_sim -->|正常| present_options[present_options\n展示供应商选项]

    tier_suggest --> present_options
    stock_warn --> present_options

    present_options --> user_choice{user_choice\n用户选择供应商}

    user_choice -->|接受推荐| draft_po[draft_purchase_order\nMCP: POST /po]
    user_choice -->|改选其他| switch_supplier[switch_supplier\n切换供应商]
    user_choice -->|提新条件| simulate

    switch_supplier --> draft_po
    draft_po -->|成功| transit_pending[transit_po_status\nDRAFT→PENDING]

    draft_po -->|BUDGET_INSUFFICIENT| hitl_gate
    draft_po -->|INSUFFICIENT_STOCK| stock_error[stock_error\n库存不足处理]

    subgraph error_recovery [异常自愈]
        stock_error --> show_alternatives[show_alternatives\n展示替代方案]
        show_alternatives --> user_resolve[user_resolve\n用户选择]
        user_resolve -->|减量| simulate
        user_resolve -->|换品| search_product
    end

    subgraph hitl [HITL 审批流]
        hitl_gate[[interrupt_before\n挂起]] --> send_card[发送审批卡片]
        send_card --> wait_approval[...等待用户审批...]
        wait_approval -->|override_token 注入| resume[resume]
        resume --> override_po[override_purchase_order\nMCP: POST /po/override]
        override_po --> transit_pending
    end

    transit_pending --> inform[inform_user\n回复用户结果]
    inform --> end_node([等待下一轮输入])
```

### 节点定义

| 节点名                       | 类型        | 职责                                              | 调用 MCP 工具                 |
| ------------------------- | --------- | ----------------------------------------------- | ------------------------- |
| `parse_input`             | LLM       | 从用户自然语言提取 department, product, quantity, intent | 无                         |
| `search_product`          | Tool      | 按名称搜索商品                                         | `search_product`          |
| `check_department`        | Tool      | 获取部门 ID                                         | `check_department`        |
| `check_budget`            | Tool      | 查询可用预算                                          | `check_budget`            |
| `simulate_purchase`       | Tool      | 执行价格试算                                          | `simulate_purchase`       |
| `analyze_simulate`        | LLM       | 分析试算结果，判断阶梯价、库存、供应商                             | 无                         |
| `tier_suggest`            | LLM       | 生成凑单建议文本                                        | 无                         |
| `present_options`         | LLM       | 格式化展示供应商选项                                      | 无                         |
| `draft_purchase_order`    | Tool      | 创建采购草稿单                                         | `draft_purchase_order`    |
| `transit_pending`         | Tool      | 状态流转 DRAFT→PENDING                              | `transit_po_status`       |
| `override_purchase_order` | Tool      | 特批建单                                            | `override_purchase_order` |
| `stock_error`             | LLM       | 解析库存不足错误，生成替代方案                                 | 无                         |
| `hitl_gate`               | Interrupt | 挂起点，等待 override_token                           | 无                         |
| `inform_user`             | LLM       | 生成最终回复                                          | 无                         |

### 路由条件

```
路由:
  parse_input → search_product:    用户输入含商品名称, 但 state 中无 product_id
  parse_input → check_department:  有商品信息, 但 state 中无 department_id
  check_budget → hitl_gate:        预算不足 且 用户同意申请特批
  analyze_simulate → tier_suggest: 存在更高阶梯且节省金额 > 阈值
  draft_po → hitl_gate:            BUDGET_INSUFFICIENT 异常
  draft_po → stock_error:          INSUFFICIENT_STOCK 异常
  user_choice → switch_supplier:   用户选择的 supplier 与推荐不同
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
    session_id: str                           # 飞书群/用户会话 ID
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

    # --- 错误自愈 ---
    error_context: dict | None                # 捕获的结构化错误
    recovery_attempted: bool                  # 是否已尝试过自动恢复
    recovery_path: str | None                 # 恢复路径: reduce_qty / change_product / override
```

---

## 三、MCP Server 结构

### 3.1 架构

```
┌─────────────────────────────────────────────┐
│              LangGraph Agent                 │
│  (通过 MCP Client 调用工具)                    │
└─────────────────┬───────────────────────────┘
                  │ MCP 协议 (JSON-RPC)
┌─────────────────▼───────────────────────────┐
│              MCP Server                      │
│  ┌─────────────────────────────────────┐     │
│  │  Tool Handlers                      │     │
│  │  - 参数校验                         │     │
│  │  - 响应 Pruning (摘要化/裁剪)         │     │
│  │  - 越权拦截 (operator_role 硬编码)    │     │
│  │  - agent_reasoning 强制校验          │     │
│  └─────────────────────────────────────┘     │
│  ┌─────────────────────────────────────┐     │
│  │  Error Interceptor                  │     │
│  │  - 捕获 mock-erp 结构化错误          │     │
│  │  - 提取 agent_suggestion            │     │
│  │  - 统一包装为 Agent 友好格式         │     │
│  └─────────────────────────────────────┘     │
└─────────────────┬───────────────────────────┘
                  │ HTTP
┌─────────────────▼───────────────────────────┐
│         Mock-ERP (FastAPI + SQLite)           │
│  /api/v1/products, /pricing/simulate, /po... │
└─────────────────────────────────────────────┘
```

### 3.2 Pruning 实现策略

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

## 四、Dev Mode 身份劫持序列图

```mermaid
sequenceDiagram
    participant User as 物理测试账号 (YR)
    participant GW as 飞书网关 (FastAPI)
    participant Agent as LangGraph Agent
    participant MCP as MCP Server
    participant ERP as Mock-ERP

    Note over User,ERP: DEV_MODE=true

    User->>GW: 发送消息 "买 5 台显示器"
    GW->>GW: 输入伪装: open_id → 逻辑身份 "采购员 Alice"
    GW->>Agent: thread_id=xxx, user_role="purchaser"
    Agent->>MCP: search_product / simulate...
    MCP->>ERP: API 调用
    ERP-->>MCP: 响应
    MCP-->>Agent: 裁剪后响应
    Agent->>GW: 需向 "财务主管 Bob" 发送审批卡片
    GW->>GW: 路由重定向: Bob → 物理测试账号
    GW->>GW: 注入标识 "[测试模式: 您正以 Bob 身份查看]"
    GW->>User: 发送审批卡片 (含伪装标识)

    User->>GW: 点击 "批准"
    GW->>GW: 反向伪装: 操作者身份替换为 Bob
    GW->>Agent: resume(thread_id, operator_role="finance_manager", override_token=xxx)
    Agent->>MCP: transit_po_status(operator_role="finance_manager")
    MCP-->>ERP: operator_role="finance_manager"
    ERP-->>MCP: 状态变更成功
    MCP-->>Agent: 成功
    Agent-->>GW: 结果
    GW-->>User: 回复 "审批通过"
```

### Dev Mode 核心逻辑 (Middleware)

```python
from fastapi import Request
import os

DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"
PHYSICAL_USER_ID = "ou_xxxx"  # 物理测试账号 open_id

# 逻辑角色 → 物理映射 (仅 DEV_MODE 启用时反转)
ROLE_MAP = {
    "purchaser": PHYSICAL_USER_ID,   # 采购员 Alice → 物理用户
    "finance_manager": PHYSICAL_USER_ID,  # 财务主管 Bob → 物理用户
}

async def dev_mode_middleware(request: Request, call_next):
    if not DEV_MODE:
        return await call_next(request)

    # 1. 输入伪装: 将物理 open_id 替换为逻辑身份
    body = await request.json()
    if body.get("open_id") == PHYSICAL_USER_ID:
        body["open_id"] = "ou_purchaser_alice"  # 逻辑身份
        body["user_role"] = "purchaser"
        request._body = body

    response = await call_next(request)

    # 2. 路由重定向: 拦截审批卡片目标地址
    if response.status_code == 200 and "send_card" in str(response.body):
        target = response.body.get("target_open_id", "")
        if target in ROLE_MAP:
            response.body["target_open_id"] = PHYSICAL_USER_ID
            response.body["test_mode_badge"] = f"[测试模式: 您正以 {target} 身份查看]"

    # 3. 回调反向伪装: 审批操作者身份替换
    if request.url.path == "/feishu/callback" and body.get("open_id") == PHYSICAL_USER_ID:
        callback_role = body.get("callback_role", "finance_manager")
        request.state.operator_role = callback_role
        request.state.open_id = f"ou_{callback_role}"

    return response
```

---

## 五、Langfuse 埋点方案

### 5.1 Trace 结构

每次 Agent 执行作为一个 Trace，内部节点作为 Spans：

```
Trace: session_id (飞书会话) / thread_id (LangGraph 线程)
├── Span: parse_input           → LLM 调用 (提取意图)
├── Span: search_product        → MCP tool call (含裁剪前后 Token 对比)
├── Span: check_budget          → MCP tool call
├── Span: simulate_purchase     → MCP tool call (重点观测)
│   ├── Span: HTTP request      → mock-erp API
│   └── Span: pruning           → 响应裁剪 (记录原始大小 vs 裁剪后大小)
├── Span: analyze_simulate      → LLM 调用 (分析结果)
├── Span: draft_purchase_order  → MCP tool call
│   ├── Span: HTTP request
│   └── Span: error_intercept   → 如果捕获到异常
├── Span: inform_user           → LLM 调用 (生成回复)
└── Span: total                 → 汇总
```

### 5.2 关键观测指标

```python
# 在每个 MCP tool call 处埋点
from langfuse.decorators import observe

@observe(name="mcp_call", capture_input=True, capture_output=True)
async def call_mcp_tool(tool_name: str, args: dict) -> dict:
    raw_response = await http_client.post(f"{ERP_BASE}/api/v1/{endpoint}", json=args)
    raw_tokens = estimate_tokens(raw_response)

    pruned = prune_response(tool_name, raw_response)
    pruned_tokens = estimate_tokens(pruned)

    # Langfuse 自定义指标
    observation = langfuse.observation(
        name=f"pruning_{tool_name}",
        metadata={
            "raw_tokens": raw_tokens,
            "pruned_tokens": pruned_tokens,
            "compression_ratio": f"{(1 - pruned_tokens/raw_tokens) * 100:.1f}%",
        }
    )
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
graph = StateGraph(AgentState).compile(
    checkpointer=checkpointer,
    interrupt_before=["hitl_gate"],
)
```

PostgreSQL 存储的 State 快照包含：

- `thread_id`, `checkpoint_id`, `parent_checkpoint_id` — 版本链
- `state` — 完整 `AgentState` (JSON 序列化)
- `metadata` — 包含 `session_id`, `source` (feishu/console), `created_at`

**跨天恢复**：用户在飞书上发出采购请求后关闭会话，第二天打开飞书收到审批卡片，点击后通过 `thread_id` 和 `checkpoint_id` 恢复被挂起的 Thread。

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
保持简洁。每个回复包含：
- 结论（一句话）
- 详情（表格/列表）
- 操作（让用户选择的选项）

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
│   │   ├── graph.py              # StateGraph 定义与编译
│   │   ├── nodes.py              # 所有节点函数
│   │   ├── state.py              # AgentState TypedDict
│   │   ├── routing.py            # 路由条件函数
│   │   └── prompts.py            # System Prompt 模板
│   ├── mcp/
│   │   ├── server.py             # MCP Server 入口 + 所有工具实现
│   │   ├── client.py             # HTTP Client (httpx → mock-erp)
│   │   ├── pruning.py            # 响应裁剪逻辑
│   │   └── interceptor.py        # 越权拦截 + 错误包装
│   ├── gateway/
│   │   ├── server.py             # FastAPI 飞书网关
│   │   ├── auth.py               # Dev Mode 中间件
│   │   ├── card_builder.py       # 飞书卡片构造
│   │   └── callback.py           # 审批回调处理
│   ├── dashboard/
│   │   └── ...                   # SQLAdmin 管控台
│   └── core/
│       ├── config.py             # 配置 (DEV_MODE, DB_URL, etc.)
│       └── langfuse.py           # Langfuse 初始化
├── docs/                         # 文档
├── tests/
│   ├── test_agent/
│   │   ├── test_scenario_s1.py   # S1 常规采购
│   │   ├── test_scenario_s2.py   # S2 库存不足
│   │   ├── test_scenario_s3.py   # S3 HITL
│   │   ├── test_scenario_s4.py   # S4 阶梯凑单
│   │   └── test_scenario_s5.py   # S5 综合寻源
│   ├── test_mcp/
│   │   ├── test_pruning.py       # 裁剪效果测试
│   │   └── test_interceptor.py   # 越权拦截测试
│   └── test_gateway/
│       └── test_dev_mode.py      # Dev Mode 测试
├── scripts/
│   └── seed.py                   # 测试数据注入
├── pyproject.toml
└── docker-compose.yml
```
