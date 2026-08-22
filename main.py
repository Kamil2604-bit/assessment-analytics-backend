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

from models import SessionLocal, AssessmentRecord, StudentRoster, ClientAccount, CommunicationConfig

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
        db.commit()
    db.close()

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
    query.delete()
    db.commit()
    return {"message": f"Successfully deleted '{filename}'."}

@app.delete("/api/reset-database/")
def reset_database(institute: str, db: Session = Depends(get_db)):
    query = db.query(AssessmentRecord)
    if institute != "ALL": query = query.filter(AssessmentRecord.institute == institute)
    deleted_count = query.delete()
    db.commit()
    return {"message": f"Reset Successful! {deleted_count} assessment records erased."}

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
                    institute=institute, roll_no=raw_roll, name=final_name, department=final_dept,
                    assessment_date=parsed_date, score_percentage=final_score, status=status,
                    conduct_metrics=conduct, report_link=report_url, source_file=file.filename  
                ))
                total_records_added += 1
            db.commit()
        return {"message": f"Successfully processed {total_records_added} assessment records for {institute}!"}
    except Exception as e:
        return {"message": f"Server Error: {str(e)}"}

# ==========================================
# EMAIL & COMMUNICATION ENGINE (100% UI DRIVEN)
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
    db.commit()
    return {"message": "Communication settings successfully saved!"}

@app.get("/api/comms-config/")
def get_comms_config(institute: str, db: Session = Depends(get_db)):
    config = db.query(CommunicationConfig).filter(CommunicationConfig.institute == institute).first()
    if config: 
        return {
            "sender_email": config.sender_email, "sender_password": config.sender_password,
            "frequency": config.frequency, "cc": config.cc_emails, "bcc": config.bcc_emails, "template": config.email_template
        }
    return {
        "sender_email": "", "sender_password": "", "frequency": "Weekly (Friday 5:00 PM)", 
        "cc": "", "bcc": "", "template": "Dear {Student_Name},\n\nYour average score is {Score_Avg}%. Attached is your Scorecard.\n\nRegards,\nAdmin"
    }

@app.post("/api/trigger-emails/")
def trigger_automated_emails(institute: str, db: Session = Depends(get_db)):
    config = db.query(CommunicationConfig).filter(CommunicationConfig.institute == institute).first()
    if not config or not config.sender_email or not config.sender_password: 
        return {"message": "Error: You must configure your Sender Email and App Password in the dashboard first."}
    
    students = db.query(StudentRoster).filter(StudentRoster.institute == institute).all()
    records = db.query(AssessmentRecord).filter(AssessmentRecord.institute == institute).all()
    df = pd.DataFrame([{ "Roll No": r.roll_no, "Name": r.name, "Date": r.assessment_date, "Score": r.score_percentage, "Status": r.status } for r in records])
    
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
        return {"message": f"Email System Error. Verify your App Password and try again. Error: {str(e)}"}
