你之前总结的这套“开发规范与工程准备”已经**非常成熟，具备了高级后端工程师的工程素养**。特别是“统一异常处理返回结构化 JSON”和“引入 Ruff”，这在面试或技术评审中是绝对的加分项。

为了让这个项目从“优秀的标准 Web 项目”彻底蜕变为 **“优秀的 Agent-Native (面向智能体) 企业级 PoC 项目”**，我建议在工程准备上做以下 **4 点关键补充与微调**，并在最后为你提供一份清晰的**开发 Roadmap**。

---

### 一、 对“工程准备”的补充与修改建议

#### 1. 目录结构微调：增加“配置中心”，移除 Agent 专属层

原有的扁平化结构在项目变大后容易臃肿。建议引入 `core` 层管理配置和数据库连接，剥离 `agent/` 层（该目录属于 `erp-agent` 项目职责，mock-erp 不包含 LLM 客户端代码）。

```text
mock-erp/
├── app/
│   ├── main.py   
│   ├── core/   
│   │   ├── config.py   
│   │   ├── database.py   
│   │   └── exceptions.py   
│   │
│   ├── model/                  # 🌟 ORM 模型 (严格 1:1 映射 DDL 表名，绝不乱造词)
│   │   ├── __init__.py         # 统一导出所有模型，方便 Alembic 或 create_all 使用
│   │   ├── base.py             # SQLModel 公共基类 (id, created_at)
│   │   ├── product.py          # 对应 DDL: products
│   │   ├── supplier.py         # 对应 DDL: suppliers
│   │   ├── supplier_pricelist.py # 对应 DDL: supplier_pricelists (独立文件，因为它是核心定价引擎)
│   │   ├── inventory.py        # 对应 DDL: inventory (库存锁定/释放)
│   │   ├── department.py       # 对应 DDL: departments
│   │   ├── budget.py           # 对应 DDL: budgets (含 frozen_budget)
│   │   └── purchase_order.py   # 对应 DDL: purchase_orders & purchase_order_lines (主子表强绑定，放同一文件)
│   │
│   ├── schema/                 # 🌟 Pydantic 契约 (按业务动作和实体划分)
│   │   ├── __init__.py
│   │   ├── common.py           # 统一响应体 (如 {"code": 200, "data": ...})
│   │   ├── product.py          # 商品查询出参 (Agent 需要知道有哪些商品)
│   │   ├── department.py       # 部门查询出参 (Agent 需要知道有哪些部门)
│   │   ├── pricing.py          # 核心：价格试算入参/出参 (SimulateRequest/Response)
│   │   ├── purchase_order.py   # 核心：采购单创建/查询/状态流转 入参/出参
│   │   ├── inventory.py        # 库存查询出参 (Agent 查可用量)
│   │   └── budget.py           # 预算查询出参 (Agent 查余额，含 frozen_budget)
│   │
│   ├── api/                    # 🌟 路由层 (RESTful 端点)
│   │   ├── deps.py             # 依赖注入 (get_db)
│   │   └── v1/
│   │       ├── router.py   
│   │       ├── product.py      # GET /products
│   │       ├── department.py   # GET /departments
│   │       ├── pricing.py      # POST /pricing/simulate
│   │       ├── purchase_order.py # POST/GET/PATCH /purchase-orders
│   │       └── budget.py       # GET /budgets/{department_id}
│   │
│   ├── repository/             # 🌟 仓储层 (文件名严格对齐 model)
│   │   ├── __init__.py
│   │   ├── product.py          # 查商品
│   │   ├── supplier.py         # 查供应商
│   │   ├── supplier_pricelist.py # 查阶梯报价 (包含复杂 SQL)
│   │   ├── inventory.py        # 库存的原子更新 (行级锁)
│   │   ├── department.py       # 查部门
│   │   ├── budget.py           # 预算的原子更新 (行级锁/乐观锁, 含 frozen_budget)
│   │   └── purchase_order.py   # 采购单主子表的联合持久化
│   │
│   ├── service/                # 🌟 业务逻辑层 (聚焦核心交易与计算)
│   │   ├── __init__.py
│   │   ├── pricing.py          # 试算引擎 (比价算法)
│   │   ├── purchase_order.py   # 采购单状态机流转 (编排预算 + 库存操作)
│   │   └── budget.py           # 预算原子性读写 (供 purchase_order 调用)
│   │
│   # └── agent/                # ❌ 已移除，该目录属于 erp-agent 项目
```

#### 2. 统一异常处理：补充“HTTP 状态码规范”与“Agent 建议字段”

Agent 不仅读取 JSON Body，**对 HTTP 状态码也非常敏感**。

- 补充规范

  ：

  - `400 Bad Request`: 参数校验失败。
  - `403 Forbidden`: 状态机越权（如 Agent 试图以普通员工身份审批）。
  - `409 Conflict`: 业务冲突（如预算不足、库存不够）。
  - `422 Unprocessable Entity`: Pydantic 格式错误。

> **说明**：本规范中的 HTTP 状态码与早期 PRD 草案有所不同——业务冲突（预算不足/库存不够/状态机非法跃迁）统一使用 `409 Conflict`，而非 `400 Bad Request`。`409` 在 REST 语义上更准确（请求本身合法，但当前资源状态不允许），且能让 Agent 更精确地判断错误类型。

- JSON 结构强化

  ：在返回的 JSON 中强制包含 `agent_suggestion` 字段。

  ```json
  {
    "error_code": "BUDGET_INSUFFICIENT",
    "message": "部门预算不足",
    "context": {"required": 15000, "remaining": 12000},
    "agent_suggestion": "CALL_TOOL: simulate_pricing with reduced quantities, OR CALL_TOOL: notify_human_manager"
  }
  ```

#### 3. 种子数据 (Seed Data) 设计：故意制造“业务陷阱”

不要只生成平庸的正常数据。**好的 PoC 演示需要“戏剧冲突”**。建议在 `seed_db.py` 中故意设计以下场景，用来测试 Agent 的智商：

- **陷阱 1 (价格 vs 交期)**：供应商 A 的显示器单价 1000 元，交期 15 天；供应商 B 的显示器单价 1200 元，交期 2 天。看 Agent 是否会根据 Prompt 中的“紧急程度”做出不同选择。
- **陷阱 2 (预算红线)**：研发部本月预算只剩 5000 元，但 Agent 收到的指令是“买 10 把单价 600 元的人体工学椅”。测试 Agent 是否能触发“预算不足”异常，并**自主决定**将数量砍到 8 把，或者向人类发起审批请求。
- **陷阱 3 (阶梯价诱惑)**：买 90 个鼠标单价 100 元，买 100 个鼠标单价 80 元。测试 Agent 是否会为了触发低价阶梯，主动建议人类“多买 10 个凑单反而更省钱”。
- **陷阱 4 (库存不足)**：戴尔显示器可用库存仅 20 台，但 Agent 收到指令“买 50 台”。测试 Agent 能否捕获库存不足错误并主动提出替代方案。

#### 4. 代码规范补充：加入 `pyright` 静态类型检查

既然用了 Pydantic 和 SQLModel，**类型提示 (Type Hints) 就是系统的灵魂**。

- **建议**：在 `pre-commit` 中除了 `ruff`，务必加上 `pyright` (basedpyright)。在 README 中写上：“*本项目采用 Ruff + Pyright 进行严格的代码格式与静态类型检查，确保 Agent 工具契约的绝对严谨。*” 这会让面试官觉得你极其专业。

---

### 二、 项目开发 Roadmap (路线图)

为了保证项目有条不紊地推进，并随时能拿出“可演示”的成果，我建议将开发分为 **4 个 Sprint (迭代)**。

#### 🚩 Sprint 1: 基础设施与数据底座 (预计耗时: 20%)

**目标：搭好架子，跑通数据库，有数据可查。**

- [X] **Task 1.1**: 初始化 `pyproject.toml` (配置 Ruff) 和 `.pre-commit-config.yaml`。
- [X] **Task 1.2**: 编写 `app/core/database.py` (配置 SQLite，**关键：通过事件监听器激活 `PRAGMA foreign_keys = ON`**)。
- [X] **Task 1.3**: 编写 `app/core/exceptions.py` (定义 `BusinessException` 及全局拦截器)。
- [X] **Task 1.4**: **严格翻译 DDL**，编写 `app/model/` 下的 8 个模型文件，确保字段类型、约束（如 `CHECK(status IN ...)`）与 DDL 100% 一致。
- [X] **Task 1.5**: 编写 `scripts/seed_db.py`，利用这些 Model 注入带有“业务陷阱”的种子数据。

- **🏆 里程碑 1**：运行 seed 脚本，本地生成完美的 `mock_erp.db`，且外键约束和 Check 约束在 SQLite 中真实生效。

#### 🚩 Sprint 2: 核心 API 与业务逻辑 – 垂直切片 (预计耗时: 40%)

**目标：按业务领域垂直切片，每个 Task 交付完整的 "schema + repository + service + API"。**

**Phase A: 只读查询 (Read APIs) — 快速出成果**

- [X] **Task 2.1**: 商品与供应商目录 API

  - `schema/product.py`, `schema/supplier.py`
  - `repository/product.py`, `repository/supplier.py`, `repository/supplier_pricelist.py`
  - `api/v1/product.py` (GET /products), `api/v1/supplier.py` (GET /suppliers)
  - 测试: 目录查询
- [X] **Task 2.2**: 部门与预算 API

  - `schema/department.py`, `schema/budget.py`
  - `repository/department.py`, `repository/budget.py`
  - `api/v1/department.py` (GET /departments), `api/v1/budget.py` (GET /budgets/{dept_id})
  - 测试: 预算查询
- [X] **Task 2.3**: 库存 API

  - `schema/inventory.py`
  - `repository/inventory.py` (+ 原子更新辅助方法)
  - `api/v1/inventory.py` (GET /inventory/{product_id})
  - 测试: 库存查询

- **🏆 里程碑 2A**：启动 FastAPI (`uvicorn`)，所有只读 API 可通过 Swagger UI 调用。

**Phase B: 核心交易 (Write APIs)**

- [X] **Task 2.4**: **攻坚** 价格试算引擎 🌟

  - `schema/pricing.py` (SimulateRequest/Response)
  - `service/pricing.py` (多供应商阶梯比价算法)
  - `api/v1/pricing.py` (POST /pricing/simulate)
  - 测试: 阶梯匹配 + 推荐逻辑 (含陷阱数据验证)
- [X] **Task 2.5**: 采购单创建

  - `schema/purchase_order.py` (create 部分)
  - `repository/purchase_order.py` (主子表持久化)
  - `service/purchase_order.py` (创建逻辑，含后端定价固化快照)
  - `api/v1/purchase_order.py` (POST /po)
  - 测试: PO 创建
- [X] **Task 2.6**: **攻坚** 状态机流转 — 预算+库存联动 🌟

  - `schema/purchase_order.py` (transit 部分)
  - `service/purchase_order.py` (transit 编排 + guard/action)
  - `repository/budget.py` (冻结合并操作), `repository/inventory.py` (锁定操作)
  - `api/v1/purchase_order.py` (POST /po/{id}/transit)
  - 测试: 完整 Happy Path + 各种边界（预算不足、库存不够、非法跃迁）

- **🏆 里程碑 2B**：完成完整的"比价 → 建单 → 提审 → 扣预算"全流程。

#### 🚩 Sprint 3: API 完备度与场景支撑 (预计耗时: 25%)

**目标：补齐所有 PRD 场景所需的 API 端点，移除越界目录。mock-erp 定位为纯 REST API 服务方，不包含 LLM 客户端代码。**

> **设计原则**：mock-erp 是"被调用方"，只提供标准 REST API + 结构化错误 + 业务规则校验。LLM 客户端、Function Calling、System Prompt 属于 `erp-agent` 项目职责。

- [x] **Task 3.1**: 商品搜索 `GET /products?q=关键词` (PRD 场景 A/E)
  
  - `repository/product.py`: 增加 `name` / `category` 的 `LIKE` 查询
  - `api/v1/product.py`: 增加 `q: str \| None = Query(None)` 可选参数
- 向后兼容：`q=None` 时行为不变
  
- [x] **Task 3.2**: 供应商报价查询 `GET /suppliers/{id}/pricelists` (PRD 场景 D)
  - `schema/supplier.py`: 新增 `PricelistItemRead`（含 `valid_from`、`valid_to`）
  - `repository/supplier_pricelist.py`: 复用 `get_pricelists_by_supplier`（Task 3.7 加过滤后自动受益）
  - `api/v1/supplier.py`: 新增端点，支持 `?product_id=UUID` 过滤
  - 支撑 Agent 查看所有阶梯边界以做凑单决策

- [x] **Task 3.3**: 预算超标特批接口 `POST /po/override` (PRD 场景 C) 🌟
  - `app/core/config.py`: 新增 `OVERRIDE_TOKEN` 环境变量
  - `app/model/purchase_order.py`: `PurchaseOrder` 新增 `is_override: bool = Field(default=False)`
  - `app/repository/budget.py`: `freeze_budget` 增加 `force=False` 参数（跳过余额校验，不改表）
  - `app/service/purchase_order.py`:
    - 新增 `create_purchase_order_override()` 服务函数（校验 token → 强制冻结预算 → 创建 PO 设 `is_override=True`）
    - `transit_po()` guard `recheck_budget_and_stock`: 如果 `po.is_override`，跳过预算重校验（库存重校验仍保留）
  - `app/schema/purchase_order.py`: 新增 `POCreateOverrideRequest`（含 `override_token: str`）
  - `app/api/v1/purchase_order.py`: 新增 `POST /po/override` 端点
  - 流程：Agent 建单遇 `409 BUDGET_INSUFFICIENT` → 询问用户 → 用户提供 token → Agent 调 override 建单 → transit 自动跳过预算重检
- 测试
  
- [x] **Task 3.4**: 试算结果增强交期信息 `POST /pricing/simulate` (PRD 场景 E)
  - `schema/pricing.py`: `SupplierTotalQuote` 新增 `default_lead_time_days: int`、`rating: float`
  - `service/pricing.py`: 构建 `all_quotes` 时从 `Supplier` 模型填充这两个字段（已有 `get_suppliers_by_ids` 数据）
  - 支撑 Agent 一次调用做"价格+交期+评分"综合决策
- 测试
  
- [x] **Task 3.5**: 移除 `app/agent/` 越界目录
  - 删除 `app/agent/tools.py`、`app/agent/prompts.py`、`app/agent/__init__.py`
  - 涉及该目录的文档同步更新
  - 这些文件属于 `erp-agent` 项目职责

- [x] **Task 3.6**: 新端点测试覆盖
  - `test_api_product.py`: 搜索命中、无结果、空 q 向后兼容
  - `test_api_pricelist.py`: 正常返回、按 product_id 过滤、supplier 不存在 404
  - `test_api_purchase_order.py` / `test_service_purchase_order.py`:
    - Override 正常创建、无效 token 403、库存不足仍拒绝
    - 特批单 DRAFT→PENDING 跳过预算重检
    - 正常单 DRAFT→PENDING 仍报预算不足
  - `test_service_pricing.py`: Simulate 返回体中 `lead_time_days` 和 `rating` 正确

- [x] **Task 3.7**: 启用阶梯报价有效期校验 🌟
  - **背景**：`SupplierPricelist` 模型已有 `valid_from` / `valid_to` 字段，但 repository 层 4 个查询函数**均不过滤**。如果系统包含过期或未来日期的报价，会导致以下级联错误：
    ```
    POST /pricing/simulate  → 返回过期报价 ❌
    POST /po               → 固化过期价格到 PO → 冻结/扣减预算基于错误金额 ❌
    GET /suppliers/{id}/pricelists (Task 3.2) → 展示过期数据 ❌
    ```
    已创建的 PO 不受影响：价格已在 `PurchaseOrderLine.unit_price` 固化为快照，pricelist 过期不影响已有采购单。
  - `repository/supplier_pricelist.py`: 新增 `_active_filter()` 通用函数，应用到全部 4 个查询：
    ```python
    from datetime import date
    
    def _active_filter(stmt):
        today = date.today().isoformat()
        return stmt.where(
            SupplierPricelist.valid_from <= today,
            (SupplierPricelist.valid_to == None) |
            (SupplierPricelist.valid_to >= today),
        )
    ```
  - 不改 model、不改 schema、不改 seed 数据（seed 默认 `valid_from=today, valid_to=None`，自然通过过滤）
  - `tests/test_repository_supplier_pricelist.py`（新增）:
    - 过期报价不被 `get_pricelists_by_product_ids` 返回
    - 未来报价不被 `get_pricelists_by_supplier_and_products` 返回
    - 混合数据（有效+过期）只返回有效数据

- **🏆 里程碑 3**：API 面完备，覆盖 PRD 全部 5 个场景的接口需求。所有 pricelist 查询已启用有效期过滤，过期/未来报价不会进入业务逻辑。

#### 🚩 Sprint 4: 端到端测试、容器化与演示准备 (预计耗时: 15%)

**目标：打包交付，准备“惊艳”面试官或评审委员。**

- [ ] **Task 4.1**: 编写 `Dockerfile` 和 `docker-compose.yml`，实现一键 `docker-compose up` 启动整个系统。
- [ ] **Task 4.2**: 完善 `README.md`，画出**系统架构图**和**状态机流转图**（用 Mermaid 语法）。
- [ ] **Task 4.3**: 准备 3 个经典的 Demo 演示剧本（Script）：

- *剧本 A (常规流程)*：Agent 完美比价并下单。
- *剧本 B (预算拦截)*：Agent 遭遇预算不足，自主调整方案。
- *剧本 C (防幻觉测试)*：人类故意诱导 Agent 买不存在的商品，Agent 严谨拒绝。
- **🏆 最终里程碑**：项目完全工程化，可随时在任意机器上拉起演示。

##### TODO

- [X] valid_from / valid_to 字段已预留但未被 service 层使用。当前的种子数据和 service 都无视有效期，这是一个"死字段"风险——后续如果生效期逻辑，现有查询会拿到过期阶梯价。
  - **已在 Sprint 3 Task 3.7 修复**：repository 层 4 个查询函数均已加 `_active_filter()` 过滤，过期/未来报价不再进入业务逻辑。

---

### 你的决定？

这份 Roadmap 将庞大的系统拆解为了可执行的步骤。

如果你认可这个工程规范和 Roadmap，**我们可以立刻开始 Sprint 1 的第一个 Task**：我可以为你生成标准的 `pyproject.toml` 配置（包含 Ruff 和 Pyright 规则），或者为你编写带有 `PRAGMA` 激活的 `database.py` 核心代码。

你想先从哪一部分开始落地？
