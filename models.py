import os
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./gniot_master.db")
if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    pool_pre_ping=True, 
    pool_recycle=300,
    connect_args={"check_same_thread": False} if "sqlite" in SQLALCHEMY_DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class ClientAccount(Base):
    __tablename__ = "client_accounts"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)
    role = Column(String)       # 'super_admin', 'client_admin'
    institute = Column(String)  # Partition Key (SRM, GNIOT, etc)
    display_name = Column(String)

class StudentRoster(Base):
    __tablename__ = "student_roster"
    id = Column(Integer, primary_key=True, index=True)
    institute = Column(String, index=True) 
    roll_no = Column(String, index=True)
    name = Column(String)
    department = Column(String, index=True)
    section = Column(String, index=True, default="General")
    email = Column(String)

class AssessmentRecord(Base):
    __tablename__ = "assessment_records"
    id = Column(Integer, primary_key=True, index=True)
    institute = Column(String, index=True) 
    roll_no = Column(String, index=True)
    name = Column(String)
    department = Column(String, index=True)
    section = Column(String, index=True, default="General")
    assessment_date = Column(Date, index=True)
    score_percentage = Column(Float)
    status = Column(String)
    source_file = Column(String, index=True) 
    conduct_metrics = Column(String, default="GENUINE")
    report_link = Column(String)

class TrainerFeedbackRecord(Base):
    __tablename__ = "trainer_feedback_records"
    id = Column(Integer, primary_key=True, index=True)
    institute = Column(String, index=True)
    submission_timestamp = Column(DateTime, index=True)
    stack = Column(String, index=True)
    trainer_name = Column(String, index=True)
    section = Column(String, index=True, default="General")
    student_reg_no = Column(String, index=True)
    student_name = Column(String)
    rating = Column(Float)
    rating_label = Column(String)
    understanding = Column(String)
    clarity = Column(String)
    pace = Column(String)
    difficulties = Column(Text)
    suggestions = Column(Text)
    source_file = Column(String, index=True)

class CommunicationConfig(Base):
    __tablename__ = "comms_config"
    id = Column(Integer, primary_key=True, index=True)
    institute = Column(String, unique=True, index=True)
    sender_email = Column(String)
    sender_password = Column(String)
    frequency = Column(String)
    cc_emails = Column(String)
    bcc_emails = Column(String)
    email_template = Column(Text)
    google_sheet_url = Column(Text)

Base.metadata.create_all(bind=engine)
