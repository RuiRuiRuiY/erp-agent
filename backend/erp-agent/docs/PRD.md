# ERP-Agent 智能采购中枢 产品需求文档 (PRD V5.0)

**文档版本**：V5.0 (双库隔离与极简 RBAC 确权版)
**项目阶段**：Week 2 - Week 4 实施期
**核心依赖**：LangGraph, MCP, FastAPI, SQLite (WAL), PostgreSQL, 飞书开放平台, SQLAdmin

------

## 一、 产品定位与核心愿景

### 1.1 项目背景与破局思路

将 LLM 接入企业级 IM（如飞书）并驱动底层 ERP 流程，面临高并发超时、上下文爆炸、多角色测试受限等系统性工程挑战。
本项目摒弃“为了炫技而过度设计”的伪需求（如引入重型 Redis 队列、复杂的飞书卡片原位更新、双轨 A/B 代码开发），**聚焦于 AI Agent 的核心工程化能力**。通过内存异步削峰、MCP 协议数据裁剪、LangGraph 状态机挂起以及低代码管控台，构建一个高可用、可观测、具备人工兜底能力的 SaaS 级 Agent 落地标杆，以此作为极具竞争力的技术资产。

### 1.2 核心护城河 (面试核心考点)

1. **LangGraph 状态机与 HITL**：实现长时运行的审批挂起（interrupt）与外部 Token 唤醒（resume）。
2. **MCP 协议与数据裁剪 (Pruning)**：将庞大的 ERP JSON 转化为 LLM 友好的摘要，硬编码拦截越权，防幻觉。
3. **结构化异常自愈**：Agent 捕获 ERP 结构化错误（如 409 库存不足）并自动触发替代方案。
4. **Dev Mode 身份劫持**：单物理账号完美映射多逻辑角色，打通全链路 E2E 测试。

------

## 二、 系统总体架构设计

本项目采用**轻量级四层解耦与双库物理隔离架构**。业务数据与 Agent 状态数据彻底分离，在保证核心亮点的前提下，最大化开发 ROI。

| 架构层级   | 组件名称          | 技术选型                              | 核心职责与设计考量                                           |
| ---------- | ----------------- | ------------------------------------- | ------------------------------------------------------------ |
| **触达层** | 飞书网关          | FastAPI + `BackgroundTasks`           | 接收 Webhook，利用 FastAPI 原生后台任务实现**内存级异步**（防超时）；发送文本/结果卡片；实现 Dev Mode 身份劫持。 |
| **大脑层** | LangGraph Server  | Docker + **PostgreSQL**               | 运行 StateGraph，原生支持 `interrupt` 断点挂起；**PostgreSQL 作为 Checkpointer** 存储 State 快照，支撑跨天审批流恢复与复杂事务控制。 |
| **工具层** | MCP Server        | Python + `mcp` SDK                    | 拦截 Mock-ERP 响应，执行 Response Pruning（数据裁剪），硬编码拦截越权操作。 |
| **底座层** | Mock-ERP & 管控台 | FastAPI + **SQLite (WAL)** + SQLAdmin | 提供核心交易 API；**SQLite 开启 WAL 模式保障并发读写**，实现业务库零配置与轻量级；通过 SQLAdmin 构建带视图级 RBAC 的管理后台。 |
| **观测层** | 全链路追踪        | Langfuse                              | Day 0 接入，追踪 LLM 思考、Tool 调用耗时及 Token 消耗，提供单轨开发下的数据对比支撑。 |

------

## 三、 核心模块需求详细说明

### 3.1 飞书网关与轻量交互层 (Feishu Gateway)

- **内存异步与消息追加**：网关接收消息后，立即返回 200 OK 防止飞书超时重试。通过 `BackgroundTasks` 将推理任务放入后台。交互上摒弃复杂的卡片原位更新，采用 **“思考中提示文本 + 最终结果 Markdown 卡片”** 的多条消息追加模式，大幅降低开发成本。

- Dev Mode 身份劫持 (核心测试特性)

  ：

  - 引入 `DEV_MODE` 环境变量。开启后，网关层构建“逻辑平行宇宙”。
  - **输入伪装**：将唯一物理测试账号的 `open_id` 映射为逻辑层的 `采购员 Alice`。
  - **路由重定向**：当 Agent 触发超预算审批，需向 `财务主管 Bob` 发送卡片时，网关拦截目标地址，强制替换为物理测试账号，并在卡片注入 `[测试模式: 您正以 Bob 身份查看]` 标识。
  - **回调反向伪装**：物理账号点击审批卡片时，网关将操作者身份反向替换为 `Bob`，完成权限校验与 Thread 唤醒。

### 3.2 Agent 引擎与 MCP 工具层 (LangGraph & MCP)

- 状态定义 (Agent State)

  ：

  ```python
  class AgentState(TypedDict):
      messages: Annotated[list, add_messages]
      department_id: str           # 提取出的部门 ID
      cart_items: list             # 用户意图采购的商品清单
      simulate_result: dict        # 试算引擎返回的裁剪后数据
      po_draft_id: str             # 创建的草稿单 ID
      override_token: str          # 人类提供的特批 Token
      error_context: dict          # 捕获的结构化错误 (含 agent_suggestion)
  ```

- MCP 工具映射与 Pruning 策略 (核心技术壁垒)

  ：

  | MCP Tool 名称          | 对应 Mock-ERP API        | MCP Pruning (数据裁剪) 策略                                  | 预期优化    |
  | ---------------------- | ------------------------ | ------------------------------------------------------------ | ----------- |
  | `search_catalog`       | `GET /products`          | 剔除审计字段，仅保留 `id`, `sku`, `name`, `price`。          | 📉 Token 40% |
  | `simulate_purchase`    | `POST /pricing/simulate` | **智能摘要化**：仅保留推荐供应商明细，其他供应商仅保留总价和交期。 | 📉 Token 80% |
  | `draft_purchase_order` | `POST /po`               | MCP 层强制校验推理要素（如 `agent_reasoning`），否则拦截重写。 | 🛡️ 防幻觉    |
  | `transit_po_status`    | `POST /po/{id}/transit`  | MCP 层**硬编码** `operator_role="agent"`，封死 LLM 伪造角色的越权漏洞。 | 🛡️ 防越权    |

- 核心节点与路由 (HITL 挂起)

  ：

  - 在 `hitl_override_gate` 节点配置 `interrupt_before`。当预算超标时，Agent 挂起并持久化至 PostgreSQL。
  - 系统通过飞书卡片或 ERP 管控台向人类索要 `OVERRIDE_TOKEN`，注入后唤醒 Agent 继续执行。

### 3.3 Mock-ERP 与低代码管控台 (Admin Dashboard)

- 极简 Mock RBAC 鉴权体系

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
- 需支持按 `session_id` (飞书群/用户) 和 `thread_id` (LangGraph 线程) 进行链路聚合分析，为面试提供硬核数据截图。

------

## 五、 部署与运维方案

采用**基础设施即代码 (IaC)** 与现代云原生方案，实现极简交付：

1. **Docker Compose 一键拉起**：
   编写 `docker-compose.yml`，编排 PostgreSQL (专用于 LangGraph Checkpointer)、Mock-ERP (挂载本地 SQLite 文件)、LangGraph Agent 及 Langfuse。实现开发/测试/演示环境的 1 分钟极速部署。
2. **Cloudflare Tunnels 安全穿透**：
   通过 `cloudflared` 进程将本地运行的飞书网关映射为安全的公网 HTTPS 域名，免去购买公网 IP、配置域名及 SSL 证书的繁琐流程，安全接收飞书 Webhook 回调。

------

## 六、 测试与验收标准

### 6.1 核心指标验收 (基于 Langfuse 单轨数据推演)

无需编写双轨代码，直接通过 Langfuse 抓取 MCP 裁剪前后的数据对比，作为面试展示物料：

| 评估维度                | 原始 ERP JSON (未裁剪)  | MCP Pruning 后 (裁剪后) | 验收标准                 |
| ----------------------- | ----------------------- | ----------------------- | ------------------------ |
| Simulate 返回体积       | ~2500 Tokens (全量明细) | ~400 Tokens (摘要对比)  | 体积缩减 **> 80%**       |
| 单次任务总 Input Tokens | ~15,000 Tokens          | ~6,000 Tokens           | 上下文消耗降低 **> 60%** |
| 越权尝试次数            | >0 (LLM 偶发幻觉)       | 0 (MCP 层硬编码拦截)    | 安全漏洞 **0**           |

### 6.2 核心交付物与展示物料

1. **架构资产**：Mermaid 绘制的轻量级四层解耦与双库物理隔离架构图。
2. **演示视频**：1.5 倍速“一镜到底”录屏（飞书 LUI 下单 -> 触发挂起 -> 飞书卡片审批 / ERP 后台强行接管）。
3. **数据报告**：Langfuse Trace 瀑布流截图及 MCP 裁剪效果对比图。

------

## 七、 项目实施 Roadmap (Offer-Oriented 极限 3 周版)

**核心原则：先跑通主线，再 enrich 细节，永远保证项目处于“可演示”状态。**

### 🚀 Week 2: 核心大脑构建 (LangGraph + MCP)

*目标：脱离飞书，在纯 Python 终端/脚本中，跑通 Agent 调用 ERP 工具的核心逻辑。*

- **Day 1**：定义 `AgentState`，搭建基础 `StateGraph` 骨架，配置 Langfuse 初始化。
- **Day 2**：Mock-ERP 核心 API 梳理，确保“查商品、试算、建单”接口可用并准备测试数据。
- **Day 3**：MCP Server 开发与数据裁剪，**核心精力放在 `simulate_purchase` 的 Response Pruning 上**。
- **Day 4**：异常捕获与自愈逻辑，处理 ERP 抛出的结构化错误（如 `409 库存不足`），触发替代方案。
- **Day 5**：HITL 闭环，实现 `interrupt` 机制。在终端模拟超预算场景，手动注入 `override_token` 恢复 Agent。

### 🧠 Week 3: 业务触达与多角色流转 (飞书网关 + Dev Mode)

*目标：将 Week 2 的大脑接入飞书，解决单人测试多角色的痛点。*

- **Day 1**：极简飞书网关，使用 FastAPI 接收 Webhook，使用 `BackgroundTasks` 实现内存异步，发送文本/卡片。
- **Day 2**：Dev Mode 身份劫持，在 Middleware 中实现输入伪装、路由重定向与 `[测试模式]` 标签注入。
- **Day 3**：飞书卡片交互与 Thread 唤醒，接收审批回调，调用 LangGraph API 恢复挂起的 Thread。
- **Day 4**：上下文管理与多轮对话，处理群聊状态，确保 `thread_id` 正确传递。
- **Day 5**：全链路联调与 Bug 修复，在飞书端完整跑通采购与审批流。

### 🛳️ Week 4: 管控台、部署与资产包装 (冲刺 Offer)

*目标：补齐 ToB 系统的最后一块拼图，完成项目包装，准备投递。*

- **Day 1**：新建极简 `AdminUser` 单表，实现基于 SQLAdmin `AdminAuth` 的 Mock 登录拦截，并通过 ModelView 的 `is_accessible` 实现财务与管理员的**视图级 RBAC 控制**及“后台强行审批”功能。
- **Day 2**：编写 `docker-compose.yml`，将 Agent、ERP (挂载 SQLite)、PostgreSQL 打包，实现一键容器化部署。
- **Day 3**：配置 Cloudflare Tunnels，将本地服务映射到公网，确保飞书 Webhook 稳定回调。
- **Day 4**：绘制 Mermaid 架构图，编写核弹级 README（含痛点分析、双库隔离设计、MCP 裁剪对比、一键部署指南）。
- **Day 5**：录制 1.5 倍速高光演示视频，整理 Langfuse 截图，进行面试话术复盘。