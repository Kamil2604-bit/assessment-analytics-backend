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

class ClientAccount(Base):
    __tablename__ = "client_accounts"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)
    role = Column(String)       
    institute = Column(String)  
    display_name = Column(String)

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

Base.metadata.create_all(bind=engine)
