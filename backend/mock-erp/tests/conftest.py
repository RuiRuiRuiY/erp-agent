from collections.abc import Generator
from pathlib import Path

import pytest
from app.model import (
    Budget,
    Department,
    Inventory,
    Product,
    PurchaseOrder,  # noqa: F401  # registers with SQLModel.metadata
    PurchaseOrderLine,  # noqa: F401  # registers with SQLModel.metadata
    Supplier,
    SupplierPricelist,
)
from sqlmodel import Session, SQLModel, create_engine

_TEMP_DB = Path(__file__).parent / "_test_temp.db"


def _build_engine() -> any:
    if _TEMP_DB.exists():
        _TEMP_DB.unlink()
    engine = create_engine(
        f"sqlite:///{_TEMP_DB}",
        connect_args={"check_same_thread": False},
    )
    return engine


engine = _build_engine()


@pytest.fixture(autouse=True)
def _setup_db():
    SQLModel.metadata.create_all(engine)
    yield
    SQLModel.metadata.drop_all(engine)


@pytest.fixture()
def session() -> Generator[Session]:
    with Session(engine) as s:
        yield s


@pytest.fixture()
def seed_data(session: Session):
    prod_mouse = Product(sku="LOGITECH_MOUSE", name="罗技无线鼠标", category="外设")  # noqa: E501
    prod_monitor = Product(sku="DELL_MONITOR_27", name="戴尔27寸显示器", category="显示器")  # noqa: E501
    prod_chair = Product(sku="ERGO_CHAIR", name="人体工学椅", category="家具")
    prod_server = Product(sku="SERVER_NO_PRICELIST", name="无报价服务器", category="服务器")
    session.add_all([prod_mouse, prod_monitor, prod_chair, prod_server])
    session.flush()

    sup_a = Supplier(code="SUP_A", name="深圳宏达电子", default_lead_time_days=15, rating=4.5)
    sup_b = Supplier(code="SUP_B", name="上海极速科技", default_lead_time_days=2, rating=4.0)
    session.add_all([sup_a, sup_b])
    session.flush()

    dept_it = Department(code="DEPT_IT", name="IT 部")
    dept_rd = Department(code="DEPT_RD", name="研发部")
    session.add_all([dept_it, dept_rd])
    session.flush()

    session.add_all([
        Budget(
            department_id=dept_it.id, fiscal_year=2026,
            total_budget=200_000_00, used_budget=0, frozen_budget=0,
        ),
        Budget(
            department_id=dept_rd.id, fiscal_year=2026,
            total_budget=50_000_00, used_budget=45_000_00,
            frozen_budget=0,
        ),
    ])

    session.add_all([
        Inventory(product_id=prod_mouse.id, total_qty=200, locked_qty=0),
        Inventory(product_id=prod_monitor.id, total_qty=5, locked_qty=0),
        Inventory(product_id=prod_chair.id, total_qty=5, locked_qty=0),
    ])

    plists = [
        (sup_a.id, prod_mouse.id, 1, 10_000),
        (sup_a.id, prod_mouse.id, 100, 8_000),
        (sup_a.id, prod_monitor.id, 1, 100_000),
        (sup_b.id, prod_monitor.id, 1, 120_000),
        (sup_b.id, prod_mouse.id, 1, 9_500),
        (sup_b.id, prod_chair.id, 1, 60_000),
    ]
    session.add_all([
        SupplierPricelist(supplier_id=s, product_id=p, min_qty=m, unit_price=u)
        for s, p, m, u in plists
    ])

    session.commit()

    return {
        "products": {
            "mouse": prod_mouse, "monitor": prod_monitor,
            "chair": prod_chair, "server_no_pricelist": prod_server,
        },
        "suppliers": {"A": sup_a, "B": sup_b},
        "departments": {"IT": dept_it, "RD": dept_rd},
    }


@pytest.fixture()
def client(session: Session):
    from app.api.deps import get_db_session
    from app.main import app
    from fastapi.testclient import TestClient

    def _override():
        yield session

    app.dependency_overrides[get_db_session] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
