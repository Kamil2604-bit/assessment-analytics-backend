import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./saas_analytics.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=5,
        max_overflow=0
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class ClientAccount(Base):
    __tablename__ = "client_accounts"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)
    role = Column(String, default="client_admin")
    institute = Column(String, index=True)
    display_name = Column(String)


class StudentRoster(Base):
    __tablename__ = "student_roster"
    id = Column(Integer, primary_key=True, index=True)
    institute = Column(String, index=True)
    roll_no = Column(String, index=True)
    name = Column(String)
    department = Column(String, default="General")
    section = Column(String, default="General")
    email = Column(String, default="")


class AssessmentRecord(Base):
    __tablename__ = "assessment_records"
    id = Column(Integer, primary_key=True, index=True)
    institute = Column(String, index=True)
    roll_no = Column(String, index=True)
    name = Column(String)
    department = Column(String, default="General")
    section = Column(String, default="General")
    assessment_date = Column(Date, index=True)
    score_percentage = Column(Float, default=0.0)
    status = Column(String, default="Present")
    conduct_metrics = Column(String, default="GENUINE")
    report_link = Column(Text, default="")
    source_file = Column(String, index=True)


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    id = Column(Integer, primary_key=True, index=True)
    institute = Column(String, index=True)
    roll_no = Column(String, index=True)
    name = Column(String)
    contact = Column(String, default="")
    email = Column(String, default="")
    department = Column(String, index=True)
    section = Column(String, index=True)
    session_date = Column(Date, index=True)
    session_slot = Column(String)
    session_label = Column(String)
    is_conducted = Column(Integer, default=1)  # 1 = Conducted, 0 = Holiday / Cancelled
    status = Column(String)                    # Present, OD, Absent, Mass Bunk, No Class
    cancel_reason = Column(Text, default="")   # e.g. Holiday (Rakshabandhan), Industrial Visit
    source_file = Column(String, index=True)


class TrainerFeedbackRecord(Base):
    __tablename__ = "trainer_feedback_records"
    id = Column(Integer, primary_key=True, index=True)
    institute = Column(String, index=True)
    submission_timestamp = Column(DateTime, default=datetime.utcnow)
    stack = Column(String, default="General")
    trainer_name = Column(String, default="Assigned Faculty")
    section = Column(String, default="General")
    student_reg_no = Column(String, default="")
    student_name = Column(String, default="Anonymous")
    rating = Column(Float, default=0.0)
    rating_label = Column(String, default="")
    understanding = Column(Text, default="")
    clarity = Column(Text, default="")
    pace = Column(String, default="")
    difficulties = Column(Text, default="")
    suggestions = Column(Text, default="")
    source_file = Column(String, index=True)


class CommunicationConfig(Base):
    __tablename__ = "comms_config"
    id = Column(Integer, primary_key=True, index=True)
    institute = Column(String, unique=True, index=True)
    sender_email = Column(String, default="")
    sender_password = Column(String, default="")
    frequency = Column(String, default="Weekly (Friday 5:00 PM)")
    cc_emails = Column(Text, default="")
    bcc_emails = Column(Text, default="")
    email_template = Column(Text, default="")
    google_sheet_url = Column(Text, default="")


Base.metadata.create_all(bind=engine)
