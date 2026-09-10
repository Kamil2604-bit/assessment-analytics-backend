from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
from typing import List
import pandas as pd
import io
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

from models import SessionLocal, AssessmentRecord, StudentRoster, ClientAccount, CommunicationConfig, TrainerFeedbackRecord

app = FastAPI(title="Master SaaS Analytics Engine")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.on_event("startup")
def startup_event():
    db = SessionLocal()
    super_admin = db.query(ClientAccount).filter(ClientAccount.username == "admin").first()
    if not super_admin:
        db.add(ClientAccount(username="admin", password="Admin@123", role="super_admin", institute="ALL", display_name="Super Admin"))
        db.add(ClientAccount(username="gniot_admin", password="Gniot@123", role="client_admin", institute="GNIOT", display_name="GNIOT"))
        db.add(ClientAccount(username="srm_admin", password="Srm@123", role="client_admin", institute="SRM", display_name="SRM"))
        db.commit()
    db.close()

# ==========================================
# AUTH & CLIENT MANAGEMENT
# ==========================================
@app.post("/api/login")
def login_user(data: dict, db: Session = Depends(get_db)):
    user = db.query(ClientAccount).filter(ClientAccount.username == data.get("username"), ClientAccount.password == data.get("password")).first()
    if user: return {"status": "success", "role": user.role, "institute": user.institute, "display": user.display_name}
    raise HTTPException(status_code=401, detail="Authentication failed.")

@app.get("/api/institutes/")
def get_institutes(db: Session = Depends(get_db)):
    institutes = db.query(ClientAccount.institute).filter(ClientAccount.institute != "ALL").distinct().all()
    return [i[0] for i in institutes]

@app.post("/api/create-client/")
def create_client(data: dict, db: Session = Depends(get_db)):
    existing = db.query(ClientAccount).filter(ClientAccount.username == data.get("username")).first()
    if existing: raise HTTPException(status_code=400, detail="Username already exists!")
    new_client = ClientAccount(
        username=data.get("username"), password=data.get("password"), role="client_admin", 
        institute=str(data.get("institute")).upper().strip(), display_name=str(data.get("institute")).upper().strip()
    )
    db.add(new_client)
    db.commit()
    return {"message": f"Successfully created workspace for {new_client.institute}!"}

# ==========================================
# ASSESSMENT DATA PIPELINE
# ==========================================
@app.get("/api/uploaded-files/")
def get_uploaded_files(institute: str, db: Session = Depends(get_db)):
    assm_q = db.query(AssessmentRecord.source_file, func.count(AssessmentRecord.id)).group_by(AssessmentRecord.source_file)
    fb_q = db.query(TrainerFeedbackRecord.source_file, func.count(TrainerFeedbackRecord.id)).group_by(TrainerFeedbackRecord.source_file)
    if institute != "ALL":
        assm_q = assm_q.filter(AssessmentRecord.institute == institute)
        fb_q = fb_q.filter(TrainerFeedbackRecord.institute == institute)
    
    files = [{"filename": r[0], "record_count": r[1], "type": "Assessment"} for r in assm_q.all() if r[0]]
    files.extend([{"filename": r[0], "record_count": r[1], "type": "Feedback"} for r in fb_q.all() if r[0]])
    return files

@app.get("/api/assessments/")
def get_all_assessments(institute: str, db: Session = Depends(get_db)):
    query = db.query(AssessmentRecord)
    if institute != "ALL": query = query.filter(AssessmentRecord.institute == institute)
    records = query.all()
    return [{ 
        "Roll No": r.roll_no, "Name": r.name, "Department": r.department, "Section": r.section or "General",
        "Date": r.assessment_date.strftime("%Y-%m-%d"), "Score": r.score_percentage, 
        "Status": r.status, "Conduct": r.conduct_metrics, "Link": r.report_link 
    } for r in records]

@app.delete("/api/delete-file/{filename}")
def delete_file_records(filename: str, institute: str, db: Session = Depends(get_db)):
    assm_q = db.query(AssessmentRecord).filter(AssessmentRecord.source_file == filename)
    fb_q = db.query(TrainerFeedbackRecord).filter(TrainerFeedbackRecord.source_file == filename)
    if institute != "ALL":
        assm_q = assm_q.filter(AssessmentRecord.institute == institute)
        fb_q = fb_q.filter(TrainerFeedbackRecord.institute == institute)
    d1 = assm_q.delete()
    d2 = fb_q.delete()
    db.commit()
    return {"message": f"Successfully deleted '{filename}' ({d1 + d2} records removed)."}

@app.delete("/api/reset-database/")
def reset_database(institute: str, db: Session = Depends(get_db)):
    q1 = db.query(AssessmentRecord)
    q2 = db.query(TrainerFeedbackRecord)
    q3 = db.query(StudentRoster)
    if institute != "ALL":
        q1 = q1.filter(AssessmentRecord.institute == institute)
        q2 = q2.filter(TrainerFeedbackRecord.institute == institute)
        q3 = q3.filter(StudentRoster.institute == institute)
    d1 = q1.delete()
    d2 = q2.delete()
    d3 = q3.delete()
    db.commit()
    return {"message": f"Reset Complete! Cleared {d1} assessments, {d2} feedback records, and {d3} roster entries."}

@app.post("/upload-assessment/")
async def upload_assessment(institute: str = Form(...), files: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    if institute == "ALL": return {"message": "Error: You must select a specific institute."}
    try:
        total_records_added = 0
        for file in files:
            if not file.filename.endswith(('.xlsx', '.xls', '.csv')): continue 
            db.query(AssessmentRecord).filter(AssessmentRecord.source_file == file.filename, AssessmentRecord.institute == institute).delete()
            db.commit()

            df = pd.read_csv(io.BytesIO(await file.read())) if file.filename.endswith('.csv') else pd.read_excel(io.BytesIO(await file.read()))
            cols = df.columns
            
            # UPDATED MAPPINGS FOR SRM FORMAT
            roll_col = next((c for c in cols if any(x in str(c).lower() for x in ['roll', 'prn', 'registration', 'register'])), None)
            if not roll_col: roll_col = next((c for c in cols if str(c).strip().lower() in ['id', 'student id']), None)
            pct_col = next((c for c in cols if 'percentage' in str(c).lower() or 'score' in str(c).lower()), None)
            link_col = next((c for c in cols if 'public report' in str(c).lower() or 'link' in str(c).lower()), None)
            date_col = next((c for c in cols if 'out of' in str(c).lower() or 'started on' in str(c).lower()), None)
            conduct_col = next((c for c in cols if 'conduct metrics' in str(c).lower() or 'flagged' in str(c).lower()), None)
            name_col = next((c for c in cols if 'name' in str(c).lower()), None)
            email_col = next((c for c in cols if 'email' in str(c).lower()), None)
            
            # Detect standalone OR combined branch/section columns
            dept_col = next((c for c in cols if str(c).lower() in ['department', 'dept', 'branch']), None)
            sec_col = next((c for c in cols if 'section' in str(c).lower() and 'branch' not in str(c).lower()), None)
            combined_branch_sec_col = next((c for c in cols if 'branch' in str(c).lower() and 'section' in str(c).lower()), None)

            if not roll_col or not pct_col: continue 

            parsed_date = datetime.now().date()
            if date_col:
                try:
                    date_str = str(date_col).split('(')[0].strip() if 'out of' in str(date_col).lower() else str(df[date_col].iloc[0])
                    parsed_date = pd.to_datetime(date_str, format="%d/%m/%Y").date()
                except: pass

            for _, row in df.iterrows():
                # Strip trailing whitespace from IDs and Names
                raw_roll = str(row[roll_col]).replace('\xa0', '').strip() if pd.notna(row[roll_col]) else "Unknown"
                if raw_roll == "Unknown" or raw_roll == "nan": continue
                
                score_val = str(row[pct_col]).replace('\xa0', '').strip() if pd.notna(row[pct_col]) else None
                if not score_val or score_val == "nan": continue
                    
                status = "Present"
                final_score = 0.0
                if 'ABSENT' in score_val.upper(): status = "Absent"
                else: 
                    try: final_score = float(score_val)
                    except: continue 

                conduct = str(row[conduct_col]).strip().upper() if conduct_col and pd.notna(row[conduct_col]) else "GENUINE"
                report_url = str(row[link_col]).strip() if link_col and pd.notna(row[link_col]) else ""
                final_name = str(row[name_col]).replace('\xa0', '').strip() if name_col and pd.notna(row[name_col]) else "Unknown"
                final_email = str(row[email_col]).replace('\xa0', '').strip() if email_col and pd.notna(row[email_col]) else ""

                # Handle combined 'Branch and Section' column (e.g., 'CORE - A')
                final_dept = "General"
                final_sec = "General"
                if combined_branch_sec_col and pd.notna(row[combined_branch_sec_col]):
                    parts = str(row[combined_branch_sec_col]).split('-')
                    final_dept = parts[0].strip()
                    if len(parts) > 1: final_sec = parts[1].strip()
                else:
                    if dept_col and pd.notna(row[dept_col]): final_dept = str(row[dept_col]).strip()
                    if sec_col and pd.notna(row[sec_col]): final_sec = str(row[sec_col]).strip()

                student = db.query(StudentRoster).filter(StudentRoster.roll_no == raw_roll, StudentRoster.institute == institute).first()
                if not student:
                    student = StudentRoster(institute=institute, roll_no=raw_roll, name=final_name, department=final_dept, section=final_sec, email=final_email)
                    db.add(student)
                else:
                    if final_name != "Unknown": student.name = final_name
                    if final_dept != "General": student.department = final_dept
                    if final_sec != "General": student.section = final_sec
                    if final_email and "@" in final_email: student.email = final_email
                
                db.add(AssessmentRecord(
                    institute=institute, roll_no=raw_roll, name=student.name, department=student.department,
                    section=student.section, assessment_date=parsed_date, score_percentage=final_score, status=status,
                    conduct_metrics=conduct, report_link=report_url, source_file=file.filename  
                ))
                total_records_added += 1
            db.commit()
        return {"message": f"Successfully processed {total_records_added} assessment records for {institute}!"}
    except Exception as e:
        return {"message": f"Server Error: {str(e)}"}

# ==========================================
# TRAINER FEEDBACK DATA PIPELINE
# ==========================================
@app.post("/upload-feedback/")
async def upload_feedback(institute: str = Form(...), files: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    if institute == "ALL": return {"message": "Error: Select a specific institute for feedback upload."}
    try:
        total_feedback_added = 0
        for file in files:
            if not file.filename.endswith(('.xlsx', '.xls', '.csv')): continue
            db.query(TrainerFeedbackRecord).filter(TrainerFeedbackRecord.source_file == file.filename, TrainerFeedbackRecord.institute == institute).delete()
            db.commit()

            df = pd.read_csv(io.BytesIO(await file.read())) if file.filename.endswith('.csv') else pd.read_excel(io.BytesIO(await file.read()))
            cols = df.columns
            
            ts_col = next((c for c in cols if 'timestamp' in str(c).lower()), None)
            name_col = next((c for c in cols if str(c).strip().lower() in ['name', 'participant name', 'student name']), None)
            reg_col = next((c for c in cols if any(x in str(c).lower() for x in ['registration', 'roll', 'prn', 'reg'])), None)
            sec_col = next((c for c in cols if 'section' in str(c).lower() or 'sec' in str(c).lower()), None)
            trainer_col = next((c for c in cols if any(x in str(c).lower() for x in ['trainer name', 'trainer', 'instructor', 'faculty'])), None)
            rating_col = next((c for c in cols if any(x in str(c).lower() for x in ['rate today', 'rating', 'score (1-5)'])), None)
            und_col = next((c for c in cols if 'understand' in str(c).lower()), None)
            clarity_col = next((c for c in cols if 'explain' in str(c).lower() or 'clarity' in str(c).lower() or 'recommend' in str(c).lower()), None)
            pace_col = next((c for c in cols if 'pace' in str(c).lower()), None)
            diff_col = next((c for c in cols if any(x in str(c).lower() for x in ['issues', 'doubts', 'difficulties', 'comments'])), None)
            sugg_col = next((c for c in cols if 'suggestion' in str(c).lower() or 'improvement' in str(c).lower()), None)

            fn_lower = file.filename.lower()
            inferred_stack = "General"
            if "cyber" in fn_lower: inferred_stack = "Cyber Security"
            elif "data science" in fn_lower or "dsml" in fn_lower: inferred_stack = "Data Science & ML"
            elif "java" in fn_lower: inferred_stack = "Java Full Stack"
            elif "mern" in fn_lower: inferred_stack = "MERN Stack"

            for _, row in df.iterrows():
                parsed_ts = datetime.now()
                if ts_col and pd.notna(row[ts_col]):
                    try: parsed_ts = pd.to_datetime(str(row[ts_col]))
                    except: pass
                
                num_rating = None
                rating_lbl = ""
                if rating_col and pd.notna(row[rating_col]):
                    val = row[rating_col]
                    try:
                        num_rating = float(val)
                    except:
                        rating_lbl = str(val).strip()
                        if "excel" in rating_lbl.lower(): num_rating = 5.0
                        elif "good" in rating_lbl.lower(): num_rating = 4.0
                        elif "avg" in rating_lbl.lower() or "average" in rating_lbl.lower(): num_rating = 3.0
                        elif "poor" in rating_lbl.lower(): num_rating = 2.0
                        else: num_rating = 3.0

                trainer = str(row[trainer_col]).strip() if trainer_col and pd.notna(row[trainer_col]) else "Assigned Faculty"
                sec = str(row[sec_col]).strip() if sec_col and pd.notna(row[sec_col]) else "General"
                st_name = str(row[name_col]).strip() if name_col and pd.notna(row[name_col]) else "Anonymous"
                st_reg = str(row[reg_col]).strip() if reg_col and pd.notna(row[reg_col]) else ""
                und = str(row[und_col]).strip() if und_col and pd.notna(row[und_col]) else ""
                clarity = str(row[clarity_col]).strip() if clarity_col and pd.notna(row[clarity_col]) else ""
                pace = str(row[pace_col]).strip() if pace_col and pd.notna(row[pace_col]) else ""
                diff = str(row[diff_col]).strip() if diff_col and pd.notna(row[diff_col]) and str(row[diff_col]).lower() not in ['no', 'none', 'nil', 'nan', 'na', '.'] else ""
                sugg = str(row[sugg_col]).strip() if sugg_col and pd.notna(row[sugg_col]) and str(row[sugg_col]).lower() not in ['no', 'none', 'nil', 'nan', 'na', '.'] else ""

                db.add(TrainerFeedbackRecord(
                    institute=institute,
                    submission_timestamp=parsed_ts,
                    stack=inferred_stack,
                    trainer_name=trainer,
                    section=sec,
                    student_reg_no=st_reg,
                    student_name=st_name,
                    rating=num_rating,
                    rating_label=rating_lbl,
                    understanding=und,
                    clarity=clarity,
                    pace=pace,
                    difficulties=diff,
                    suggestions=sugg,
                    source_file=file.filename
                ))
                total_feedback_added += 1
            db.commit()
        return {"message": f"Successfully ingested {total_feedback_added} trainer feedback records for {institute}!"}
    except Exception as e:
        return {"message": f"Server Error: {str(e)}"}

@app.get("/api/feedbacks/")
def get_feedbacks(institute: str, db: Session = Depends(get_db)):
    query = db.query(TrainerFeedbackRecord)
    if institute != "ALL": query = query.filter(TrainerFeedbackRecord.institute == institute)
    records = query.all()
    return [{
        "Date": r.submission_timestamp.strftime("%Y-%m-%d"),
        "Time": r.submission_timestamp.strftime("%H:%M:%S"),
        "Stack": r.stack,
        "Trainer": r.trainer_name,
        "Section": r.section or "General",
        "Student": r.student_name or "Anonymous",
        "RegNo": r.student_reg_no or "-",
        "Rating": r.rating or 0,
        "Understanding": r.understanding or "-",
        "Clarity": r.clarity or "-",
        "Pace": r.pace or "-",
        "Difficulties": r.difficulties or "-",
        "Suggestions": r.suggestions or "-"
    } for r in records]

# ==========================================
# EMAIL & CONFIGURATION GATEWAY
# ==========================================
@app.post("/api/comms-config/")
def save_comms_config(data: dict, db: Session = Depends(get_db)):
    institute = data.get("institute")
    config = db.query(CommunicationConfig).filter(CommunicationConfig.institute == institute).first()
    if not config:
        config = CommunicationConfig(institute=institute)
        db.add(config)
    config.sender_email = data.get("sender_email", "")
    config.sender_password = data.get("sender_password", "")
    config.frequency = data.get("frequency", "")
    config.cc_emails = data.get("cc", "")
    config.bcc_emails = data.get("bcc", "")
    config.email_template = data.get("template", "")
    config.google_sheet_url = data.get("google_sheet_url", "")
    db.commit()
    return {"message": "Communication & live sync configurations successfully locked in!"}

@app.get("/api/comms-config/")
def get_comms_config(institute: str, db: Session = Depends(get_db)):
    config = db.query(CommunicationConfig).filter(CommunicationConfig.institute == institute).first()
    if config: 
        return {
            "sender_email": config.sender_email, "sender_password": config.sender_password,
            "frequency": config.frequency, "cc": config.cc_emails, "bcc": config.bcc_emails, 
            "template": config.email_template, "google_sheet_url": config.google_sheet_url or ""
        }
    return {
        "sender_email": "", "sender_password": "", "frequency": "Weekly (Friday 5:00 PM)", 
        "cc": "", "bcc": "", "template": "Dear {Student_Name},\n\nYour average score is {Score_Avg}%. Attached is your Scorecard.\n\nRegards,\nAdmin",
        "google_sheet_url": ""
    }

@app.post("/api/trigger-emails/")
def trigger_automated_emails(institute: str, target_date: str = None, db: Session = Depends(get_db)):
    config = db.query(CommunicationConfig).filter(CommunicationConfig.institute == institute).first()
    if not config or not config.sender_email or not config.sender_password: 
        return {"message": "Error: Sender Email and App Password must be configured in settings first."}
    
    students = db.query(StudentRoster).filter(StudentRoster.institute == institute).all()
    query = db.query(AssessmentRecord).filter(AssessmentRecord.institute == institute)
    if target_date:
        try:
            p_date = datetime.strptime(target_date, "%Y-%m-%d").date()
            query = query.filter(AssessmentRecord.assessment_date == p_date)
        except: pass
        
    records = query.all()
    df = pd.DataFrame([{ "Roll No": r.roll_no, "Name": r.name, "Department": r.department, "Section": r.section, "Date": r.assessment_date, "Score": r.score_percentage, "Status": r.status, "Conduct": r.conduct_metrics, "Report Link": r.report_link } for r in records])
    
    emails_sent = 0
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(config.sender_email, config.sender_password)
        
        for student in students:
            if not student.email or "@" not in student.email: continue
            student_df = df[df["Roll No"] == student.roll_no]
            if student_df.empty: continue
            
            avg_score = student_df["Score"].mean() if not student_df["Score"].isnull().all() else 0
            custom_message = config.email_template.replace("{Student_Name}", student.name).replace("{Score_Avg}", f"{avg_score:.1f}")
            
            msg = MIMEMultipart()
            msg['From'] = config.sender_email
            msg['To'] = student.email
            msg['Cc'] = config.cc_emails
            msg['Subject'] = f"[{institute}] Automated Performance Scorecard"
            msg.attach(MIMEText(custom_message, 'plain'))
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                student_df.to_excel(writer, index=False, sheet_name="Scorecard")
            attachment = MIMEApplication(output.getvalue(), Name=f"{student.name}_Scorecard.xlsx")
            attachment['Content-Disposition'] = f'attachment; filename="{student.name}_Scorecard.xlsx"'
            msg.attach(attachment)
            
            recipients = [student.email]
            if config.cc_emails: recipients.extend([e.strip() for e in config.cc_emails.split(",") if e.strip()])
            if config.bcc_emails: recipients.extend([e.strip() for e in config.bcc_emails.split(",") if e.strip()])
            
            server.sendmail(config.sender_email, recipients, msg.as_string())
            emails_sent += 1
            
        server.quit()
        return {"message": f"Success! Dispatched {emails_sent} automated scorecards using {config.sender_email}."}
    except Exception as e:
        return {"message": f"Email System Error: {str(e)}"}
