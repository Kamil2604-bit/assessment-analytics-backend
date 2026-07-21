import os
from sqlalchemy import create_engine, Column, Integer, String, Float, Date
from sqlalchemy.orm import declarative_base, sessionmaker

# Fetch cloud database URL or fallback to local SQLite
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./gniot_master.db")

# Fix compatibility for cloud providers that use "postgres://" instead of "postgresql://"
if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Initialize engine (SQLite needs special thread arguments)
if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(SQLALCHEMY_DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ==========================================
# TABLE 1: MASTER STUDENT ROSTER (MAIN SHEET)
# ==========================================
class StudentRoster(Base):
    __tablename__ = "student_roster"
    roll_no = Column(String, primary_key=True, index=True)
    name = Column(String)
    department = Column(String, index=True)
    email = Column(String, nullable=True)

# ==========================================
# TABLE 2: STUDENT ASSESSMENTS
# ==========================================
class AssessmentRecord(Base):
    __tablename__ = "assessment_records"
    id = Column(Integer, primary_key=True, index=True)
    roll_no = Column(String, index=True)
    name = Column(String)
    department = Column(String, index=True)
    assessment_date = Column(Date, index=True)
    score_percentage = Column(Float, nullable=True)
    status = Column(String)
    source_file = Column(String, index=True) 
    
    # Advanced Client Features
    conduct_metrics = Column(String, nullable=True, default="GENUINE")
    report_link = Column(String, nullable=True)

# ==========================================
# TABLE 3: TRAINER FEEDBACK
# ==========================================
class Feedback(Base):
    __tablename__ = "trainer_feedback"
    id = Column(Integer, primary_key=True, index=True)
    trainer_name = Column(String, index=True)
    date = Column(Date, index=True)
    subject = Column(String)
    rating = Column(Float)
    difficulties = Column(String, nullable=True)
    remarks = Column(String, nullable=True)

# Create the tables in the database
Base.metadata.create_all(bind=engine)
