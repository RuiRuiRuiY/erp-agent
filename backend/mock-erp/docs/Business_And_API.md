太棒了！数据底座（DDL）已经彻底夯实，现在我们正式进入整个系统最核心、也最精彩的环节：**第三步：核心业务逻辑与 API 契约设计**。

在这个阶段，我们的核心设计理念是 **“API 即工具 (API as Tools)”**。因为我们的调用方主要是 AI Agent，所以 API 契约不仅要严谨，还要**对大模型极度友好**（提供清晰的错误原因、返回辅助推理的上下文）。

以下是详细的业务逻辑与 API 契约设计方案（包含 Pydantic Schema 示例与核心算法伪代码，不包含具体 CRUD 实现）。

------

### 一、 核心 API 契约设计 (Pydantic Schemas)

在 API 层面，我们遵循 **“人类/Agent 视角”**，所有金额字段均使用 `float`（单位：元）。在 Service 层写入数据库前，再统一转换为 `int`（单位：分）。

#### 1. 价格试算与寻源引擎 (Simulate Engine) 🌟

这是 Agent 在创建采购单前，必须调用的“比价”工具。

- **路由**: `POST /api/v1/pricing/simulate`
- **业务目的**: 给定一个采购需求清单，系统自动遍历所有供应商的阶梯报价，返回**每个供应商的总价明细**，并给出**系统推荐的最优方案**。

```python
from pydantic import BaseModel, Field
from typing import List, Optional
from uuid import UUID

# --- 入参：采购需求清单 ---
class SimulateRequestItem(BaseModel):
    product_id: UUID
    quantity: int = Field(gt=0)

class SimulateRequest(BaseModel):
    department_id: UUID
    items: List[SimulateRequestItem]

# --- 出参：试算结果与比价明细 ---
class SupplierQuoteDetail(BaseModel):
    """某个供应商针对某商品的报价明细（展示阶梯命中情况）"""
    product_id: UUID
    product_name: str
    quantity: int
    hit_tier_min_qty: int      # 命中的阶梯门槛（如：满100件）
    unit_price: float          # 命中阶梯的单价（元）
    subtotal: float            # 小计（元）

class SupplierTotalQuote(BaseModel):
    """单个供应商的整体报价汇总"""
    supplier_id: UUID
    supplier_name: str
    total_amount: float        # 该供应商总价（元）
    can_fulfill: bool          # 是否能满足所有商品的采购需求（有些供应商可能缺某个商品）
    line_details: List[SupplierQuoteDetail]

class SimulateResponse(BaseModel):
    """试算引擎最终返回给 Agent 的结果"""
    department_remaining_budget: float # 部门剩余预算（元），供 Agent 判断是否超标
    
    all_quotes: List[SupplierTotalQuote] # 所有有效供应商的报价清单
    
    # 🌟 Agent 辅助决策字段
    recommended_supplier_id: Optional[UUID] = None
    recommendation_reason: Optional[str] = None # 例如："供应商A总价最低，且交期满足"
```

#### 2. 采购单创建 (Create PO)

Agent 根据 `simulate` 的结果，决定向哪个供应商下单。

- **路由**: `POST /api/v1/po`

```python
class CreatePOLineRequest(BaseModel):
    product_id: UUID
    quantity: int = Field(gt=0)
    # 注意：这里不需要传 unit_price，后端会根据当前生效的 pricelist 自动计算并固化快照，防止 Agent 篡改价格

class CreatePORequest(BaseModel):
    supplier_id: UUID
    department_id: UUID
    lines: List[CreatePOLineRequest]
    agent_reasoning: str = Field(description="Agent 选择该供应商的推理过程，用于审计")

class CreatePOResponse(BaseModel):
    po_id: UUID
    po_number: str
    status: str # 默认返回 "DRAFT"
    total_amount: float # 订单总金额（元）
```

#### 3. 状态机流转 (Transit PO Status)

控制采购单的生命周期，并与预算系统联动。

- **路由**: `POST /api/v1/po/{po_id}/transit`

```python
class TransitStatusRequest(BaseModel):
    target_status: str = Field(description="目标状态，如 'PENDING', 'APPROVED', 'REJECTED'")
    operator_role: str = Field(default="agent", description="操作者角色，如 'agent', 'finance_manager'")

class TransitStatusResponse(BaseModel):
    po_id: UUID
    old_status: str
    new_status: str
    budget_impact: Optional[str] = None # 例如："已冻结预算 ¥5000.00" 或 "预算不足，冻结失败"
```

------

### 二、 核心业务逻辑设计 (伪代码)

这里我们不写具体的 SQL 查询代码，而是用伪代码理清**最复杂的业务算法**和**状态机流转规则**。

#### 1. 多供应商阶梯寻源算法 (Simulate 核心逻辑)

当 Agent 传入 `[商品A: 150个, 商品B: 20个]` 时，系统如何计算？

```python
def simulate_pricing_logic(items: List[SimulateRequestItem]):
    # 1. 获取所有相关商品的有效报价矩阵 (按 supplier_id 分组)
    # pricelists_map = {supplier_id: [pricelist_records...]}
    
    all_quotes = []
    
    for supplier_id, pricelists in pricelists_map.items():
        supplier_quote = SupplierTotalQuote(supplier_id=supplier_id, ...)
        
        for item in items:
            # 2. 筛选出该供应商对该商品的有效报价，并按 min_qty 降序排列
            valid_tiers = get_valid_tiers(pricelists, item.product_id)
            
            # 3. 🌟 阶梯匹配算法：找到满足 item.quantity >= tier.min_qty 的最高阶梯
            hit_tier = None
            for tier in valid_tiers: 
                if item.quantity >= tier.min_qty:
                    hit_tier = tier
                    break # 因为已降序，第一个命中的就是最优阶梯
            
            if hit_tier:
                # 计算小计 (注意：这里在内存中用 Decimal 计算，最后转 float)
                subtotal = Decimal(hit_tier.unit_price) * item.quantity 
                supplier_quote.line_details.append(...)
            else:
                # 该供应商没有该商品的报价，或者数量未达到最低起订量
                supplier_quote.can_fulfill = False 
                
        # 4. 汇总该供应商总价
        if supplier_quote.can_fulfill:
            supplier_quote.total_amount = sum(line.subtotal for line in supplier_quote.line_details)
            
        all_quotes.append(supplier_quote)
        
    # 5. 🌟 推荐逻辑：在 can_fulfill=True 的供应商中，找 total_amount 最低的
    recommended = min([q for q in all_quotes if q.can_fulfill], key=lambda x: x.total_amount, default=None)
    
    return SimulateResponse(all_quotes=all_quotes, recommended_supplier_id=recommended.id, ...)
```

#### 2. 状态机与预算联动控制 (Transit 核心逻辑)

这是保障财务安全的核心。状态流转不能只是改个字符串，必须伴随**前置校验 (Guard)** 和**副作用 (Action)**。

```python
# 定义状态机规则
STATE_MACHINE = {
    'DRAFT': {
        'PENDING': {'guard': 'check_budget', 'action': 'freeze_budget'},
        'CANCELLED': {'action': None}
    },
    'PENDING': {
        'APPROVED': {'guard': 'is_finance_role', 'action': 'deduct_budget'}, # 审批通过，冻结转为实际扣减
        'REJECTED': {'guard': 'is_finance_role', 'action': 'unfreeze_budget'}, # 驳回，释放冻结预算
        'CANCELLED': {'action': 'unfreeze_budget'}
    },
    'REJECTED': {'DRAFT': {'action': None}}, # 驳回后退回草稿修改
    # ... 其他状态
}

def transit_po_logic(po_id: UUID, target_status: str, operator_role: str):
    po = get_po(po_id)
    current_status = po.status
    
    # 1. 校验状态流转合法性
    if target_status not in STATE_MACHINE.get(current_status, {}):
        raise InvalidTransitionError(f"不允许从 {current_status} 跳转到 {target_status}")
        
    transition_rule = STATE_MACHINE[current_status][target_status]
    
    # 2. 执行前置校验 (Guard)
    if 'guard' in transition_rule:
        if transition_rule['guard'] == 'check_budget':
            budget = get_budget(po.department_id)
            if budget.remaining < po.total_amount:
                # 🌟 抛出结构化错误，让 Agent 明确知道原因
                raise BudgetInsufficientError(
                    required=po.total_amount, 
                    remaining=budget.remaining,
                    suggestion="请减少采购数量或申请追加预算"
                )
        elif transition_rule['guard'] == 'is_finance_role' and operator_role != 'finance_manager':
            raise PermissionDeniedError("审批操作需要财务经理权限")
            
    # 3. 执行副作用 (Action) - 涉及预算变动
    if 'action' in transition_rule:
        if transition_rule['action'] == 'freeze_budget':
            freeze_budget(po.department_id, po.total_amount)
        elif transition_rule['action'] == 'unfreeze_budget':
            unfreeze_budget(po.department_id, po.total_amount)
        elif transition_rule['action'] == 'deduct_budget':
            deduct_budget(po.department_id, po.total_amount)
            
    # 4. 更新状态并保存
    po.status = target_status
    save(po)
```

------

### 三、 面向 Agent 的 API 设计亮点 (面试/答辩加分项)

在传统的后端开发中，API 报错通常只返回一个 `400 Bad Request` 和一句简单的 `"Budget insufficient"`。但在 **Agent-Native 架构**中，我们需要做特殊优化：

1. **结构化的错误反馈 (Structured Errors)**
   当预算不足时，API 应该返回包含具体数值的 JSON，而不是纯文本。

   ```json
   {
     "error_code": "BUDGET_INSUFFICIENT",
     "message": "部门预算不足，无法提交审批。",
     "context": {
       "required_amount": 15000.00,
       "remaining_budget": 12000.00,
       "deficit": 3000.00
     },
     "agent_suggestion": "建议将采购数量从 150 减少至 120，或提示人类主管追加预算。"
   }
   ```

   *收益：Agent 读到这个 JSON 后，不需要人类干预，就能自动调用 `simulate` 重新计算 120 个的数量，或者自动生成一封“申请追加预算”的邮件草稿发给人类。*

2. **强制的推理留痕 (Mandatory Reasoning)**
   在 `CreatePORequest` 中，`agent_reasoning` 被设计为必填项（或在 Prompt 中强烈要求）。
   *收益：解决了 AI 系统的“黑盒”问题。当财务审计时，可以直接看到：“*Agent 选择供应商 B，是因为虽然供应商 A 单价低 5 元，但供应商 B 承诺次日达，且总价在预算范围内。*”

3. **防篡改的价格计算 (Server-Side Pricing)**
   在创建 PO 的 API 中，**绝对不允许 Agent 传入 `unit_price`**。Agent 只能传 `product_id` 和 `quantity`。
   *收益：价格必须由后端 Service 层根据当前生效的 `supplier_pricelists` 实时计算并固化。这防止了 Agent 产生幻觉，传入一个极低的价格导致公司遭受损失（即所谓的“Prompt 注入攻击”防线之一）。*

------

### 下一步行动确认

到这里，我们已经完成了：

1. **数据底座**：严谨的 SQLite DDL（主子表设计、分币存储、状态机约束）。
2. **业务逻辑**：阶梯比价算法、状态机与预算联动规则。
3. **API 契约**：面向 Agent 优化的 Pydantic Schema 和错误反馈机制。

整个系统的“骨架”和“神经系统”已经设计完毕。