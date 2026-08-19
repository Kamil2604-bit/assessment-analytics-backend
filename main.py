from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
from typing import List
import pandas as pd
import io

from models import SessionLocal, AssessmentRecord, StudentRoster, ClientAccount

app = FastAPI(title="Master SaaS Analytics Engine")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# Auto-Create Super Admin on Startup
@app.on_event("startup")
def startup_event():
    db = SessionLocal()
    super_admin = db.query(ClientAccount).filter(ClientAccount.username == "admin").first()
    if not super_admin:
        db.add(ClientAccount(username="admin", password="Admin@123", role="super_admin", institute="ALL", display_name="Super Admin"))
        # Add a default demo client so the interface isn't completely empty initially
        db.add(ClientAccount(username="gniot_admin", password="Gniot@123", role="client_admin", institute="GNIOT", display_name="GNIOT"))
        db.commit()
    db.close()

# ==========================================
# AUTH & CLIENT MANAGEMENT
# ==========================================
@app.post("/api/login")
def login_user(data: dict, db: Session = Depends(get_db)):
    user = db.query(ClientAccount).filter(ClientAccount.username == data.get("username"), ClientAccount.password == data.get("password")).first()
    if user:
        return {"status": "success", "role": user.role, "institute": user.institute, "display": user.display_name}
    raise HTTPException(status_code=401, detail="Authentication failed.")

@app.get("/api/institutes/")
def get_institutes(db: Session = Depends(get_db)):
    """Returns a list of all active institutes in the database."""
    institutes = db.query(ClientAccount.institute).filter(ClientAccount.institute != "ALL").distinct().all()
    return [i[0] for i in institutes]

@app.post("/api/create-client/")
def create_client(data: dict, db: Session = Depends(get_db)):
    """Allows Super Admin to create a new Institute & Login directly from the Dashboard."""
    existing = db.query(ClientAccount).filter(ClientAccount.username == data.get("username")).first()
    if existing: raise HTTPException(status_code=400, detail="Username already exists!")
    
    new_client = ClientAccount(
        username=data.get("username"),
        password=data.get("password"),
        role="client_admin", 
        institute=str(data.get("institute")).upper().strip(),
        display_name=str(data.get("institute")).upper().strip()
    )
    db.add(new_client)
    db.commit()
    return {"message": f"Successfully created workspace for {new_client.institute}!"}

# ==========================================
# DATA ENDPOINTS (Multi-Tenant filtered)
# ==========================================
@app.get("/api/uploaded-files/")
def get_uploaded_files(institute: str, db: Session = Depends(get_db)):
    query = db.query(AssessmentRecord.source_file, func.count(AssessmentRecord.id)).group_by(AssessmentRecord.source_file)
    if institute != "ALL": query = query.filter(AssessmentRecord.institute == institute)
    return [{"filename": r[0], "record_count": r[1]} for r in query.all() if r[0]]

@app.get("/api/assessments/")
def get_all_assessments(institute: str, db: Session = Depends(get_db)):
    query = db.query(AssessmentRecord)
    if institute != "ALL": query = query.filter(AssessmentRecord.institute == institute)
    records = query.all()
    return [{ "Roll No": r.roll_no, "Name": r.name, "Department": r.department, "Date": r.assessment_date.strftime("%Y-%m-%d"), "Score": r.score_percentage, "Status": r.status, "Conduct": r.conduct_metrics, "Link": r.report_link } for r in records]

@app.delete("/api/delete-file/{filename}")
def delete_file_records(filename: str, institute: str, db: Session = Depends(get_db)):
    query = db.query(AssessmentRecord).filter(AssessmentRecord.source_file == filename)
    if institute != "ALL": query = query.filter(AssessmentRecord.institute == institute)
    deleted_count = query.delete()
    db.commit()
    return {"message": f"Successfully deleted '{filename}'."}

@app.delete("/api/reset-database/")
def reset_database(institute: str, db: Session = Depends(get_db)):
    query = db.query(AssessmentRecord)
    if institute != "ALL": query = query.filter(AssessmentRecord.institute == institute)
    deleted_count = query.delete()
    db.commit()
    return {"message": f"Reset Successful! {deleted_count} assessment records erased."}

# ==========================================
# UPLOAD ENGINE
# ==========================================
@app.post("/upload-assessment/")
async def upload_assessment(institute: str = Form(...), files: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    if institute == "ALL": return {"message": "Error: You must select a specific institute."}
    try:
        total_records_added = 0
        roster_records = db.query(StudentRoster).filter(StudentRoster.institute == institute).all()
        roster_dict = {r.roll_no: {"name": r.name, "dept": r.department} for r in roster_records}

        for file in files:
            if not file.filename.endswith(('.xlsx', '.xls', '.csv')): continue 
            db.query(AssessmentRecord).filter(AssessmentRecord.source_file == file.filename, AssessmentRecord.institute == institute).delete()
            db.commit()

            df = pd.read_csv(io.BytesIO(await file.read())) if file.filename.endswith('.csv') else pd.read_excel(io.BytesIO(await file.read()))
            cols = df.columns
            
            roll_col = next((c for c in cols if any(x in str(c).lower() for x in ['roll', 'prn', 'registration'])), None)
            if not roll_col: roll_col = next((c for c in cols if str(c).strip().lower() in ['id', 'student id']), None)
            pct_col = next((c for c in cols if 'percentage' in str(c).lower() or 'score' in str(c).lower()), None)
            link_col = next((c for c in cols if 'public report' in str(c).lower() or 'link' in str(c).lower()), None)
            date_col = next((c for c in cols if 'out of' in str(c).lower() or 'started on' in str(c).lower()), None)
            conduct_col = next((c for c in cols if 'conduct metrics' in str(c).lower() or 'flagged' in str(c).lower()), None)
            name_col_assm = next((c for c in cols if 'name' in str(c).lower()), None)
            dept_col_assm = next((c for c in cols if 'department' in str(c).lower() or 'dept' in str(c).lower()), None)

            if not roll_col or not pct_col: continue 

            parsed_date = datetime.now().date()
            if date_col:
                try:
                    date_str = str(date_col).split('(')[0].strip() if 'out of' in str(date_col).lower() else str(df[date_col].iloc[0])
                    parsed_date = pd.to_datetime(date_str, format="%d/%m/%Y").date()
                except: pass

            for index, row in df.iterrows():
                raw_roll = str(row[roll_col]).split('.')[0].strip() if pd.notna(row[roll_col]) else "Unknown"
                score_val = row[pct_col]
                if pd.isna(score_val): continue
                    
                status = "Present"
                final_score = 0.0
                if isinstance(score_val, str) and 'ABSENT' in score_val.upper(): status = "Absent"
                else: 
                    try: final_score = float(score_val)
                    except: continue 

                conduct = str(row[conduct_col]).strip().upper() if conduct_col and pd.notna(row[conduct_col]) else "GENUINE"
                report_url = str(row[link_col]).strip() if link_col and pd.notna(row[link_col]) else ""
                
                student_data = roster_dict.get(raw_roll)
                final_name = student_data["name"] if student_data and student_data["name"] != "Unknown" else (str(row[name_col_assm]).strip() if name_col_assm and pd.notna(row[name_col_assm]) else "Unknown")
                final_dept = student_data["dept"] if student_data and student_data["dept"] != "General" else (str(row[dept_col_assm]).strip() if dept_col_assm and pd.notna(row[dept_col_assm]) else "General")

                db.add(AssessmentRecord(
                    institute=institute,
                    roll_no=raw_roll, name=final_name, department=final_dept,
                    assessment_date=parsed_date, score_percentage=final_score, status=status,
                    conduct_metrics=conduct, report_link=report_url,
                    source_file=file.filename  
                ))
                total_records_added += 1
            db.commit()
        return {"message": f"Successfully processed {total_records_added} assessment records for {institute}!"}
    except Exception as e:
        return {"message": f"Server Error: {str(e)}"}
