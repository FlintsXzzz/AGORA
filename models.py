import uuid
from sqlalchemy import Column, String, Text, Numeric, Enum as SQLEnum, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timezone
import enum

from database import Base

class RoleEnum(str, enum.Enum):
    OWNER = "OWNER"
    EMPLOYEE = "EMPLOYEE"

class TransactionTypeEnum(str, enum.Enum):
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"

class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_name = Column(String, nullable=False)
    subscription_tier = Column(String, nullable=False, default="FREE")

    users = relationship("User", back_populates="tenant")
    transactions = relationship("Transaction", back_populates="tenant")

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    whatsapp_number = Column(String, unique=True, nullable=False)
    role = Column(SQLEnum(RoleEnum), nullable=False, default=RoleEnum.EMPLOYEE)

    tenant = relationship("Tenant", back_populates="users")
    transactions = relationship("Transaction", back_populates="recorded_by_user")

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    recorded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    type = Column(SQLEnum(TransactionTypeEnum), nullable=False, default=TransactionTypeEnum.EXPENSE)
    amount = Column(Numeric, nullable=False)
    category = Column(String, nullable=False, default="Uncategorized")
    description = Column(Text, nullable=True)
    raw_image_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    tenant = relationship("Tenant", back_populates="transactions")
    recorded_by_user = relationship("User", back_populates="transactions")
