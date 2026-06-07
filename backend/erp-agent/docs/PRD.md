# ERP-Agent 智能采购中枢 产品需求文档 (PRD V6.0)

**文档版本**：V6.0 (全场景覆盖与行为规范确权版)
**项目阶段**：Week 2 - Week 4 实施期
**核心依赖**：LangGraph, FastMCP + langchain-mcp-adapters, Chainlit, FastAPI, SQLite (WAL), PostgreSQL, SQLAdmin, Langfuse, DeepSeek API

------

## 一、 产品定位与核心愿景

### 1.1 项目背景与破局思路

将 LLM 接入对话式 UI 并驱动底层 ERP 流程，面临上下文管理、多角色测试、人工审批闭环等系统性工程挑战。
本项目摒弃“为了炫技而过度设计”的伪需求（如引入重型 Redis 队列、复杂的卡片原位更新、双轨 A/B 代码开发），**聚焦于 AI Agent 的核心工程化能力**。通过 MCP 协议数据裁剪、LangGraph 状态机挂起、Chainlit HITL 审批弹窗以及低代码管控台，构建一个高可用、可观测、具备人工兜底能力的 Agent 落地标杆，以此作为极具竞争力的技术资产。

### 1.2 核心护城河 (面试核心考点)

1. **LangGraph 状态机与 HITL**：实现长时运行的审批挂起（interrupt）与外部 Token 唤醒（resume），通过 Chainlit 原生弹窗完成人工审批闭环。
2. **MCP 协议与数据裁剪 (Pruning)**：将庞大的 ERP JSON 转化为 LLM 友好的摘要，硬编码拦截越权，防幻觉。
3. **结构化异常自愈**：Agent 捕获 ERP 结构化错误（如 409 库存不足）并自动触发替代方案。
4. **角色切换机制**：通过 Chainlit 命令实现单人测试采购员/财务主管全流程，打通全链路 E2E 测试。
5. **五场景 Agent 行为规范**：基于 mock-erp 的结构化错误与业务陷阱，预定义 Agent 在常规采购、库存不足、预算超标、阶梯凑单、综合寻源 5 个场景的决策逻辑。
6. **LLM 选型与 Prompt 工程**：明确 LLM 模型规格与 System Prompt 设计策略，确保 Agent 行为可预测、可调试。

------

## 二、 系统总体架构设计

本项目采用**轻量级四层解耦与双库物理隔离架构**。业务数据与 Agent 状态数据彻底分离，在保证核心亮点的前提下，最大化开发 ROI。

| 架构层级   | 组件名称          | 技术选型                              | 核心职责与设计考量                                           |
| ---------- | ----------------- | ------------------------------------- | ------------------------------------------------------------ |
| **触达层** | Chainlit Chat UI  | Chainlit                             | 提供开箱即用的对话式 UI；原生支持 HITL 审批弹窗（`AskActionMessage`）；支持角色切换命令实现单人多角色测试。 |
| **大脑层** | LangGraph Agent   | Docker + **PostgreSQL**               | 运行 StateGraph，原生支持 `interrupt` 断点挂起；**PostgreSQL 作为 Checkpointer** 存储 State 快照，支撑跨会话审批流恢复。 |
| **工具层** | MCP Server        | Python + FastMCP                      | 拦截 Mock-ERP 响应，执行 Response Pruning（数据裁剪），硬编码拦截越权操作。 |
| **底座层** | Mock-ERP & 管控台 | FastAPI + **SQLite (WAL)** + SQLAdmin | 提供核心交易 API；**SQLite 开启 WAL 模式保障并发读写**，实现业务库零配置与轻量级；通过 SQLAdmin 构建带视图级 RBAC 的管理后台。 |
| **观测层** | 全链路追踪        | Langfuse                              | Day 0 接入，追踪 LLM 思考、Tool 调用耗时及 Token 消耗，提供单轨开发下的数据对比支撑。 |

------

## 三、 核心模块需求详细说明

### 3.1 Chainlit 对话 UI 与 HITL 审批

- **对话式交互**：用户通过 Chainlit Chat UI 发送自然语言采购指令，Agent 返回结构化回复。
- **HITL 审批弹窗**：当预算超标触发 interrupt 时，Chainlit 原生 `AskActionMessage` 弹出审批确认框，用户点击"批准"或"拒绝"后通过 `Command(resume=True)` 唤醒挂起的 Thread。
- **角色切换命令**：支持 `/role 采购员` / `/role 财务经理` 命令切换当前操作者角色，实现单人测试多角色审批流。无需复杂的身份伪装机制。

### 3.2 Agent 引擎与 MCP 工具层 (LangGraph & MCP)

- 状态定义 (Agent State)

  ：

  ```python
  class AgentState(TypedDict):
      # --- LangGraph 核心 ---
      messages: Annotated[list, add_messages]   # 对话历史
      thread_id: str                            # LangGraph 线程 ID (绑定 Langfuse)
      session_id: str                           # 用户会话 ID

      # --- 业务上下文 ---
      department_id: str                        # 提取出的部门 ID
      cart_items: list[CartItem]                # 用户意图采购的商品清单
      selected_supplier_id: str | None          # 用户选择的供应商 ID
      supplier_choice_prompted: bool            # 是否已向用户展示供应商选项

      # --- 试算与建单 ---
      simulate_result: dict                     # 试算引擎返回的裁剪后数据
      po_draft_id: str | None                   # 创建的草稿单 ID
      po_status: str | None                     # 当前 PO 生命周期状态

      # --- HITL / 审批 ---
      override_token: str | None                # 人类提供的特批 Token
      operator_role: str                        # 当前操作者角色 (purchaser / finance_manager)

      # --- 错误自愈 ---
      error_context: dict | None                # 捕获的结构化错误 (含 error_code, context, agent_suggestion)
      recovery_attempted: bool                  # 是否已尝试过自动恢复
  ```

- MCP 工具映射与 Pruning 策略 (核心技术壁垒)

  ：

  | MCP Tool 名称                | 对应 Mock-ERP API              | MCP Pruning (数据裁剪) 策略                                                              | 预期优化     |
  | ---------------------------- | ------------------------------ | ---------------------------------------------------------------------------------------- | ------------ |
  | `search_product`             | `GET /products`                | 剔除审计字段，仅保留 `id`, `sku`, `name`, `price`。                                       | 📉 Token 40%  |
  | `check_department`           | `GET /departments`             | 仅保留 `id`, `name`。                                                                     | 📉 Token 50%  |
  | `check_budget`               | `GET /budgets/{department_id}` | 保留 `department_id`, `available`(已计算剩余)，剔除 `fiscal_year` 等审计字段。                | 📉 Token 60%  |
  | `check_inventory`            | `GET /inventory/{product_id}`  | 仅保留 `product_id`, `available_qty`(计算字段)。                                          | 📉 Token 70%  |
  | `list_suppliers`             | `GET /suppliers`               | 保留 `id`, `name`, `rating`, `default_lead_time_days`，剔除 `contact` 等无关字段。          | 📉 Token 50%  |
  | `get_supplier_pricelist`     | `GET /suppliers/{id}/pricelists` | 摘要化：仅保留 `product_id`, `min_qty`, `unit_price`，剔除有效期等审计字段。                | 📉 Token 60%  |
  | `simulate_purchase`          | `POST /pricing/simulate`       | **智能摘要化**：保留推荐供应商完整明细；其他供应商仅保留总价、交期和 skipped 原因；保留预算信息。 | 📉 Token 80%  |
  | `draft_purchase_order`       | `POST /po`                     | MCP 层强制校验 `agent_reasoning` 字段是否包含有效推理链，否则拦截重写。                     | 🛡️ 防幻觉     |
  | `override_purchase_order`    | `POST /po/override`            | MCP 层强制注入 `override_token`，LLM 不可操控该参数；校验 token 格式。                      | 🛡️ 防越权     |
  | `transit_po_status`          | `POST /po/{id}/transit`        | MCP 层**硬编码** `operator_role`，根据路由来源自动决定：Agent 自主流转为 `"purchaser"`，HITL 回调审批为 `"finance_manager"`。 | 🛡️ 防越权 |

- 核心节点与路由 (HITL 挂起 & operator_role 切换)

  ：

  - 在 `hitl_override_gate` 节点配置 `interrupt_before`。当预算超标时，Agent 挂起并持久化至 PostgreSQL。
  - 通过 Chainlit `AskActionMessage` 向用户索要 `OVERRIDE_TOKEN`，注入后唤醒 Agent 继续执行。
  - **operator_role 切换机制**：Agent 自主调用 `transit_po_status` 时 `operator_role="purchaser"`（仅限 DRAFT→PENDING 等非审批状态流转）。HITL 回调触发审批时，由 Chainlit 或管控台将 `operator_role` 提升为 `"finance_manager"`（对应 APPROVED/REJECTED 状态变更）。MCP 层据此区分"Agent 自主动作"与"人类审批动作"，防止越权。

### 3.4 Agent 行为规范 (新增 — 详见专项文档)

Agent 的 5 个核心业务场景及对应的行为逻辑，在独立文档中详细定义：

| 场景 | 触发条件 | Agent 行为要点 | 对应 Business Trap |
|---|---|---|---|
| S1 常规采购 | 用户指定商品+数量+部门 | 查品→查预算→试算→展示供应商选项→建单 | 价格 vs 交期权衡 |
| S2 库存不足协商 | 建单时抛 INSUFFICIENT_STOCK | 解析 `agent_suggestion`，推荐替代方案 | 库存不足陷阱 |
| S3 HITL 审批流 | 试算/建单时预算超限 | 挂起→发审批卡片→接收 Token→resume→override | 预算红线陷阱 |
| S4 阶梯定价凑单 | 试算结果存在更优阶梯 | 主动建议用户调整数量，说明节省金额 | 阶梯价陷阱 |
| S5 供应商综合寻源 | 用户未指定供应商或要求对比 | 多维度对比(价格+评分+交期)，给出推荐 | 竞争报价陷阱 |

> **详细行为设计见 [`docs/02-Agent-Business-Behavior.md`](./02-Agent-Business-Behavior.md)**。
> **技术架构设计见 [`docs/03-Agent-Technical-Arch.md`](./03-Agent-Technical-Arch.md)**。
> **实施计划见 [`docs/04-Implementation-Plan.md`](./04-Implementation-Plan.md)**。


### 3.5 LLM 选型与 Prompt 工程策略

- **LLM 选型**：采用 `deepseek-v4-pro` 平衡推理质量与 Token 成本。备选 `deepseek-v4-flash` 以保证 API 兼容性。
- **System Prompt 设计**：
  - 角色定义：ERP 采购助理，仅通过 MCP 工具操作数据，不凭空编造。
  - 工具使用规范：每次调用前展示推理链（`agent_reasoning`），如 `"搜索 Dell 显示器 → 确认商品 ID → 查询 IT 部预算 → 执行试算"`。
  - 错误处理指令：收到结构化错误时优先读取 `agent_suggestion` 字段，据此给出用户可操作的回复。
  - 供应商展示规范：向用户展示供应商选项时，必须同时呈现价格、评分、交期三个维度。
  - 阶梯价提醒规范：试算结果存在更高阶梯时，必须主动提示用户调整数量。
- **Token 预算规划**：System Prompt ≈ 800 Tokens；单轮对话 ≈ 2000 Tokens；MCP 工具响应（裁剪后）≈ 400-800 Tokens。3 轮内完成一次完整采购流程。

> **详细 Prompt 模板见技术架构文档 [`03-Agent-Technical-Arch.md`](./03-Agent-Technical-Arch.md)**。

### 3.6 Mock-ERP 与低代码管控台 (Admin Dashboard)

  ：

  - 摒弃重型权限框架，在 SQLite 中新建极简 `AdminUser` 单表（仅含 `id`, `username`, `hashed_password`, `role` 字段）。
  - 结合 FastAPI 的 `OAuth2PasswordBearer` 与 SQLAdmin 的 `AdminAuth` 基类，实现轻量级登录拦截。

- 视图级权限控制 (View-level RBAC)

  ：

  - 利用 SQLAdmin ModelView 的 `is_accessible` 等属性实现角色隔离。
  - 例如：`role="finance"` 的用户隐藏“强行审批”与“删除”按钮；`role="admin"` 拥有全量管控权限。

- 核心管控功能

  ：

  - **全局数据看板**：实时展示所有采购单状态流转。
  - **Agent 审计日志**：集成 Langfuse Trace ID，点击即可查看单次任务的 Token 消耗与工具调用链路。
  - **人工接管 (Override)**：管理员可在后台点击“强行审批”，系统通过 API **反向唤醒**挂起的 LangGraph Thread，确保业务连续性。

------

## 四、 非功能性需求

### 4.1 可观测性 (Langfuse Day 0)

- 所有 LLM 调用、MCP 工具执行、State 变更必须生成 Trace。
- 需支持按 `session_id` (用户会话) 和 `thread_id` (LangGraph 线程) 进行链路聚合分析，为面试提供硬核数据截图。

------

## 五、 部署与运维方案

采用**基础设施即代码 (IaC)** 与现代云原生方案，实现极简交付：

1. **Docker Compose 一键拉起**：
   编写 `docker-compose.yml`，编排 PostgreSQL (专用于 LangGraph Checkpointer)、Mock-ERP (挂载本地 SQLite 文件)、LangGraph Agent 及 Langfuse。实现开发/测试/演示环境的 1 分钟极速部署。
2. **Chainlit 本地运行**：
   Agent 通过 Chainlit 框架运行，本地启动即可演示完整采购流程与 HITL 审批，无需公网 IP 或域名配置。

------

## 六、 测试与验收标准

### 6.1 核心指标验收 (基于 Langfuse 单轨数据推演)

无需编写双轨代码，直接通过 Langfuse 抓取 MCP 裁剪前后的数据对比，作为面试展示物料：

| 评估维度                | 原始 ERP JSON (未裁剪)  | MCP Pruning 后 (裁剪后) | 验收标准                 |
| ----------------------- | ----------------------- | ----------------------- | ------------------------ |
| Simulate 返回体积       | ~2500 Tokens (全量明细) | ~400 Tokens (摘要对比)  | 体积缩减 **> 80%**       |
| 单次任务总 Input Tokens | ~15,000 Tokens          | ~6,000 Tokens           | 上下文消耗降低 **> 60%** |
| 越权尝试次数            | >0 (LLM 偶发幻觉)       | 0 (MCP 层硬编码拦截)    | 安全漏洞 **0**           |

### 6.2 Agent 行为验收 (5 业务场景 Case 验证)

在每个场景的 LangGraph 节点增加断言式验证（单元测试 + 集成测试）：

| 场景 | 验收标准 | 自动化测试 |
|---|---|---|
| S1 常规采购 | Agent 正确选择推荐供应商或按用户意愿切换 | 单元测试覆盖各分支 |
| S2 库存不足 | Agent 解析 `agent_suggestion` 并向用户给出替代建议 | 模拟 mock-erp 返回 INSUFFICIENT_STOCK |
| S3 HITL 挂起 | Agent 在预算超标时进入 interrupt，Token 注入后成功 resume | 集成测试验证 interrupt/resume 闭环 |
| S4 阶梯凑单 | Agent 发现阶梯价差并主动提示用户 | 测试 seed 数据的阶梯价陷阱场景 |
| S5 综合寻源 | Agent 调用多供应商数据后给出综合推荐 | 测试种子的竞争报价数据 |

### 6.3 核心交付物与展示物料

1. **架构资产**：Mermaid 绘制的轻量级四层解耦与双库物理隔离架构图。
2. **演示视频**：1.5 倍速"一镜到底"录屏（Chainlit LUI 下单 -> 触发挂起 -> 审批弹窗恢复 -> 建单成功）。
3. **数据报告**：Langfuse Trace 瀑布流截图及 MCP 裁剪效果对比图。

------

## 七、 项目实施 Roadmap (Offer-Oriented 极限 3 周版)

**核心原则：先跑通主线，再 enrich 细节，永远保证项目处于“可演示”状态。**

### 🚀 Week 2: 核心大脑构建 (LangGraph + MCP)

*目标：脱离前端，在纯 Python 终端/脚本中，跑通 Agent 调用 ERP 工具的核心逻辑。*

- **Day 1**：定义 `AgentState`，搭建基础 `StateGraph` 骨架，配置 Langfuse 初始化。
- **Day 2**：Mock-ERP 核心 API 梳理，确保"查商品、试算、建单"接口可用并准备测试数据。
- **Day 3**：MCP Server 开发与数据裁剪，**核心精力放在 `simulate_purchase` 的 Response Pruning 上**。
- **Day 4**：异常捕获与自愈逻辑，处理 ERP 抛出的结构化错误（如 `409 库存不足`），触发替代方案。
- **Day 5**：HITL 闭环，实现 `interrupt` 机制。在终端模拟超预算场景，手动注入 `override_token` 恢复 Agent。

### 🧠 Week 3: 业务触达与多角色流转 (Chainlit)

*目标：将 Week 2 的大脑接入 Chainlit UI，完成 HITL 审批闭环。*

- **Day 1**：Chainlit 基础集成，接入 LangGraph Agent，实现消息收发与流式输出。
- **Day 2**：HITL 审批弹窗，Chainlit `AskActionMessage` 与 LangGraph `interrupt`/`resume` 联调。
- **Day 3**：角色切换命令，实现 `/role` 切换采购员/财务主管，完成全链路 E2E 测试。

### 🛳️ Week 4: 管控台、部署与资产包装 (冲刺 Offer)

*目标：补齐 ToB 系统的最后一块拼图，完成项目包装，准备投递。*

- **Day 1**：新建极简 `AdminUser` 单表，实现基于 SQLAdmin `AdminAuth` 的 Mock 登录拦截，并通过 ModelView 的 `is_accessible` 实现财务与管理员的**视图级 RBAC 控制**及"后台强行审批"功能。
- **Day 2**：编写 `docker-compose.yml`，将 Agent、ERP (挂载 SQLite)、PostgreSQL 打包，实现一键容器化部署。
- **Day 3**：绘制 Mermaid 架构图，编写核弹级 README（含痛点分析、双库隔离设计、MCP 裁剪对比、一键部署指南）。
- **Day 4**：录制 1.5 倍速高光演示视频，整理 Langfuse 截图，进行面试话术复盘。