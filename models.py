import os
from sqlalchemy import create_engine, Column, Integer, String, Float, Date
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
# NEW: DYNAMIC CLIENT ACCOUNT TABLE
# ==========================================
class ClientAccount(Base):
    __tablename__ = "client_accounts"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)
    role = Column(String)       # 'super_admin', 'client_admin', or 'client_user'
    institute = Column(String)  # e.g., 'ALL', 'GNIOT', 'SRM'
    display_name = Column(String)

# ==========================================
# DATA TABLES
# ==========================================
class StudentRoster(Base):
    __tablename__ = "student_roster"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    institute = Column(String, index=True) 
    roll_no = Column(String, index=True)
    name = Column(String)
    department = Column(String, index=True)
    email = Column(String, nullable=True)

class AssessmentRecord(Base):
    __tablename__ = "assessment_records"
    id = Column(Integer, primary_key=True, index=True)
    institute = Column(String, index=True) 
    roll_no = Column(String, index=True)
    name = Column(String)
    department = Column(String, index=True)
    assessment_date = Column(Date, index=True)
    score_percentage = Column(Float, nullable=True)
    status = Column(String)
    source_file = Column(String, index=True) 
    conduct_metrics = Column(String, nullable=True, default="GENUINE")
    report_link = Column(String, nullable=True)

Base.metadata.create_all(bind=engine)
