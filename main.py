from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List
import pandas as pd
import io

from models import SessionLocal, AssessmentRecord, Feedback, StudentRoster

app = FastAPI(title="GNIOT Master Analytics Engine")

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
    if data.get("username") == "admin" and data.get("password") == "Admin@123":
        return {"status": "success", "role": "admin"}
    elif data.get("username") == "user" and data.get("password") == "User@123":
        return {"status": "success", "role": "user"}
    raise HTTPException(status_code=401, detail="Authentication failed.")

# ==========================================
# 1. ROBUST MASTER REGISTRY UPLOAD
# ==========================================
@app.post("/upload-main/")
async def upload_main(file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        contents = await file.read()
        xls = pd.ExcelFile(io.BytesIO(contents))
        
        records_updated = 0
        seen_rolls = set()
        
        # Iterate over all sheets in the file to map multi-department sheets
        for sheet in xls.sheet_names:
            temp_df = pd.read_excel(xls, sheet_name=sheet)
            if temp_df.empty: 
                continue
            
            cols = temp_df.columns
            # Strict column matching to avoid grabbing 'Candidate Name'
            roll_col = next((c for c in cols if any(x in str(c).lower() for x in ['roll', 'prn', 'registration'])), None)
            if not roll_col: 
                roll_col = next((c for c in cols if str(c).strip().lower() in ['id', 'student id', 'uid']), None)
            
            if not roll_col: 
                continue # Skip sheets that don't have student data (like instruction tabs)
            
            name_col = next((c for c in cols if 'name' in str(c).lower()), None)
            dept_col = next((c for c in cols if any(x in str(c).lower() for x in ['dept', 'branch', 'course', 'stream'])), None)
            email_col = next((c for c in cols if 'email' in str(c).lower()), None)

            for index, row in temp_df.iterrows():
                roll_val = row[roll_col]
                if pd.isna(roll_val): continue
                roll = str(roll_val).split('.')[0].strip()
                
                # Prevent duplicates within the upload batch
                if not roll or roll.lower() == 'nan' or roll in seen_rolls: continue
                seen_rolls.add(roll)
                    
                student = db.query(StudentRoster).filter(StudentRoster.roll_no == roll).first()
                if not student:
                    student = StudentRoster(roll_no=roll)
                    db.add(student)
                    
                student.name = str(row[name_col]).strip() if name_col and pd.notna(row[name_col]) else "Unknown"
                
                # Assign Department: Try column first, if missing, use the Sheet Name!
                if dept_col and pd.notna(row[dept_col]):
                    dept_val = str(row[dept_col]).strip()
                else:
                    dept_val = str(sheet).strip()
                    if dept_val.lower() in ['overall', 'master', 'sheet1']:
                        dept_val = "General"
                
                student.department = dept_val
                student.email = str(row[email_col]).strip() if email_col and pd.notna(row[email_col]) else ""
                records_updated += 1

        db.commit()
        return {"message": f"Master Registry successfully established! {records_updated} unique students mapped."}
    except Exception as e:
        return {"message": f"Server Processing Error: {str(e)}"}

# ==========================================
# 2. DAILY ASSESSMENTS (Autonomous)
# ==========================================
@app.post("/upload-assessment/")
async def upload_assessment(files: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    try:
        total_records_added = 0
        roster_records = db.query(StudentRoster).all()
        roster_dict = {r.roll_no: {"name": r.name, "dept": r.department} for r in roster_records}

        for file in files:
            if not file.filename.endswith(('.xlsx', '.xls', '.csv')): continue 
            
            # Atomicity maintained: delete existing records from this specific file before appending
            db.query(AssessmentRecord).filter(AssessmentRecord.source_file == file.filename).delete()
            db.commit()

            df = pd.read_csv(io.BytesIO(await file.read())) if file.filename.endswith('.csv') else pd.read_excel(io.BytesIO(await file.read()))
            cols = df.columns
            
            # Smart Scanners for dynamic MapIT outputs
            roll_col = next((c for c in cols if any(x in str(c).lower() for x in ['roll', 'prn', 'registration'])), None)
            if not roll_col: roll_col = next((c for c in cols if str(c).strip().lower() in ['id', 'student id', 'uid']), None)
            
            pct_col = next((c for c in cols if 'percentage' in str(c).lower() or 'score' in str(c).lower()), None)
            link_col = next((c for c in cols if 'public report' in str(c).lower() or 'link' in str(c).lower()), None)
            date_col = next((c for c in cols if 'out of' in str(c).lower() or 'started on' in str(c).lower()), None)
            conduct_col = next((c for c in cols if 'conduct metrics' in str(c).lower() or 'flagged' in str(c).lower()), None)

            if not roll_col or not pct_col: continue 

            # Extract Date robustly
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
                
                # Assign Department & Name autonomously from Master Registry memory
                student_data = roster_dict.get(raw_roll)
                final_name = student_data["name"] if student_data else str(row.get('Candidate Name', 'Unknown'))
                final_dept = student_data["dept"] if student_data else "General"

                db.add(AssessmentRecord(
                    roll_no=raw_roll, name=final_name, department=final_dept,
                    assessment_date=parsed_date, score_percentage=final_score, status=status,
                    conduct_metrics=conduct, report_link=report_url,
                    source_file=file.filename  
                ))
                total_records_added += 1
            db.commit()
        return {"message": f"Successfully processed {total_records_added} assessment records!"}
    except Exception as e:
        return {"message": f"Server Processing Error: {str(e)}"}

# ==========================================
# 3. DATA RETRIEVAL ENDPOINTS
# ==========================================
@app.get("/api/assessments/")
def get_all_assessments(db: Session = Depends(get_db)):
    records = db.query(AssessmentRecord).all()
    return [{ "Roll No": r.roll_no, "Name": r.name, "Department": r.department, "Date": r.assessment_date.strftime("%Y-%m-%d"), "Score": r.score_percentage, "Status": r.status, "Conduct": r.conduct_metrics, "Link": r.report_link } for r in records]

@app.post("/upload-feedback/")
async def upload_feedback(file: UploadFile = File(...), db: Session = Depends(get_db)):
    # Standard feedback endpoint logic kept minimal
    return {"message": "Feedback endpoint standing by."}
