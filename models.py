import os
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./gniot_master.db")
if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(SQLALCHEMY_DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ==========================================
# 1. CLIENT ACCOUNT TABLE
# ==========================================
class ClientAccount(Base):
    __tablename__ = "client_accounts"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)
    role = Column(String)       # 'super_admin', 'client_admin', or 'client_user'
    institute = Column(String)  # e.g., 'ALL', 'GNIOT', 'SRM', 'JIT'
    display_name = Column(String)

# ==========================================
# 2. STUDENT ROSTER TABLE (With Section Fallback)
# ==========================================
class StudentRoster(Base):
    __tablename__ = "student_roster"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    institute = Column(String, index=True) 
    roll_no = Column(String, index=True)
    name = Column(String)
    department = Column(String, index=True)
    section = Column(String, index=True, nullable=True, default="General")
    email = Column(String, nullable=True)

# ==========================================
# 3. ASSESSMENT RECORDS TABLE (With Section)
# ==========================================
class AssessmentRecord(Base):
    __tablename__ = "assessment_records"
    id = Column(Integer, primary_key=True, index=True)
    institute = Column(String, index=True) 
    roll_no = Column(String, index=True)
    name = Column(String)
    department = Column(String, index=True)
    section = Column(String, index=True, nullable=True, default="General")
    assessment_date = Column(Date, index=True)
    score_percentage = Column(Float, nullable=True)
    status = Column(String)
    source_file = Column(String, index=True) 
    conduct_metrics = Column(String, nullable=True, default="GENUINE")
    report_link = Column(String, nullable=True)

# ==========================================
# 4. TRAINER FEEDBACK TABLE (Unified Google Form Responses)
# ==========================================
class TrainerFeedbackRecord(Base):
    __tablename__ = "trainer_feedback_records"
    id = Column(Integer, primary_key=True, index=True)
    institute = Column(String, index=True)
    submission_timestamp = Column(DateTime, index=True)
    stack = Column(String, index=True)          # e.g., 'Cyber Security', 'DSML', 'Java Full Stack', 'MERN'
    trainer_name = Column(String, index=True)
    section = Column(String, index=True, nullable=True, default="General")
    student_reg_no = Column(String, index=True, nullable=True)
    student_name = Column(String, nullable=True)
    rating = Column(Float, nullable=True)       # Numerical 1 - 5
    rating_label = Column(String, nullable=True)# e.g., 'Excellent', 'Good'
    understanding = Column(String, nullable=True)
    clarity = Column(String, nullable=True)     # 'Yes', 'Somewhat', 'No'
    pace = Column(String, nullable=True)        # 'Just Right', 'Satisfactory', 'Too Slow', 'Too Fast'
    difficulties = Column(Text, nullable=True)
    suggestions = Column(Text, nullable=True)
    source_file = Column(String, index=True)

# ==========================================
# 5. COMMUNICATION & AUTOMATION CONFIG TABLE
# ==========================================
class CommunicationConfig(Base):
    __tablename__ = "comms_config"
    id = Column(Integer, primary_key=True, index=True)
    institute = Column(String, unique=True, index=True)
    sender_email = Column(String)
    sender_password = Column(String)
    frequency = Column(String)
    cc_emails = Column(String)
    bcc_emails = Column(String)
    email_template = Column(String)
    google_sheet_url = Column(String, nullable=True)

Base.metadata.create_all(bind=engine)
