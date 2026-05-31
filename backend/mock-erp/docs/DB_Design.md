太棒了！需求已经完全锁定，现在我们正式进入**第二步：技术架构与数据模型设计 (DB Design)**。

按照你的要求，我将聚焦于**架构选型、实体关系梳理以及核心表结构的 Schema 设计**，并提供必要的 SQLModel（Pydantic + SQLAlchemy）示例代码来辅助说明，**绝不涉及具体的 CRUD 业务逻辑和接口实现代码**。

------

### 一、 技术架构概览 (Agent-Native 架构)

为了支撑大模型 Agent 的高效调用，我们的后端架构需要遵循 **“重模型、轻路由、强校验”** 的原则。

- **Web 框架**：FastAPI (自带 OpenAPI 文档，对 Agent 的 Function Calling 极其友好)。

- **ORM / 数据校验**：SQLModel (完美融合了 Pydantic 的数据校验和 SQLAlchemy 的 ORM 能力，一套代码同时搞定 DB 表和 API Schema)。

- **数据库**：SQLite 3。

- ⚠️ SQLite 专属架构注意事项

  ：

  1. **外键激活**：SQLite 默认**关闭**外键约束。在应用启动连接数据库时，必须执行 `PRAGMA foreign_keys = ON;`。
  2. **类型映射**：SQLite 没有原生的 `UUID`、`ENUM` 和 `DATETIME` 类型。在 DDL 中，我们将使用 `TEXT` 来存储 UUID (36位字符串) 和 ISO8601 格式的时间，使用 `TEXT` 配合 `CHECK` 约束来模拟枚举（状态机）。

- 架构分层

  ：

  - **API 层 (Routers)**：极简，只负责接收请求和返回响应，直接暴露给 Agent 作为 Tools。
  - **Service 层 (Core Logic)**：包含状态机流转、价格试算引擎（`simulate` 的核心逻辑）、预算扣减等。
  - **Repository 层 (DB)**：纯粹的数据访问层。

------

### 二、 核心实体关系设计 (ER 概念)

我们彻底摒弃了“商品自带价格”的传统思维，构建了一个以 **“采购交易”** 为核心的星型/雪花型拓扑结构：

1. **Product (商品)** 与 **Supplier (供应商)** 是多对多关系。
2. **SupplierPricelist (报价矩阵)** 是连接两者的关联表，并承载了**阶梯定价**和**时间有效性**的核心业务逻辑。
3. **Inventory (库存)** 维护每个商品的库存水位，`available_qty = total_qty - locked_qty` 用于 Agent 采购时的可用量校验。
4. **PurchaseOrder (采购单)** 属于某个 Department (部门)，并消耗其 Budget (预算)。
5. **PurchaseOrderLine (采购明细)** 记录单次采购的具体商品、数量和**成交时的快照价格**。

------

### 三、 核心产出物：数据库 DDL 设计

以下是完整的 SQLite DDL 脚本。它不仅是建表语句，更是我们业务规则的“硬编码”体现（通过唯一索引和 CHECK 约束）。

```sqlite
-- ==========================================
-- 1. 基础档案层 (Master Data)
-- ==========================================
CREATE TABLE products (
    id TEXT PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    unit_of_measure TEXT DEFAULT 'PCS',
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE suppliers (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    default_lead_time_days INTEGER DEFAULT 7,
    rating REAL DEFAULT 5.0 CHECK(rating >= 0 AND rating <= 5),
    is_active INTEGER DEFAULT 1
);

-- ==========================================
-- 2. 核心定价引擎 (Pricing Engine)
-- ==========================================
CREATE TABLE supplier_pricelists (
    id TEXT PRIMARY KEY,
    supplier_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    min_qty INTEGER NOT NULL CHECK(min_qty >= 1),
    
    -- 🌟 修正：金额改为 INTEGER，单位：分
    unit_price INTEGER NOT NULL CHECK(unit_price >= 0), 
    
    valid_from TEXT DEFAULT (date('now')),
    valid_to TEXT,
    FOREIGN KEY (supplier_id) REFERENCES suppliers(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE UNIQUE INDEX idx_supplier_product_qty 
ON supplier_pricelists(supplier_id, product_id, min_qty);

-- ==========================================
-- 3. 库存控制 (Inventory Control)
-- ==========================================
CREATE TABLE inventory (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL UNIQUE,
    total_qty INTEGER NOT NULL CHECK(total_qty >= 0),
    locked_qty INTEGER DEFAULT 0 CHECK(locked_qty >= 0),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

-- ==========================================
-- 4. 财务与预算控制 (Finance & Budget)
-- ==========================================
CREATE TABLE departments (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL
);

CREATE TABLE budgets (
    id TEXT PRIMARY KEY,
    department_id TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    -- 🌟 修正：金额改为 INTEGER，单位：分
    total_budget INTEGER NOT NULL CHECK(total_budget >= 0),
    used_budget INTEGER DEFAULT 0 CHECK(used_budget >= 0),
    frozen_budget INTEGER DEFAULT 0 CHECK(frozen_budget >= 0),
    FOREIGN KEY (department_id) REFERENCES departments(id)
);

CREATE UNIQUE INDEX idx_dept_fiscal_year ON budgets(department_id, fiscal_year);

-- ==========================================
-- 5. 交易与状态机 (Transactions & State Machine)
-- ==========================================
CREATE TABLE purchase_orders (
    id TEXT PRIMARY KEY,
    po_number TEXT NOT NULL UNIQUE,
    supplier_id TEXT NOT NULL,
    department_id TEXT NOT NULL,
    
    -- 🌟 修正：状态机扩充
    status TEXT NOT NULL DEFAULT 'DRAFT' 
        CHECK(status IN ('DRAFT', 'PENDING', 'APPROVED', 'REJECTED', 'ORDERED', 'SHIPPED', 'RECEIVED', 'CANCELLED')),
        
    -- 🌟 修正：金额改为 INTEGER，单位：分
    total_amount INTEGER DEFAULT 0,
    
    created_by_agent INTEGER DEFAULT 0,
    agent_reasoning TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (supplier_id) REFERENCES suppliers(id),
    FOREIGN KEY (department_id) REFERENCES departments(id)
);

CREATE TABLE purchase_order_lines (
    id TEXT PRIMARY KEY,
    po_id TEXT NOT NULL,
    -- 🌟 坚持使用 product_id，保持交易数据与基础档案的关联，而非动态配置
    product_id TEXT NOT NULL, 
    
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    -- 🌟 修正：金额改为 INTEGER，单位：分 (交易快照)
    unit_price INTEGER NOT NULL CHECK(unit_price >= 0), 
    
    FOREIGN KEY (po_id) REFERENCES purchase_orders(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE INDEX idx_po_lines_po_id ON purchase_order_lines(po_id);
```



### 四、 针对 Agent 场景的 3 个关键设计考量

在上面的 Schema 设计中，我埋了几个专门针对 AI Agent 交互的“彩蛋”，在面试或答辩时可以作为亮点提出：

1. 用 `CHECK` 约束捍卫状态机底线

   - **设计**：在 `purchase_orders` 表中，`status` 字段使用了 `CHECK(status IN (...))`。
   - **收益**：大模型 Agent 有时会“自由发挥”，试图直接将状态从 `DRAFT` 更新为 `SHIPPED`（一个不存在的状态）。这个 DDL 层面的硬约束，确保了即使 Agent 产生了幻觉，数据库也会直接拒绝写入（抛出 `IntegrityError`），从而保护了核心交易数据的一致性。

2. 用复合唯一索引 (`UNIQUE INDEX`) 保证报价矩阵的严谨性

   - **设计**：`idx_supplier_product_qty` 索引限制了 `(supplier_id, product_id, min_qty)` 的唯一性。
   - **收益**：在真实的 ERP 中，绝不允许出现“供应商 A 对商品 B，在满 10 件时既有 90 元的报价，又有 85 元的报价”这种脏数据。这个索引从物理层面杜绝了阶梯定价配置的冲突，让后端的 `simulate` 试算引擎在取“最优阶梯价”时逻辑更简单、更安全。

3. 交易快照与审计追踪分离

   - **设计**：`purchase_order_lines` 固化了 `unit_price`；`purchase_orders` 增加了 `agent_reasoning`。

    - **收益**：前者保证了财务数据的不可篡改性（历史订单金额不随今日调价而改变）；后者为 AI 系统提供了宝贵的“可解释性”数据。当人类审计员问“AI 为什么选这家供应商”时，系统可以直接读取 `agent_reasoning` 字段进行回答。

4. 预算与库存的对称锁定机制

   - **设计**：`budgets` 表增加 `frozen_budget` 字段，新增 `inventory` 表记录 `locked_qty`。状态机流转时，预算冻结/扣减/释放与库存锁定/消耗/解锁严格对称执行。
   - **收益**：Agent 在提交审批时，系统同时锁定预算和库存，确保资源不被重复分配。驳回或取消时同步释放，避免预算和库存状态不一致。这种"双重锁定"模式是真实 ERP 的核心财务逻辑。

   - 同时建议在应用层维护一个**状态机**来约束合法跳转：

      ```python
       # 应用层状态机设计示例 (伪代码)
       # 说明：预算冻结和库存锁定在 create_purchase_order（DRAFT 创建）时已完成，
       #       因此 DRAFT → PENDING 不再重复冻结，改为重新校验。
       STATE_MACHINE = {
           'DRAFT': {
               'transitions': {
                   'PENDING': {
                       'guard': 'recheck_budget_and_stock',  # 重新校验：预算和库存是否仍然充足
                       'action': None  # 冻结已在创建时完成，此处只加状态
                   },
                   'CANCELLED': {'action': 'unfreeze_budget_and_unlock_stock'}
               }
           },
           'PENDING': {
               'transitions': {
                   'APPROVED': {'guard': 'is_finance_manager', 'action': 'deduct_budget_and_consume_stock'},
                   'REJECTED': {'guard': 'is_finance_manager', 'action': 'unfreeze_budget_and_unlock_stock'},
                   'CANCELLED': {'action': 'unfreeze_budget_and_unlock_stock'}
               }
           },
           'REJECTED': {
               'transitions': {
                   'DRAFT': {'action': None},
               }
           },
           'APPROVED': {
               'transitions': {
                   'ORDERED': {'action': None},
                   'CANCELLED': {'action': 'reverse_approval'},
               }
           },
           'ORDERED': {
               'transitions': {
                   'SHIPPED': {'action': None},
                   'CANCELLED': {'action': None},
               }
           },
           'SHIPPED': {
               'transitions': {
                   'RECEIVED': {'action': None},
               }
           },
      }
      ```

   - 为了更好地配合 Agent，建议在状态机中引入 **“副作用 (Side Effects)”** 和 **“角色权限 (Guards)”** 的概念：

     ```py
      # 应用层状态机设计示例 (伪代码)
      STATE_MACHINE = {
          'DRAFT': {
              'transitions': {
                  'PENDING': {
                      'guard': 'check_budget_and_stock',  # 触发条件：预算充足且库存足够
                      'action': 'freeze_budget_and_lock_stock' # 副作用：冻结预算 + 锁定库存
                  },
                  'CANCELLED': {'action': None}
              }
          },
          'PENDING': {
              'transitions': {
                  'APPROVED': {'guard': 'is_finance_manager', 'action': 'confirm_budget_deduction_and_consume_stock'},
                  'REJECTED': {'guard': 'is_finance_manager', 'action': 'unfreeze_budget_and_unlock_stock'}, # 驳回必须释放预算和库存
                  'CANCELLED': {'action': 'unfreeze_budget_and_unlock_stock'}
              }
          },
         # ... 其他状态
     }
     ```

     - **为什么这样设计？**

       当 Agent 试图调用 `POST /api/v1/po/{id}/approve` 时，如果预算不足或 Agent 没有财务角色权限，状态机会直接拦截并返回明确的错误原因（如 `"error": "Budget freeze failed"`），这比直接报数据库错误对 Agent 友好得多。

------

### 你的决定？

这套基于 SQLModel 的数据模型设计，既保证了关系型数据库的严谨性（外键、唯一约束），又兼顾了 Pydantic 的数据校验能力，同时为 Agent 留出了充足的推理空间。

如果你觉得这套 DB Design 方案没问题，我们就可以进入**第三步：核心业务逻辑与 API 契约设计**（重点攻克 `simulate` 试算引擎的算法逻辑和状态机流转规则）。

准备好继续推进了吗？