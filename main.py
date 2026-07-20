from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List
import pandas as pd
import io

from models import SessionLocal, Feedback, AssessmentRecord

app = FastAPI(title="GNIOT Analytics API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/api/login")
def login_user(data: dict):
    username = data.get("username")
    password = data.get("password")
    
    if username == "kamil_admin" and password == "Admin@987":
        return {"status": "success", "role": "admin", "redirect": "dashboard"}
    elif username == "gniot_user" and password == "User@432":
        return {"status": "success", "role": "user", "redirect": "dashboard"}
    else:
        raise HTTPException(status_code=401, detail="Invalid Username or Password")

@app.post("/upload-feedback/")
async def upload_feedback(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Only Excel files are allowed")

    contents = await file.read()
    df = pd.read_excel(io.BytesIO(contents), sheet_name=0)

    column_sets = [
        {"trainer": "Trainer's Name", "date": "Timestamp", "rating": "Rate your understanding of today’s content  ", "diff": "What difficulties did you face today?  ", "rem": "Any Remarks or suggestions?", "subject": "Select your choice"},
        {"trainer": "Trainer's Name 2", "date": "Timestamp", "rating": "Rate your understanding of today’s content   2", "diff": "What difficulties did you face today?   2", "rem": "Any Remarks or suggestions? 2", "subject": "Select your choice"},
        {"trainer": "Trainer's Name 3", "date": "Timestamp", "rating": "Rate your understanding of today’s content   3", "diff": "What difficulties did you face today?   3", "rem": "Any Remarks or suggestions? 3", "subject": "Select your choice"},
        {"trainer": "Trainer's Name 4", "date": "Timestamp", "rating": "Rate your understanding of today’s content   4", "diff": "What difficulties did you face today?   4", "rem": "Any Remarks or suggestions? 4", "subject": "Select your choice"}
    ]

    records_added = 0
    for index, row in df.iterrows():
        for col_set in column_sets:
            if pd.notna(row.get(col_set["trainer"])):
                raw_date = row.get(col_set["date"])
                parsed_date = datetime.now().date()
                if pd.notna(raw_date):
                    parsed_date = pd.to_datetime(raw_date).date()

                feedback = Feedback(
                    trainer_name=str(row[col_set["trainer"]]),
                    date=parsed_date,
                    subject=str(row.get(col_set["subject"], "Unknown")),
                    rating=float(row.get(col_set["rating"], 0)),
                    difficulties=str(row.get(col_set["diff"], "")),
                    remarks=str(row.get(col_set["rem"], ""))
                )
                db.add(feedback)
                records_added += 1

    db.commit()
    return {"message": f"Successfully processed and added {records_added} feedback records!"}

@app.get("/api/dashboard-data/")
def get_dashboard_data(db: Session = Depends(get_db)):
    records = db.query(Feedback).all()
    return [{ "Trainer": r.trainer_name, "Date": r.date.strftime("%Y-%m-%d"), "Rating": r.rating, "Subject": r.subject, "Difficulties": r.difficulties, "Remarks": r.remarks } for r in records]

@app.post("/upload-assessment/")
async def upload_assessment(files: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    total_records_added = 0
    processed_files = []

    for file in files:
        if not file.filename.endswith(('.xlsx', '.xls', '.csv')):
            continue 

        db.query(AssessmentRecord).filter(AssessmentRecord.source_file == file.filename).delete()
        db.commit()

        contents = await file.read()
        df = pd.read_csv(io.BytesIO(contents)) if file.filename.endswith('.csv') else pd.read_excel(io.BytesIO(contents), sheet_name=0)

        cols = df.columns
        name_col = next((c for c in cols if 'name' in str(c).lower()), None)
        roll_col = next((c for c in cols if 'roll' in str(c).lower()), None)
        dept_col = next((c for c in cols if 'department' in str(c).lower()), None)
        pct_col = next((c for c in cols if 'percentage' in str(c).lower()), None)
        out_of_col = next((c for c in cols if 'out of' in str(c).lower()), None)
        
        # --- NEW COLUMN DETECTORS ---
        link_col = next((c for c in cols if 'public report' in str(c).lower()), None)
        conduct_col = next((c for c in cols if 'conduct metrics' in str(c).lower()), None)

        if not all([name_col, roll_col, pct_col]):
            continue 

        parsed_date = datetime.now().date()
        if out_of_col:
            try:
                date_str = str(out_of_col).split('(')[0].strip()
                parsed_date = pd.to_datetime(date_str, format="%d/%m/%Y").date()
            except: pass

        for index, row in df.iterrows():
            roll_no = str(row[roll_col]).split('.')[0] if pd.notna(row[roll_col]) else "Unknown"
            name = str(row[name_col]) if pd.notna(row[name_col]) else "Unknown"
            dept = str(row[dept_col]) if pd.notna(row[dept_col]) else "Unknown"

            score_val = row[pct_col]
            status = "Present"
            final_score = 0.0
            
            if isinstance(score_val, str) and score_val.strip().upper() == 'ABSENT':
                status = "Absent"
            elif pd.notna(score_val):
                try: final_score = float(score_val)
                except ValueError: continue 
            else: continue 

            # Parse Conduct & Link
            conduct = str(row[conduct_col]).strip().upper() if conduct_col and pd.notna(row[conduct_col]) else "GENUINE"
            report_url = str(row[link_col]).strip() if link_col and pd.notna(row[link_col]) else ""

            new_record = AssessmentRecord(
                roll_no=roll_no, name=name, department=dept,
                assessment_date=parsed_date, score_percentage=final_score, status=status,
                conduct_metrics=conduct, report_link=report_url,
                source_file=file.filename  
            )
            db.add(new_record)
            total_records_added += 1
                
        processed_files.append(file.filename)
        db.commit()

    return {"message": f"Successfully processed {len(processed_files)} files. Synced {total_records_added} records to the database!"}

@app.get("/api/assessments/")
def get_all_assessments(db: Session = Depends(get_db)):
    records = db.query(AssessmentRecord).all()
    return [
        {
            "Roll No": r.roll_no,
            "Name": r.name,
            "Department": r.department,
            "Date": r.assessment_date.strftime("%Y-%m-%d"),
            "Score": r.score_percentage,
            "Status": r.status,
            "Conduct": r.conduct_metrics,
            "Link": r.report_link
        } for r in records
    ]

@app.get("/api/student-history/{roll_no}")
def get_student_history(roll_no: str, db: Session = Depends(get_db)):
    records = db.query(AssessmentRecord).filter(AssessmentRecord.roll_no == roll_no).order_by(AssessmentRecord.assessment_date).all()
    if not records: raise HTTPException(status_code=404, detail="Student not found")
    return [{ "Date": r.assessment_date.strftime("%Y-%m-%d"), "Score": r.score_percentage, "Status": r.status, "Conduct": r.conduct_metrics, "Link": r.report_link } for r in records]
