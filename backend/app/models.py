from datetime import datetime, timezone
from sqlalchemy import String, Text, Boolean, Float, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

def now():
    return datetime.now(timezone.utc)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default='pending')

class Care(Base):
    __tablename__ = 'care_logs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    worker_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'), nullable=True, index=True)
    encrypted_content: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30))
    urgency: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(40))
    confidence: Mapped[float] = mapped_column(Float)
    review_required: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Audit(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(40))
    target: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Attendance(Base):
    __tablename__ = 'attendance_logs'
    __table_args__ = (UniqueConstraint('owner_id', 'day'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    day: Mapped[str] = mapped_column(String(10))
