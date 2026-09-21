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

class Preference(Base):
    __tablename__ = 'preferences'
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    local_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class ServiceRegion(Base):
    __tablename__ = 'service_regions'
    __table_args__ = (UniqueConstraint('owner_id', 'province', 'district'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    province: Mapped[str] = mapped_column(String(30))
    district: Mapped[str] = mapped_column(String(30))

class Availability(Base):
    __tablename__ = 'availability'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    caregiver_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    province: Mapped[str] = mapped_column(String(30))
    district: Mapped[str] = mapped_column(String(30))
    day: Mapped[str] = mapped_column(String(10), index=True)
    start: Mapped[str] = mapped_column(String(5))
    end: Mapped[str] = mapped_column(String(5))
    state: Mapped[str] = mapped_column(String(20), default='open')

class Booking(Base):
    __tablename__ = 'bookings'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    slot_id: Mapped[str] = mapped_column(ForeignKey('availability.id'), index=True)
    elder_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    category: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default='pending')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Coordination(Base):
    __tablename__ = 'booking_coordination'
    booking_id: Mapped[str] = mapped_column(ForeignKey('bookings.id'), primary_key=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    care_id: Mapped[str | None] = mapped_column(ForeignKey('care_logs.id'), nullable=True, unique=True)

class VisitRecord(Base):
    __tablename__ = 'visit_records'
    booking_id: Mapped[str] = mapped_column(ForeignKey('bookings.id'), primary_key=True)
    caregiver_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    outcome: Mapped[str] = mapped_column(String(20))
    encrypted_note: Mapped[str] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class RepeatCase(Base):
    __tablename__ = 'repeat_cases'
    __table_args__ = (UniqueConstraint('elder_id', 'category'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    elder_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    category: Mapped[str] = mapped_column(String(30))
    worker_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    state: Mapped[str] = mapped_column(String(20), default='open')
    auto_route: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    followup_day: Mapped[str | None] = mapped_column(String(10), nullable=True)
    encrypted_decision: Mapped[str | None] = mapped_column(Text, nullable=True)

class ScheduleProposal(Base):
    __tablename__ = 'schedule_proposals'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    booking_id: Mapped[str] = mapped_column(ForeignKey('bookings.id'), index=True)
    slot_id: Mapped[str] = mapped_column(ForeignKey('availability.id'))
    caregiver_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    stage: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default='offered')
    encrypted_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class CareDecision(Base):
    __tablename__ = 'care_decisions'
    care_id: Mapped[str] = mapped_column(ForeignKey('care_logs.id'), primary_key=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    method: Mapped[str] = mapped_column(String(20))
    suggested_urgency: Mapped[str] = mapped_column(String(20))
    final_urgency: Mapped[str] = mapped_column(String(20))
    ai_prepared: Mapped[bool] = mapped_column(Boolean, default=False)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    encrypted_handoff: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class CaregiverTeam(Base):
    __tablename__ = 'caregiver_teams'
    caregiver_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)

class RouteLocation(Base):
    __tablename__ = 'route_locations'
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    encrypted_point: Mapped[str] = mapped_column(Text)
    consent: Mapped[bool] = mapped_column(Boolean, default=False)
    departure: Mapped[str] = mapped_column(String(5), default='08:00')

class CheckinPreference(Base):
    __tablename__ = 'checkin_preferences'
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)

class CheckinDay(Base):
    __tablename__ = 'checkin_days'
    __table_args__ = (UniqueConstraint('owner_id','day'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    day: Mapped[str] = mapped_column(String(10))
    attempts: Mapped[int] = mapped_column(default=0)
    state: Mapped[str] = mapped_column(String(20), default='waiting')
    token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    next_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
