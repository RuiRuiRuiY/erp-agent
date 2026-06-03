# ERP-Agent 业务行为规范文档 (V1.0)

**文档版本**：V1.0
**对应版本**：PRD V6.0
**前置依赖**：Mock-ERP API (详见 mock-erp/docs/Business_And_API.md)
**核心原则**：Agent 是"有工具的采购助理"，不是"替用户做决定的机器人"。

---

## 一、概览: 5 场景 + 1 异常处理矩阵

| # | 场景 | 触发条件 | 核心 API 调用序列 | Business Trap |
|---|---|---|---|---|
| S1 | 常规采购 | 用户指定商品+数量+部门 | `search_product` → `check_department` → `check_budget` → `simulate_purchase` → 用户确认 → `draft_purchase_order` → `transit_po_status` (DRAFT→PENDING) | 价格 vs 交期权衡 |
| S2 | 库存不足协商 | 建单时服务端抛 `INSUFFICIENT_STOCK` (409) | 解析 `error_context.agent_suggestion` → 向用户展示替代方案 | 库存不足陷阱 |
| S3 | HITL 审批流 | 试算/建单时预算超限 → `interrupt` | 挂起 → 发送审批卡片 → 接收 `override_token` → `resume` → `override_purchase_order` → `transit_po_status` | 预算红线陷阱 |
| S4 | 阶梯定价凑单 | `simulate_purchase` 结果中存在未命中的更高阶梯 | 解析阶梯价差 → 主动建议用户调整数量 → 用户确认后重试 | 阶梯价陷阱 |
| S5 | 供应商综合寻源 | 用户未指定供应商或明确要求对比 | `list_suppliers` → `get_supplier_pricelist`(多供应商) → 综合推荐 | 竞争报价陷阱 |
| EX | 通用异常处理 | 任意步骤服务端抛结构化错误 | 读 `error_code` → 读 `agent_suggestion` → 转译为用户友好的回复 | 全部 |

---

## 二、场景详细行为规范

### S1: 常规采购

**触发条件**：用户明确指定商品名称/型号、数量、部门。可省略供应商（由 Agent 推荐）。

**标准行为流**：

```
用户输入: "给我买 5 台 Dell 显示器给 IT 部"
         ↓
Step 1: search_product("Dell 显示器")
        → 返回 [{id: "p001", sku: "DELL-U2724D", name: "Dell 27'' 显示器", price: 1000}]
        → [异常: 无结果] → 回复"未找到该商品，请确认商品名称"
         ↓
Step 2: check_department("IT部")
        → 返回 {id: "dept_it", name: "IT部"}
        → [异常: 无结果] → 回复"未找到该部门，请确认部门名称"
         ↓
Step 3: check_budget("dept_it")
        → 返回 {department_id: "dept_it", available: 200000}
        → [预算充足] → 继续
        → [预算不足] → 转入 S3 HITL 审批流
         ↓
Step 4: simulate_purchase(department_id="dept_it", items=[{product_id: "p001", qty: 5}])
        → 返回:
          - recommended_supplier: {id: "sup_a", name: "深圳宏达电子", amount: 5000, lead_time: 15}
          - all_quotes: [
              {supplier: "深圳宏达电子", amount: 5000, lead_time: 15, rating: 4.5},
              {supplier: "上海极速科技", amount: 6000, lead_time: 2, rating: 4.0}
            ]
          - skipped_suppliers: [...]
          - department_remaining_budget: 195000
         ↓
Step 5: 向用户展示供应商选项 (必须同时呈现价格、交期、评分)

        "Dell 27'' 显示器 5 台, 共 5000 元。
        供应商选项:
        A. 深圳宏达电子 → 5000 元, 15 天交期, 评分 4.5 (推荐)
        B. 上海极速科技 → 6000 元, 2 天交期, 评分 4.0
        请选择:"

         ↓
        [用户选择 A] → 继续使用推荐供应商
        [用户选择 B] → 切换到上海极速科技
        [用户回复其他] → 如指定价格上限/交期要求, 调整筛选条件后重跑 Step 4

Step 6: draft_purchase_order(department_id="dept_it", supplier_id="sup_a",
                             items=[{product_id: "p001", qty: 5}],
                             agent_reasoning="用户指定 IT 部采购 5 台 Dell 显示器...
                                            推荐深圳宏达电子总价最低(5000 元/15 天交期)")
        → 返回 {id: "po_xxx", status: "DRAFT", total_amount: 5000.0}
        → [异常: BUDGET_INSUFFICIENT] → 转入 S3
        → [异常: INSUFFICIENT_STOCK] → 转入 S2
        → [异常: PRICING_TIER_NOT_FOUND] → 回复"该供应商对此商品暂无报价"
         ↓
Step 7: transit_po_status("po_xxx", target_status="PENDING", operator_role="agent")
        → 返回 {new_status: "PENDING"}
        → [异常: 409] → 解析错误并回复用户
         ↓
Step 8: 回复用户: "采购单已创建并提交审批，单号: PO-xxx-xxx。
        当前状态: 待审批。财务主管审批通过后即可下单。"
```

**决策树**:

```
用户输入
  ├─ 商品不存在 → 提示用户
  ├─ 部门不存在 → 提示用户
  ├─ 预算不足 → 转入 S3
  ├─ 库存不足 → 转入 S2
  └─ 一切正常
      ├─ 用户接受推荐 → 建单
      ├─ 用户选其他供应商 → 建单(指定供应商)
      └─ 用户提新条件 → 调整后重新试算
```

---

### S2: 库存不足协商

**触发条件**：`draft_purchase_order` 返回 `INSUFFICIENT_STOCK` 错误。

**mock-erp 错误示例**：

```json
{
  "error_code": "INSUFFICIENT_STOCK",
  "message": "商品 人体工学椅 库存不足",
  "context": { "product_id": "p003", "requested": 10, "available": 5 },
  "agent_suggestion": "建议减少购买数量至 5 件，或联系供应商确认补货时间"
}
```

**行为流**：

```
Step 1: 捕获 InsufficientStockError
Step 2: 解析 error_context:
          - requested: 10 (用户要的数量)
          - available: 5 (实际可用)
          - agent_suggestion: "建议减少购买数量至 5 件..."
Step 3: 向用户回复 (Agent 自身逻辑, 非简单透传):

        "人体工学椅库存不足。
        您要 10 把，目前仅剩 5 把。
        建议方案:
        A. 先购买 5 把（剩余库存）
        B. 更换其他商品
        请选择:"

Step 4:
  [用户选 A] → 修改 cart_items 数量为 5 → 重新 check_budget → 重新建单
  [用户选 B] → 询问用户想买什么替代品
  [用户坚持 10 把] → 回复"目前库存无法满足，建议分批或选择替代品"
```

**约束**：
- `INSUFFICIENT_STOCK` 不能被 `override_token` 绕过 (mock-erp 强制校验)。
- Agent 不可编造补货时间，应如实告知用户"库存信息以系统为准"。
- 修改数量后需重新执行 `simulate_purchase`（阶梯价可能变化）→ `check_budget`。

---

### S3: HITL 审批流 (预算超标)

**触发条件**：`simulate_purchase` 或 `draft_purchase_order` 返回预算不足，或 `check_budget` 发现可用余额不足。

**mock-erp 错误示例**：

```json
{
  "error_code": "BUDGET_INSUFFICIENT",
  "message": "IT 部预算不足",
  "context": { "required": 500000, "remaining": 120000, "deficit": 380000 },
  "agent_suggestion": "建议申请预算特批或联系财务部门调整预算"
}
```

**行为流**：

```
用户: "采购 5 台 MacBook Pro (5×30000=150000) 给设计部"
         ↓
Step 1-4: 同 S1, check_budget 发现设计部可用预算仅 50000, 不足 150000
         ↓
Step 5: Agent 进入 hitl_override_gate 节点

        [Agent 回复用户]:
        "设计部当前可用预算 50000 元，本次采购需 150000 元，超出 100000 元。
        请确认是否申请特批？(需财务主管审批)"

         ↓
        [用户确认] → Agent 调用 interrupt_before 挂起
        [用户放弃] → 流程终止, 回复"已取消采购"

Step 6 (挂起态): 系统向用户发送飞书审批卡片 (或管控台显示挂起记录):

        "📋 采购特批申请
         申请人: 采购员 Alice
         部门: 设计部
         商品: MacBook Pro × 5
         金额: ¥150,000 (预算仅 ¥50,000)
         请 [批准] / [拒绝]"

         ↓
        [用户点击批准] → 飞书网关接收回调, 注入 override_token → resume Thread
        [用户点击拒绝] → 回复用户"审批已拒绝"

Step 7 (resume 后): Agent 调用:

        override_purchase_order(department_id="dept_design",
                                supplier_id=recommended_supplier,
                                items=[...],
                                agent_reasoning="...",
                                override_token="xxx")
        → 返回 PO (status: DRAFT, is_override=True)

Step 8: transit_po_status(po_id, target_status="PENDING", operator_role="agent")
        → DRAFT → PENDING (override 跳过预算检查, 但仍查库存)

Step 9: 通知用户: "特批已通过, 采购单已提交, 等待财务主管最终审批。"

        [注: 此时还需要一次 human-in-the-loop, 由 finance_manager 将 PENDING→APPROVED]
        → 飞书卡片通知财务主管 Bob → Bob 审批 → 回调触发
          transit_po_status(po_id, target_status="APPROVED", operator_role="finance_manager")
```

**关键设计点**：

1. **两次 HITL**：第一次是"用户确认申请特批"（`interrupt`/`override_token`），第二次是"财务主管审批 PENDING→APPROVED"（`operator_role="finance_manager"`）。这是 mock-erp 状态机的要求。
2. **operator_role 切换**：`transit_po_status` 的 `operator_role` 参数必须由 MCP 层根据调用来源硬编码，LLM 不可操控。
3. **override 边界**：mock-erp 的 override 仅跳过预算检查，不跳过库存和定价检查。Agent 需向用户说明"特批通过，但仍需满足库存条件"。

---

### S4: 阶梯定价凑单建议

**触发条件**：`simulate_purchase` 返回的 `all_quotes` 中存在未命中的更高阶梯，且价差显著（节省金额 > 商品单价 × 20% 或用户明确关注成本）。

**行为逻辑**：

```
用户: "买 90 个罗技鼠标给 IT 部"
         ↓
simulate_purchase → 返回:
  - 推荐供应商: SUP_C, 90个 × 100元 = 9000元
  - Agent 分析阶梯数据:
      * 当前阶梯: 1-99个 → 100元/个
      * 下一个阶梯: 100+个 → 80元/个
      * 多买 10 个(100个×80元=8000元) vs 90个×100元=9000元
      * 多花 10×80=800 元, 但节省 9000-8000=1000 元
      * 净节省: 1000 元!
         ↓
Agent 回复:

"罗技鼠标报价: 90 个 × 100 元 = 9000 元。
💡 建议: 加购 10 个至 100 个，可享受阶梯价 80 元/个，
  总价仅 8000 元，反而节省 1000 元。
请问是否需要调整数量？"
         ↓
[用户同意] → 修改 cart_items 中鼠标数量为 100 → 重新 simulate_purchase
              → 确认后进入建单流程
[用户拒绝] → 按原数量建单
```

**约束**：
- Agent 必须给出具体数字对比（当前总价 vs 建议后总价 + 节省金额）。
- Agent 不可主动替用户改数量，必须等用户确认。
- 若用户原数量已是最优阶梯，不提凑单建议。

**阶梯价计算规则**（Agent 内部逻辑，非调用额外 API）：

```
for each supplier_quote in simulate_result.all_quotes:
    for each line_detail in supplier_quote.line_details:
        # 检查同一供应商同一商品的更高阶梯
        higher_tier = find_next_tier(supplier_id, product_id, current_qty)
        if higher_tier:
            savings = calculate_savings(current_qty, current_price,
                                        higher_tier.min_qty, higher_tier.unit_price)
            if savings > 0:
                → 生成凑单建议
```

---

### S5: 供应商综合寻源

**触发条件**：
- 用户未指定供应商，且 `simulate_purchase` 返回多个可fulfill供应商。
- 用户明确要求"帮我比价"、"找最好的供应商"、"综合评分"等。

**行为流**：

```
用户: "对比一下所有供应商对机械键盘的报价"
         ↓
Step 1: list_suppliers → 返回所有供应商信息 (id, name, rating, lead_time)
         ↓
Step 2: simulate_purchase(department_id, items=[{product_id: "p006", qty: 10}])
        → 返回 all_quotes:
          - SUP_C 广州万通: 500元/个 × 10 = 5000 元, 评分 4.8, 7 天
          - SUP_A 深圳宏达: 450元/个 × 10 = 4500 元, 评分 4.5, 15 天
         ↓
Step 3: 综合对比并推荐

        "机械键盘 10 把的报价对比:
        A. 深圳宏达 → 4500 元 (评分 4.5, 15 天) — 价格最低
        B. 广州万通 → 5000 元 (评分 4.8, 7 天) — 评分最高, 交期最快

        推荐: 若预算优先选 A(省 500), 若质量和速度优先选 B。
        请选择:"
```

**评分权重参考**（Agent 推荐依据）：

| 维度 | 权重 | 说明 |
|---|---|---|
| 总价 | 50% | 核心维度 |
| 交期 | 30% | 响应速度影响业务 |
| 供应商评分 | 20% | 长期合作质量参考 |

这个权重仅用于 Agent 生成 `recommendation_reason`，不做硬性排序规则。

---

## 三、通用异常处理

### 3.1 结构化错误映射表

| error_code | HTTP | Agent 行为 | 是否可自愈 |
|---|---|---|---|
| `RESOURCE_NOT_FOUND` | 404 | 告知用户资源不存在，请检查名称 | ❌ 需用户输入 |
| `BUDGET_INSUFFICIENT` | 409 | 转入 S3 HITL 审批流 | ✅ 通过 override |
| `INSUFFICIENT_STOCK` | 409 | 转入 S2 协商流程 | ✅ 通过减量/换品 |
| `INVALID_STATE_TRANSITION` | 409 | 告知用户当前状态不允许该操作，建议联系管理员 | ❌ 需人工 |
| `PERMISSION_DENIED` | 403 | 告知用户无权限，建议联系管理员 | ❌ 需人工 |
| `PRICING_TIER_NOT_FOUND` | 409 | 告知用户该供应商无匹配报价，建议换供应商 | ❌ 需用户选择 |
| `IntegrityError` | 500 | 系统内部错误，告知用户稍后重试 | ❌ 需管理员 |

### 3.2 多轮对话中的上下文保持

- Agent 需在每次回复中携带当前流程进度摘要，帮助用户理解当前状态。
- 当用户输入模糊时（如"就按这个来"），Agent 应根据 `AgentState` 推断用户意图，而不是重新开始。

**上下文保持示例**：

```
用户: "那就按推荐的来吧"
Agent 推理: State 中 simulate_result 存在, selected_supplier_id 为空
           → 用户接受推荐供应商 → 进入建单流程

用户: "换个供应商"
Agent 推理: State 中有 simulate_result.all_quotes
           → 展示其他供应商选项让用户选

用户: "刚才那个流程到哪了"
Agent 推理: State 中有 po_draft_id 但 po_status="PENDING"
           → "采购单 PO-xxx 已提交，正在等待财务审批"
```

---

## 四、回复格式规范

### 4.1 Agent 回复模板

- 第一行：简洁结论（一句话概括做了什么/出现了什么情况）
- 中间：结构化信息（表格/列表）
- 最后：行动选项（让用户选择下一步）

```
[结论] 已为您查询到 Dell 显示器信息。
[详情]
  商品: Dell 27'' 显示器 | 单价: ¥1,000 | 库存: 充足
  供应商选项:
  | 选项 | 供应商 | 总价 | 交期 | 评分 |
  |---|---|---|---|---|
  | A | 深圳宏达 | ¥5,000 | 15天 | 4.5 |
  | B | 上海极速 | ¥6,000 | 2天  | 4.0 |
[操作] 请选择供应商 A 或 B，或提出其他要求。
```

### 4.2 错误回复模板

```
[问题] 商品"XX"库存不足。
[详情] 您需要 10 件，当前可用仅 5 件。
[建议] 您可以选择:
  A. 先购买 5 件
  B. 更换其他商品
  C. 其他需求请告诉我
```

---

## 五、与 mock-erp 的集成点

| Agent 行为 | 依赖 mock-erp 能力 | mock-erp 实现状态 |
|---|---|---|
| 错误自愈 | 结构化错误 + `agent_suggestion` | ✅ 已实现 |
| 预算校验 | `GET /budgets/{dept_id}` (含 available 计算字段) | ✅ 已实现 |
| 阶梯价发现 | `POST /pricing/simulate` (含阶梯命中) | ✅ 已实现 |
| override 建单 | `POST /po/override` (含 override_token 校验) | ✅ 已实现 |
| 状态机流转 | `POST /po/{id}/transit` (guard/action 模式) | ✅ 已实现 |
| 综合比价 | Multiple suppliers pricing data | ✅ 种子数据已含 |
