import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base, get_db
from models import Tenant, User, Transaction, TransactionTypeEnum
from main import app
import uuid

from sqlalchemy.pool import StaticPool

# Setup SQLite in-memory database for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

@pytest.fixture
def db_session():
    """Provides a fresh database session for a test and rolls back after."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture
def setup_test_data(db_session):
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    
    tenant = Tenant(id=tenant_id, business_name="Test UMKM", subscription_tier="FREE")
    user = User(id=user_id, tenant_id=tenant_id, whatsapp_number="628123456789", role="OWNER")
    
    db_session.add(tenant)
    db_session.add(user)
    db_session.commit()
    return {"tenant_id": str(tenant_id), "user_id": str(user_id), "whatsapp": "628123456789"}

def test_get_user_by_whatsapp_success(setup_test_data):
    # Try exact match
    response = client.get(f"/users/by-whatsapp/{setup_test_data['whatsapp']}")
    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == setup_test_data["tenant_id"]
    assert data["user_id"] == setup_test_data["user_id"]

def test_get_user_by_whatsapp_not_found(db_session):
    response = client.get("/users/by-whatsapp/08999999999")
    assert response.status_code == 404
    assert "tidak terdaftar" in response.json()["detail"]

def test_create_transaction_success(setup_test_data, db_session):
    payload = {
        "tenant_id": setup_test_data["tenant_id"],
        "user_id": setup_test_data["user_id"],
        "source": "whatsapp",
        "items": [
            {"item": "Kopi", "quantity": 2, "price": 15000}
        ],
        "total_amount": 30000,
        "notes": "Test transaction",
        "category": "Food"
    }
    
    response = client.post("/transactions", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    
    # Verify in DB
    tx = db_session.query(Transaction).filter_by(tenant_id=setup_test_data["tenant_id"]).first()
    assert tx is not None
    assert tx.amount == 30000
    assert tx.category == "Food"
    assert "Kopi" in tx.description

def test_create_transaction_invalid_tenant(setup_test_data):
    payload = {
        "tenant_id": str(uuid.uuid4()), # Non-existent tenant
        "user_id": setup_test_data["user_id"],
        "items": [{"item": "Kopi", "quantity": 1, "price": 10000}]
    }
    response = client.post("/transactions", json=payload)
    assert response.status_code == 404
    assert "Tenant tidak ditemukan" in response.json()["detail"]
