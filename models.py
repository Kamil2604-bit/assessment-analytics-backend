from sqlalchemy import create_engine, Column, Integer, String, Float, Date
from sqlalchemy.orm import declarative_base, sessionmaker

SQLALCHEMY_DATABASE_URL = "sqlite:///./gniot_dashboard.db"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class Feedback(Base):
    __tablename__ = "trainer_feedback"
    id = Column(Integer, primary_key=True, index=True)
    trainer_name = Column(String, index=True)
    date = Column(Date, index=True)
    subject = Column(String)
    rating = Column(Float)
    difficulties = Column(String, nullable=True)
    remarks = Column(String, nullable=True)

class AssessmentRecord(Base):
    __tablename__ = "assessment_records"
    id = Column(Integer, primary_key=True, index=True)
    roll_no = Column(String, index=True)
    name = Column(String)
    department = Column(String)
    assessment_date = Column(Date, index=True)
    score_percentage = Column(Float, nullable=True)
    status = Column(String)
    
    # NEW: Track the exact filename to prevent duplicates
    source_file = Column(String, index=True) 

Base.metadata.create_all(bind=engine)