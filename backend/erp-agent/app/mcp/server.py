"""
mcp-erp-server

MCP Tool → Mock-ERP API 映射清单 (共 13 端点 → 10 个工具)

工具名              Method  路径                                  入参                               响应概要
------------------  ------  ------------------------------------  ---------------------------------  -------------------------------
search_product      GET     /api/v1/products                      ?q=, ?skip=, ?limit=              [{id, sku, name, category,
                                                                                                      unit_of_measure, is_active}]
                    GET     /api/v1/products/{product_id}         path: product_id                   {id, sku, name, category,
                                                                                                      unit_of_measure, is_active}

check_department    GET     /api/v1/departments                   ?skip=, ?limit=                    [{id, code, name}]
                    GET     /api/v1/departments/{department_id}   path: department_id                {id, code, name}

check_budget        GET     /api/v1/budgets/{department_id}       path: department_id,               {department_id, fiscal_year,
                                                                  ?fiscal_year=                      total_budget, used_budget,
                                                                                                      frozen_budget, available}

check_inventory     GET     /api/v1/inventory/{product_id}        path: product_id                   {id, product_id, total_qty,
                                                                                                      locked_qty, available_qty}

list_suppliers      GET     /api/v1/suppliers                     ?skip=, ?limit=                    [{id, code, name, rating,
                                                                                                      default_lead_time_days}]
                    GET     /api/v1/suppliers/{supplier_id}       path: supplier_id                  {id, code, name, rating,
                                                                                                      default_lead_time_days}

get_supplier_pricelist GET  /api/v1/suppliers/{id}/pricelists     path: supplier_id,                  [{id, supplier_id, product_id,
                                                                  ?product_id=                       min_qty, unit_price,
                                                                                                      valid_from, valid_to}]

simulate_purchase   POST    /api/v1/pricing/simulate              body: {department_id,               {department_remaining_budget,
                                                                   items: [{product_id,               all_quotes: [...],
                                                                   quantity}]}                         recommended_supplier_id,
                                                                                                       recommended_supplier_name,
                                                                                                       recommendation_reason,
                                                                                                       skipped_suppliers}

draft_purchase_order POST   /api/v1/po                            body: {department_id,               {id, po_number, status,
                                                                    supplier_id, items: [{             total_amount, created_at,
                                                                    product_id, quantity}],            supplier_name, department_name,
                                                                    agent_reasoning}                   lines: [...]}

override_purchase_order POST /api/v1/po/override                  同 draft 但添加 override_token       同上

transit_po_status   POST    /api/v1/po/{po_id}/transit            path: po_id,                        {po_id, po_number,
                                                                    body: {target_status,              old_status, new_status,
                                                                    operator_role}                     budget_impact}
"""
import json

from fastmcp import FastMCP

from app.mcp.erp_client import get, post
from app.mcp.interceptor import require_agent_reasoning, enforce_operator_role, catch_erp_error

mcp = FastMCP("mcp-erp-server")


@mcp.tool(description="搜索商品列表（按关键词 q）或查单个商品详情（product_id）")
@catch_erp_error
async def search_product(
    q: str = "",
    product_id: str = "",
    skip: int = 0,
    limit: int = 100,
) -> str:
    if product_id:
        data = await get(f"/products/{product_id}")
    else:
        params = {"skip": skip, "limit": limit}
        if q:
            params["q"] = q
        data = await get("/products", params=params)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool(description="查询部门列表或单个部门详情")
@catch_erp_error
async def check_department(department_id: str = "", skip: int = 0, limit: int = 100) -> str:
    if department_id:
        data = await get(f"/departments/{department_id}")
    else:
        data = await get("/departments", params={"skip": skip, "limit": limit})
    return json.dumps(data, ensure_ascii=False)


@mcp.tool(description="查询部门预算（含 available 计算字段）")
@catch_erp_error
async def check_budget(department_id: str, fiscal_year: int | None = None) -> str:
    params = {}
    if fiscal_year is not None:
        params["fiscal_year"] = fiscal_year
    data = await get(f"/budgets/{department_id}", params=params)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool(description="查询商品库存（含 available_qty 计算字段）")
@catch_erp_error
async def check_inventory(product_id: str) -> str:
    data = await get(f"/inventory/{product_id}")
    return json.dumps(data, ensure_ascii=False)


@mcp.tool(description="列出供应商或查单个供应商详情")
@catch_erp_error
async def list_suppliers(supplier_id: str = "", skip: int = 0, limit: int = 100) -> str:
    if supplier_id:
        data = await get(f"/suppliers/{supplier_id}")
    else:
        data = await get("/suppliers", params={"skip": skip, "limit": limit})
    return json.dumps(data, ensure_ascii=False)


@mcp.tool(description="查供应商价目表（可按商品筛选）")
@catch_erp_error
async def get_supplier_pricelist(supplier_id: str, product_id: str = "") -> str:
    params = {}
    if product_id:
        params["product_id"] = product_id
    data = await get(f"/suppliers/{supplier_id}/pricelists", params=params)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool(description="试算采购方案，获取多方报价与推荐供应商")
@catch_erp_error
async def simulate_purchase(department_id: str, items: list) -> str:
    body = {"department_id": department_id, "items": items}
    data = await post("/pricing/simulate", body)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool(description="草拟采购订单（普通流程）")
@catch_erp_error
async def draft_purchase_order(
    department_id: str, supplier_id: str, items: list, agent_reasoning: str
) -> str:
    require_agent_reasoning(agent_reasoning, "draft_purchase_order")
    body = {"department_id": department_id, "supplier_id": supplier_id, "items": items, "agent_reasoning": agent_reasoning}
    data = await post("/po", body)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool(description="越权创建采购订单（需 Override Token）")
@catch_erp_error
async def override_purchase_order(
    department_id: str,
    supplier_id: str,
    items: list,
    override_token: str,
    agent_reasoning: str,
) -> str:
    require_agent_reasoning(agent_reasoning, "override_purchase_order")
    body = {
        "department_id": department_id,
        "supplier_id": supplier_id,
        "items": items,
        "override_token": override_token,
        "agent_reasoning": agent_reasoning,
    }
    data = await post("/po/override", body)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool(description="流转采购订单状态（如 PENDING→APPROVED, APPROVED→ISSUED）")
@catch_erp_error
async def transit_po_status(po_id: str, target_status: str, operator_role: str = "purchaser") -> str:
    operator_role = enforce_operator_role(operator_role)
    body = {"target_status": target_status, "operator_role": operator_role}
    data = await post(f"/po/{po_id}/transit", body)
    return json.dumps(data, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
