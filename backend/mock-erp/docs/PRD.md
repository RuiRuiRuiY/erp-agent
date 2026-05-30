------

# 📄 B2B 硬件采购与库存履约 Mock ERP 需求文档 (Agent 交互版)

## 1. 项目概述

本项目是一个专为验证大语言模型 Agent 工具调用（Function Calling）、复杂工作流编排（LangGraph）以及异常处理能力而设计的“模拟企业资源计划（ERP）系统”。
系统对外提供 RESTful API，**不包含任何前端 UI**。系统的核心用户是“AI 采购助理 Agent”，系统需通过严格的业务规则、状态机校验和特定的错误码，来测试 Agent 在复杂、受限企业环境下的决策与执行能力。

## 2. 核心实体定义 (Data Dictionary)

系统包含四个核心数据实体，它们之间存在严格的关联约束：

| 实体名称                   | 核心字段 (简略)                                              | 业务含义与约束                                               |
| -------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| **Product (商品)**         | `id` (UUID), `name`, `category`, `unit_price`                | 硬件商品基础信息。不可被 Agent 修改或创建。                  |
| **Inventory (库存)**       | `product_id` (FK), `total_qty`, `available_qty`, `locked_qty` | `available_qty` = `total_qty` - `locked_qty`。Agent 采购时只能使用 `available_qty`。 |
| **Budget (预算)**          | `department_id` (主键), `total_limit`, `used_amount`         | 部门的财务预算。`remaining` = `total_limit` - `used_amount`。 |
| **PurchaseOrder (采购单)** | `id` (UUID), `product_id`, `dept_id`, `qty`, `total_cost`, `status` | 核心业务单据。记录采购行为及当前流转状态。                   |

| 实体名称          | 核心字段 (简略)                                             | 业务含义与约束                           |
| ----------------- | ----------------------------------------------------------- | ---------------------------------------- |
| Supplier (供应商) | `id` (UUID), `name`, `rating` (1-5), `lead_time_days` (int) | 供应商资质信息。Agent 可查询，不可修改。 |
| Product (商品)    | *(新增)* `supplier_id` (FK)                                 | 一个商品由一个特定供应商提供。           |

**新增 `SupplierPricelist` (供应商报价矩阵) 表：**

- `id` (UUID)
- `supplier_id` (FK -> Supplier)
- `product_id` (FK -> Product)
- `min_qty` (int) - *触发该价格的最小数量*
- `unit_price` (float) - *阶梯单价*
- *联合唯一约束 (Unique Constraint)*：`supplier_id`, `product_id`, `min_qty` 必须唯一。

## 3. Agent 角色设定与权限边界 (Role & Permissions)

这是设计 **Human-in-the-loop（人机协同）** 的关键依据。

- **Agent 角色**：IT 部门的“AI 采购助理”。

- 拥有的权限 (Read & Draft)

  ：

  - 查询所有商品目录及当前可用库存。
  - 查询指定部门的当前剩余预算。
  - 创建**草稿状态 (DRAFT)** 的采购单（此时系统会预扣库存，但不扣减实际预算）。
  - 将草稿订单**提交审批 (Submit for Approval)**，状态变更为 `PENDING_APPROVAL`。

- 没有的权限 (Write & Approve - 需人工介入)

  ：

  - **无权**直接批准订单（将状态改为 `APPROVED`）。
  - **无权**直接修改部门的总预算。
  - **无权**强制解除被锁定的库存。

## 4. 核心交互场景 (Agent Workflows & Edge Cases)

我们需要设计几个典型的场景，包含“顺利路径（Happy Path）”和“异常路径（Edge Cases）”，以此来“刁难”和测试 Agent。

### 场景 A：常规查询与简单采购 (Happy Path)

- **用户指令**：“帮我查一下现在有没有罗技鼠标，有的话给 IT 部门买 10 个。”

- Agent 预期行为

  ：

  1. 调用 `search_products` 找到罗技鼠标的 `product_id`。
  2. 调用 `check_inventory` 确认 `available_qty >= 10`。
  3. 调用 `check_budget` 确认 IT 部门预算充足。
  4. 调用 `create_order` 创建草稿订单。
  5. 调用 `submit_order` 提交审批。
  6. 回复用户：“已为您创建采购单并提交审批，单号为 XXX。”

### 场景 B：库存不足时的智能协商 (Error Handling & Reflection)

- **用户指令**：“买 50 台戴尔显示器。”

- **系统埋坑**：戴尔显示器当前 `available_qty` 只有 20 台。

- **API 预期返回**：`create_order` 接口返回 `400 Bad Request`，错误码 `ERR_INSUFFICIENT_STOCK`，并附带提示信息：“库存不足。当前可用: 20。建议方案: 1. 减少数量; 2. 等待补货; 3. 寻找替代品。”

- Agent 预期行为 (考察 Reflection 能力)

  ：

  - *低级 Agent*：直接报错给用户“库存不足”。
  - *高级 Agent*：捕获错误码，**自主决定**调用 `search_products` 寻找同价位的其他品牌显示器作为替代方案，或者向用户提问：“戴尔显示器只有 20 台了，我是先买 20 台，还是帮您看看其他品牌？”

### 场景 C：预算超标触发审批流 (Human-in-the-loop)

- **用户指令**：“给设计部买 5 台高配 MacBook Pro。”

- **系统埋坑**：总价超出了设计部的 `remaining` 预算。

- **API 预期返回**：`create_order` 接口返回 `400 Bad Request`，错误码 `ERR_BUDGET_EXCEEDED`。

- Agent 预期行为 (考察工作流中断与恢复)

  ：

  1. 识别到预算超标。
  2. **触发 Interrupt（中断）**：Agent 暂停当前工作流，向用户（或管理员）发送通知：“设计部预算超标 3000 元，是否允许透支并强制创建特批订单？”
  3. **等待 Human Input**：用户回复“同意”。
  4. Agent 调用特殊接口 `create_order_with_override`（需携带特殊 token 或参数）完成创建。

###  场景 D：基于阶梯定价的智能凑单建议 (Proactive Planning)

- **系统埋坑**：某型号服务器单价 10000 元。折扣规则：>=10台，95折；>=50台，9折。当前用户要求买 48 台。

- Agent 预期行为

  ：

  1. 查询商品单价和折扣规则。
  2. 进行内部计算（或调用 ERP 提供的 `estimate_price` 试算 API）。
  3. 发现 48台 * 10000 = 480,000 元；而 50台 * 10000 * 0.9 = 450,000 元。
  4. **中断并询问用户**：“我发现购买 50 台可以享受 9 折优惠，总价 45 万，比您要求的 48 台（48万）还要便宜 3 万。是否需要将采购数量修改为 50 台？”
  5. 用户同意后，再以 50 台的数量调用 `create_order`。

### 场景 E：基于供应商属性的综合寻源 (Multi-hop Reasoning)

- **用户指令**：“研发部需要买 20 把人体工学椅，预算 3 万。另外，下周一就要用，帮我筛选一下。”
- Agent 预期行为：
  1. 搜索“人体工学椅”，可能得到多个不同供应商的商品。
  2. 过滤掉单价 * 20 > 30000 的商品（预算约束）。
  3. 查询剩余商品的供应商 `lead_time_days`。
  4. 假设今天是周四，下周一是 4 天后。过滤掉 `lead_time_days > 4` 的供应商。
  5. 向用户推荐最终符合条件的商品并请求确认。

## 5. 核心业务规则与状态机 (Business Rules & State Machine)

这是后端代码必须严格遵守的铁律，也是 Agent 容易产生幻觉（Hallucination）的地方。

### 5.1 价格试算规则

**新增 API 接口**：`POST /api/v1/pricing/simulate` (价格试算接口)。接收 `product_id` 和 `qty`，后端自动匹配最优供应商和阶梯价，返回详细的比价 JSON，供 Agent 决策使用

### 5.2 采购单状态机 (State Machine)

订单状态只能按照以下有向图流转，API 必须拒绝任何非法的状态跃迁。

```text
[DRAFT] ──(提交审批)──> [PENDING_APPROVAL] ──(人工批准)──> [APPROVED] ──(发货/履约)──> [FULFILLED]
                          │                                    │
                          └──(人工拒绝)──> [REJECTED]          └──(取消)──> [CANCELLED]
```

- **非法操作示例**：Agent 试图调用 `update_order_status` 将 `DRAFT` 直接改为 `APPROVED`。
- **API 预期返回**：`409 Conflict`，错误码 `ERR_INVALID_STATE_TRANSITION`。

### 5.3 事务一致性约束 (Transaction)

- **创建订单时**：必须在同一个数据库事务中完成：① 生成订单记录 -> ② 增加 `locked_qty` -> ③ 减少 `available_qty`。任何一步失败，全部回滚。
- **批准订单时**：必须在同一个事务中完成：① 状态改为 `APPROVED` -> ② 扣减部门 `used_amount` (实际扣钱) -> ③ 减少 `locked_qty` (库存真正出库)。

## 6. 验收标准 (Acceptance Criteria for Agent)

如何评判基于此 ERP 开发的 Agent 是合格的？

1. **零幻觉调用**：Agent 绝不会凭空捏造不存在的 `product_id` 或 `department_id` 发起请求。
2. **优雅的错误恢复**：面对 `ERR_INSUFFICIENT_STOCK` 等业务错误，Agent 能解析错误信息，并自主采取替代策略或向用户澄清，而不是直接抛出代码异常（Traceback）。
3. **状态机敬畏**：Agent 理解订单的生命周期，不会尝试去“黑”进系统直接修改已批准订单的金额。
4. **Token 经济性**：Agent 在查询列表时，懂得使用分页参数，而不是一次性拉取所有数据导致 Context Window 溢出。

------

### 💡 接下来你的行动建议：

1. **Review 这份文档**：看看有没有你觉得不合理或者想增加的业务逻辑（比如增加一个“供应商”实体？或者增加“批量采购打折”的规则？）。**规则越复杂，你的 Agent 施展空间越大。**
2. **确认技术栈**：确保你准备好使用 Python, FastAPI, SQLModel/SQLAlchemy, 以及 SQLite。
3. **准备进入第二步**：当这份 PRD 你觉得 OK 后，我们就进入**第二步：技术架构与数据模型设计 (DB Design)**。我会教你如何把这些文字规则，转化为严谨的 SQLModel 数据表结构和 Pydantic 校验模型。

你觉得这份 PRD 的场景设计符合你的预期吗？有没有哪个场景你想替换或深入的？随时告诉我！
