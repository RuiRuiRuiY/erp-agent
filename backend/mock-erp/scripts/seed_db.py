"""Seed database with master data and business trap scenarios."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import DB_PATH, engine, init_db
from app.model import (
    Budget,
    Department,
    Product,
    Supplier,
    SupplierPricelist,
)
from sqlmodel import Session

# ---------------------------------------------------------------------------
# Master Data
# ---------------------------------------------------------------------------

PRODUCTS = [
    Product(sku="LOGITECH_MOUSE", name="罗技无线鼠标", category="外设"),
    Product(sku="DELL_MONITOR_27", name="戴尔27寸显示器", category="显示器"),
    Product(sku="MACBOOK_PRO_16", name="高配MacBook Pro 16寸", category="电脑"),
    Product(sku="ERGO_CHAIR", name="人体工学椅", category="家具"),
    Product(sku="SERVER_X10", name="机架式服务器 X10", category="服务器"),
    Product(sku="MECH_KEYBOARD", name="机械键盘", category="外设"),
]

SUPPLIERS = [
    Supplier(code="SUP_A", name="深圳宏达电子", default_lead_time_days=15, rating=4.5),
    Supplier(code="SUP_B", name="上海极速科技", default_lead_time_days=2, rating=4.0),
    Supplier(code="SUP_C", name="广州万通商贸", default_lead_time_days=7, rating=4.8),
]

DEPARTMENTS = [
    Department(code="DEPT_IT", name="IT 部"),
    Department(code="DEPT_RD", name="研发部"),
    Department(code="DEPT_DESIGN", name="设计部"),
    Department(code="DEPT_FINANCE", name="财务部"),
]

BUDGETS = [
    Budget(department_id="", fiscal_year=2026, total_budget=20_000_000, used_budget=0),
    Budget(department_id="", fiscal_year=2026, total_budget=5_000_000, used_budget=4_500_000),
    Budget(department_id="", fiscal_year=2026, total_budget=10_000_000, used_budget=0),
    Budget(department_id="", fiscal_year=2026, total_budget=3_000_000, used_budget=0),
]

# unit_price in 分 (cents)
PRICELISTS = [
    # -- 罗技鼠标: 阶梯价陷阱 --
    # 90个 * 100 = 9000元, 100个 * 80 = 8000元 → 多买10个反而省1000元
    SupplierPricelist(supplier_id="", product_id="", min_qty=1, unit_price=10_000),
    SupplierPricelist(supplier_id="", product_id="", min_qty=100, unit_price=8_000),
    # -- 戴尔显示器: 价格 vs 交期陷阱 --
    # SUP_A: 1000元/台 but 15天交期
    SupplierPricelist(supplier_id="", product_id="", min_qty=1, unit_price=100_000),
    # SUP_B: 1200元/台 but 2天交期
    SupplierPricelist(supplier_id="", product_id="", min_qty=1, unit_price=120_000),
    # -- 人体工学椅: 预算红线陷阱 --
    # 600元/把, 10把=6000元, 研发部只剩5000元
    SupplierPricelist(supplier_id="", product_id="", min_qty=1, unit_price=60_000),
    # -- MacBook Pro --
    SupplierPricelist(supplier_id="", product_id="", min_qty=1, unit_price=3_000_000),
    # -- 服务器: 阶梯凑单陷阱 --
    # 48台*10000=48万, 50台*9000=45万 → 多买2台省3万
    SupplierPricelist(supplier_id="", product_id="", min_qty=1, unit_price=1_000_000),
    SupplierPricelist(supplier_id="", product_id="", min_qty=10, unit_price=950_000),
    SupplierPricelist(supplier_id="", product_id="", min_qty=50, unit_price=900_000),
    # -- 机械键盘 (有竞争报价) --
    SupplierPricelist(supplier_id="", product_id="", min_qty=1, unit_price=50_000),
    SupplierPricelist(supplier_id="", product_id="", min_qty=1, unit_price=45_000),
]


def seed() -> None:
    DB_PATH.unlink(missing_ok=True)
    init_db()

    product_map: dict[str, str] = {}
    supplier_map: dict[str, str] = {}
    department_map: dict[str, str] = {}

    with Session(engine) as session:
        # -- products --
        for p in PRODUCTS:
            session.add(p)
            session.flush()
            product_map[p.sku] = p.id
        print(f"  products: {len(PRODUCTS)}")

        # -- suppliers --
        for s in SUPPLIERS:
            session.add(s)
            session.flush()
            supplier_map[s.code] = s.id
        print(f"  suppliers: {len(SUPPLIERS)}")

        # -- departments --
        for d in DEPARTMENTS:
            session.add(d)
            session.flush()
            department_map[d.code] = d.id
        print(f"  departments: {len(DEPARTMENTS)}")

        # -- budgets (need department_id) --
        budget_data = [
            (department_map["DEPT_IT"], 20_000_000, 0,
             "IT 部年度预算 20万元"),
            (department_map["DEPT_RD"], 5_000_000, 4_500_000,
             "研发部年度预算: 已花4.5万, 仅剩5000元"),
            (department_map["DEPT_DESIGN"], 10_000_000, 0,
             "设计部年度预算 10万元"),
            (department_map["DEPT_FINANCE"], 3_000_000, 0,
             "财务部年度预算 3万元"),
        ]
        for dept_id, total, used, note in budget_data:
            session.add(Budget(
                department_id=dept_id, fiscal_year=2026,
                total_budget=total, used_budget=used,
            ))
            print(f"    {note}")
        print("  budgets: 4")

        # -- pricelists (need supplier_id + product_id) --
        pricelist_specs = [
            ("SUP_C", "LOGITECH_MOUSE", 1, 10_000, "罗技鼠标 基础价 100元/个"),
            ("SUP_C", "LOGITECH_MOUSE", 100, 8_000, "罗技鼠标 满100个 80元/个（阶梯价诱惑陷阱）"),
            ("SUP_A", "DELL_MONITOR_27", 1, 100_000,
             "戴尔显示器 SUP_A: 1000元/台, 交期15天"),
            ("SUP_B", "DELL_MONITOR_27", 1, 120_000,
             "戴尔显示器 SUP_B: 1200元/台, 交期2天（价格vs交期陷阱）"),
            ("SUP_C", "ERGO_CHAIR", 1, 60_000, "人体工学椅 600元/把（预算红线陷阱）"),
            ("SUP_C", "MACBOOK_PRO_16", 1, 3_000_000, "MacBook Pro 30000元/台"),
            ("SUP_A", "SERVER_X10", 1, 1_000_000, "服务器 基础价 10000元/台"),
            ("SUP_A", "SERVER_X10", 10, 950_000, "服务器 满10台 9500元/台（95折）"),
            ("SUP_A", "SERVER_X10", 50, 900_000, "服务器 满50台 9000元/台（9折）（凑单陷阱）"),
            ("SUP_C", "MECH_KEYBOARD", 1, 50_000, "机械键盘 SUP_C: 500元/个"),
            ("SUP_A", "MECH_KEYBOARD", 1, 45_000, "机械键盘 SUP_A: 450元/个（有竞争报价）"),
        ]
        for sup_code, prod_sku, min_qty, price, _note in pricelist_specs:
            session.add(
                SupplierPricelist(
                    supplier_id=supplier_map[sup_code],
                    product_id=product_map[prod_sku],
                    min_qty=min_qty,
                    unit_price=price,
                )
            )
        print(f"  pricelists: {len(pricelist_specs)}")

        session.commit()
        print(f"\n[OK] DB seeded: {DB_PATH}")

    # -- summary --
    print()
    print("=" * 50)
    print("业务陷阱场景:")
    print("=" * 50)
    print("""1. [陷阱] 价格 vs 交期: 戴尔显示器
   - SUP_A: 1000元/台, 交期15天
   - SUP_B: 1200元/台, 交期2天

2. [陷阱] 预算红线: 研发部采购人体工学椅
   - 研发部剩余预算: 5000元
   - 人体工学椅: 600元/把 x 10把 = 6000元 -> 超标1000元

3. [陷阱] 阶梯凑单: 服务器采购
   - 48台 x 10000 = 48万
   - 50台 x 9000 = 45万 -> 多买2台省3万

4. [陷阱] 竞争报价: 机械键盘
   - SUP_C: 500元/个
   - SUP_A: 450元/个（更低价格）""")


if __name__ == "__main__":
    seed()
