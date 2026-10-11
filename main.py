from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
from typing import List
import pandas as pd
import io
import math
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

from models import (
    SessionLocal,
    AssessmentRecord,
    AttendanceRecord,
    StudentRoster,
    ClientAccount,
    CommunicationConfig,
    TrainerFeedbackRecord,
)

app = FastAPI(title="BENCHMARK. Academic Intelligence & Performance Engine")

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


@app.on_event("startup")
def startup_event():
    db = SessionLocal()
    try:
        super_admin = db.query(ClientAccount).filter(ClientAccount.username == "admin").first()
        if not super_admin:
            db.add(ClientAccount(username="admin", password="Admin@123", role="super_admin", institute="ALL", display_name="Super Admin"))
            db.add(ClientAccount(username="gniot_admin", password="Gniot@123", role="client_admin", institute="GNIOT", display_name="GNIOT"))
            db.add(ClientAccount(username="srm_admin", password="Srm@123", role="client_admin", institute="SRM", display_name="SRM"))

        if not db.query(ClientAccount).filter(ClientAccount.username == "srm_guest").first():
            db.add(ClientAccount(username="srm_guest", password="Srm@View123", role="client_user", institute="SRM", display_name="SRM"))
        if not db.query(ClientAccount).filter(ClientAccount.username == "gniot_guest").first():
            db.add(ClientAccount(username="gniot_guest", password="Gniot@View123", role="client_user", institute="GNIOT", display_name="GNIOT"))

        db.commit()
    finally:
        db.close()


# ==========================================
# AUTH & CLIENT CREDENTIALS MANAGER
# ==========================================
@app.post("/api/login")
def login_user(data: dict, db: Session = Depends(get_db)):
    user = db.query(ClientAccount).filter(
        ClientAccount.username == data.get("username"),
        ClientAccount.password == data.get("password")
    ).first()
    if user:
        return {
            "status": "success",
            "role": user.role,
            "institute": user.institute,
            "display": user.display_name,
        }
    raise HTTPException(status_code=401, detail="Authentication failed.")


@app.get("/api/institutes/")
def get_institutes(db: Session = Depends(get_db)):
    institutes = db.query(ClientAccount.institute).filter(ClientAccount.institute != "ALL").distinct().all()
    return [i[0] for i in institutes]


@app.post("/api/create-client/")
def create_or_update_client(data: dict, db: Session = Depends(get_db)):
    uname = str(data.get("username", "")).strip()
    pwd = str(data.get("password", "")).strip()
    inst_clean = str(data.get("institute", "")).upper().strip()
    assigned_role = data.get("role", "client_admin")

    if not uname or not pwd or not inst_clean:
        raise HTTPException(status_code=400, detail="All fields are required.")

    existing = db.query(ClientAccount).filter(ClientAccount.username == uname).first()
    role_label = "View-Only Guest POC" if assigned_role == "client_user" else "Client Admin"

    if existing:
        existing.password = pwd
        existing.institute = inst_clean
        existing.display_name = inst_clean
        existing.role = assigned_role
        db.commit()
        return {"message": f"Updated credentials! '{uname}' ({inst_clean}) now has the new password and role ({role_label})."}

    new_client = ClientAccount(
        username=uname,
        password=pwd,
        role=assigned_role,
        institute=inst_clean,
        display_name=inst_clean,
    )
    db.add(new_client)
    db.commit()
    return {"message": f"Successfully created {role_label} account '{uname}' for {inst_clean}!"}


@app.get("/api/accounts/")
def get_all_accounts(db: Session = Depends(get_db)):
    accounts = db.query(ClientAccount).filter(ClientAccount.username != "admin").all()
    return [{
        "username": a.username,
        "password": a.password,
        "institute": a.institute,
        "role": "Guest POC (View Only)" if a.role == "client_user" else "Client Admin"
    } for a in accounts]


@app.delete("/api/accounts/{username}")
def delete_account(username: str, db: Session = Depends(get_db)):
    if username == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete Super Admin.")
    db.query(ClientAccount).filter(ClientAccount.username == username).delete()
    db.commit()
    return {"message": f"Account '{username}' has been revoked and deleted."}


# ==========================================
# FILE MANAGEMENT GATEWAY
# ==========================================
@app.get("/api/uploaded-files/")
def get_uploaded_files(institute: str, db: Session = Depends(get_db)):
    assm_q = db.query(AssessmentRecord.source_file, func.count(AssessmentRecord.id))
    fb_q = db.query(TrainerFeedbackRecord.source_file, func.count(TrainerFeedbackRecord.id))
    att_q = db.query(AttendanceRecord.source_file, func.count(AttendanceRecord.id))

    if institute != "ALL":
        assm_q = assm_q.filter(AssessmentRecord.institute == institute)
        fb_q = fb_q.filter(TrainerFeedbackRecord.institute == institute)
        att_q = att_q.filter(AttendanceRecord.institute == institute)

    assm_q = assm_q.group_by(AssessmentRecord.source_file)
    fb_q = fb_q.group_by(TrainerFeedbackRecord.source_file)
    att_q = att_q.group_by(AttendanceRecord.source_file)

    files = [{"filename": str(r[0]), "record_count": r[1], "type": "Assessment"} for r in assm_q.all() if r[0]]
    files.extend([{"filename": str(r[0]), "record_count": r[1], "type": "Feedback"} for r in fb_q.all() if r[0]])
    files.extend([{"filename": str(r[0]), "record_count": r[1], "type": "Attendance"} for r in att_q.all() if r[0]])
    return files


@app.delete("/api/delete-file/{filename}")
def delete_file_records(filename: str, institute: str, db: Session = Depends(get_db)):
    assm_q = db.query(AssessmentRecord).filter(AssessmentRecord.source_file == filename)
    fb_q = db.query(TrainerFeedbackRecord).filter(TrainerFeedbackRecord.source_file == filename)
    att_q = db.query(AttendanceRecord).filter(AttendanceRecord.source_file == filename)
    if institute != "ALL":
        assm_q = assm_q.filter(AssessmentRecord.institute == institute)
        fb_q = fb_q.filter(TrainerFeedbackRecord.institute == institute)
        att_q = att_q.filter(AttendanceRecord.institute == institute)
    d1 = assm_q.delete()
    d2 = fb_q.delete()
    d3 = att_q.delete()
    db.commit()
    return {"message": f"Successfully deleted '{filename}' ({d1 + d2 + d3} records removed)."}


@app.delete("/api/reset-database/")
def reset_database(institute: str, db: Session = Depends(get_db)):
    q1 = db.query(AssessmentRecord)
    q2 = db.query(TrainerFeedbackRecord)
    q3 = db.query(StudentRoster)
    q4 = db.query(AttendanceRecord)
    if institute != "ALL":
        q1 = q1.filter(AssessmentRecord.institute == institute)
        q2 = q2.filter(TrainerFeedbackRecord.institute == institute)
        q3 = q3.filter(StudentRoster.institute == institute)
        q4 = q4.filter(AttendanceRecord.institute == institute)
    d1 = q1.delete()
    d2 = q2.delete()
    d3 = q3.delete()
    d4 = q4.delete()
    db.commit()
    return {"message": f"Reset Complete! Cleared {d1} assessments, {d4} attendance logs, {d2} feedback records, and {d3} roster entries."}


# ==========================================
# ASSESSMENT DATA PIPELINE
# ==========================================
@app.get("/api/assessments/")
def get_all_assessments(institute: str, db: Session = Depends(get_db)):
    query = db.query(AssessmentRecord)
    if institute != "ALL":
        query = query.filter(AssessmentRecord.institute == institute)

    output = []
    for r in query.all():
        score = r.score_percentage if r.score_percentage is not None else 0.0
        if math.isnan(score) or math.isinf(score):
            score = 0.0

        date_str = "Unknown"
        if r.assessment_date:
            try:
                date_str = r.assessment_date.strftime("%Y-%m-%d")
            except Exception:
                pass

        output.append({
            "Roll No": str(r.roll_no) if r.roll_no else "Unknown",
            "Name": str(r.name) if r.name else "Unknown",
            "Department": str(r.department) if r.department else "General",
            "Section": str(r.section) if r.section else "General",
            "Date": date_str,
            "Score": round(score, 2),
            "Status": str(r.status) if r.status else "Present",
            "Conduct": str(r.conduct_metrics) if r.conduct_metrics else "GENUINE",
            "Link": str(r.report_link) if r.report_link else "",
        })
    return output


@app.post("/upload-assessment/")
def upload_assessment(institute: str = Form(...), files: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    if institute == "ALL":
        return {"message": "Error: You must select a specific institute."}
    try:
        total_records_added = 0
        existing_students = db.query(StudentRoster).filter(StudentRoster.institute == institute).all()
        student_map = {s.roll_no: s for s in existing_students}

        for file in files:
            if not file.filename.endswith(('.xlsx', '.xls', '.csv')):
                continue
            db.query(AssessmentRecord).filter(
                AssessmentRecord.source_file == file.filename,
                AssessmentRecord.institute == institute
            ).delete()
            db.commit()

            file.file.seek(0)
            df = pd.read_csv(file.file) if file.filename.endswith('.csv') else pd.read_excel(file.file)
            cols = df.columns

            roll_col = next((c for c in cols if any(x in str(c).lower() for x in ['roll', 'prn', 'registration', 'register'])), None)
            if not roll_col:
                roll_col = next((c for c in cols if str(c).strip().lower() in ['id', 'student id']), None)
            pct_col = next((c for c in cols if 'percentage' in str(c).lower() or 'score' in str(c).lower()), None)
            link_col = next((c for c in cols if 'public report' in str(c).lower() or 'link' in str(c).lower()), None)
            date_col = next((c for c in cols if 'out of' in str(c).lower() or 'started on' in str(c).lower()), None)
            conduct_col = next((c for c in cols if 'conduct metrics' in str(c).lower() or 'flagged' in str(c).lower()), None)
            name_col = next((c for c in cols if 'name' in str(c).lower()), None)
            email_col = next((c for c in cols if 'email' in str(c).lower()), None)

            dept_col = next((c for c in cols if str(c).lower() in ['department', 'dept', 'branch']), None)
            sec_col = next((c for c in cols if 'section' in str(c).lower() and 'branch' not in str(c).lower()), None)
            combined_branch_sec_col = next((c for c in cols if 'branch' in str(c).lower() and 'section' in str(c).lower()), None)

            if not roll_col or not pct_col:
                continue

            parsed_date = datetime.now().date()
            if date_col:
                try:
                    date_str = str(date_col).split('(')[0].strip() if 'out of' in str(date_col).lower() else str(df[date_col].iloc[0])
                    parsed_date = pd.to_datetime(date_str, format="%d/%m/%Y").date()
                except Exception:
                    pass

            new_assessments = []
            for _, row in df.iterrows():
                raw_roll = str(row[roll_col]).replace('\xa0', '').strip() if pd.notna(row[roll_col]) else "Unknown"
                if raw_roll == "Unknown" or raw_roll.lower() == "nan":
                    continue

                score_val = str(row[pct_col]).replace('\xa0', '').strip() if pd.notna(row[pct_col]) else None
                if not score_val or score_val.lower() == "nan":
                    continue

                status = "Present"
                final_score = 0.0
                if 'ABSENT' in score_val.upper():
                    status = "Absent"
                else:
                    try:
                        final_score = float(score_val)
                        if math.isnan(final_score) or math.isinf(final_score):
                            final_score = 0.0
                    except Exception:
                        continue

                conduct = str(row[conduct_col]).strip().upper() if conduct_col and pd.notna(row[conduct_col]) else "GENUINE"
                report_url = str(row[link_col]).strip() if link_col and pd.notna(row[link_col]) else ""
                final_name = str(row[name_col]).replace('\xa0', '').strip() if name_col and pd.notna(row[name_col]) else "Unknown"
                final_email = str(row[email_col]).replace('\xa0', '').strip() if email_col and pd.notna(row[email_col]) else ""

                final_dept = "General"
                final_sec = "General"
                if combined_branch_sec_col and pd.notna(row[combined_branch_sec_col]):
                    parts = str(row[combined_branch_sec_col]).split('-')
                    final_dept = parts[0].strip()
                    if len(parts) > 1:
                        final_sec = parts[1].strip()
                else:
                    if dept_col and pd.notna(row[dept_col]):
                        final_dept = str(row[dept_col]).strip()
                    if sec_col and pd.notna(row[sec_col]):
                        final_sec = str(row[sec_col]).strip()

                student = student_map.get(raw_roll)
                if not student:
                    student = StudentRoster(
                        institute=institute,
                        roll_no=raw_roll,
                        name=final_name,
                        department=final_dept,
                        section=final_sec,
                        email=final_email,
                    )
                    db.add(student)
                    student_map[raw_roll] = student
                else:
                    if final_name != "Unknown":
                        student.name = final_name
                    if final_dept != "General":
                        student.department = final_dept
                    if final_sec != "General":
                        student.section = final_sec
                    if final_email and "@" in final_email:
                        student.email = final_email

                new_assessments.append(AssessmentRecord(
                    institute=institute,
                    roll_no=raw_roll,
                    name=student.name,
                    department=student.department,
                    section=student.section,
                    assessment_date=parsed_date,
                    score_percentage=final_score,
                    status=status,
                    conduct_metrics=conduct,
                    report_link=report_url,
                    source_file=file.filename,
                ))
                total_records_added += 1

            db.add_all(new_assessments)
            db.commit()

        return {"message": f"Successfully processed {total_records_added} assessment records for {institute}!"}
    except Exception as e:
        return {"message": f"Server Error: {str(e)}"}


# ==========================================
# MULTI-SHEET ATTENDANCE & CERTIFICATION PIPELINE
# ==========================================
def infer_department_from_section(sec_name: str, filename: str) -> str:
    s_up = sec_name.upper()
    f_up = filename.upper()
    if "CORE" in s_up or "CORE" in f_up:
        return "CSE CORE"
    if "AIML" in s_up or "AIML" in f_up:
        return "CSE AIML"
    if any(k in s_up for k in ["DS", "CC", "CS"]) or "DSBS" in f_up:
        return "DSBS"
    return "General"


def process_attendance_sheet(df: pd.DataFrame, sheet_name: str, filename: str, institute: str, db: Session, student_map: dict) -> int:
    cols = list(df.columns)
    if len(cols) < 5:
        return 0

    reg_col = next((c for c in cols if any(x in str(c).lower() for x in ['register', 'registration', 'roll', 'prn'])), cols[1])
    name_col = next((c for c in cols if 'name' in str(c).lower()), cols[2])
    contact_col = next((c for c in cols if 'contact' in str(c).lower() or 'phone' in str(c).lower()), cols[3] if len(cols) > 3 else None)
    email_col = next((c for c in cols if 'mail' in str(c).lower()), cols[4] if len(cols) > 4 else None)

    dept_name = infer_department_from_section(sheet_name, filename)
    sec_clean = sheet_name.strip()

    # Identify all session date columns (skip inline 'Percentage (...)' columns)
    session_cols = []
    for c in cols[5:]:
        c_str = str(c).strip()
        if "percentage" in c_str.lower() or "total" in c_str.lower() or "unnamed" in c_str.lower():
            continue
        m = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', c_str)
        if m:
            raw_date_str = m.group(1)
            try:
                s_date = pd.to_datetime(raw_date_str, format="%d/%m/%Y").date()
            except Exception:
                continue
            lines = [line.strip() for line in c_str.split('\n') if line.strip()]
            s_slot = lines[1] if len(lines) > 1 else "Regular Slot"
            s_label = f"{s_date.strftime('%Y-%m-%d')} ({s_slot})"
            session_cols.append((c, s_date, s_slot, s_label))

    if not session_cols:
        return 0

    # Filter valid student rows (exclude bottom TOTAL / NaN summary rows)
    valid_rows = []
    for _, row in df.iterrows():
        raw_reg = str(row[reg_col]).replace('\xa0', '').strip() if pd.notna(row[reg_col]) else ""
        if not raw_reg or raw_reg.lower() in ["nan", "none", "total", "total:"]:
            continue
        if not any(ch.isdigit() for ch in raw_reg):
            continue
        valid_rows.append((raw_reg, row))

    if not valid_rows:
        return 0

    # Pre-analyze each session column to determine if it was Conducted (1) or Cancelled/Holiday (0)
    col_meta = {}
    for c, s_date, s_slot, s_label in session_cols:
        raw_vals = []
        for _, row in valid_rows:
            v = row[c]
            if pd.notna(v):
                s_v = str(v).replace('\xa0', '').replace('`', '').strip()
                if s_v != "":
                    raw_vals.append(s_v)

        has_normal_marks = False
        text_reasons = []
        for sv in raw_vals:
            sv_up = sv.upper()
            if sv_up in ['1', '1.0', '0', '0.0', 'OD', 'P', 'A']:
                has_normal_marks = True
            elif 'MASS BUNK' in sv_up:
                has_normal_marks = True
            else:
                try:
                    float(sv)
                    has_normal_marks = True
                except Exception:
                    text_reasons.append(sv)

        if not has_normal_marks and text_reasons:
            # Entire column is a Holiday / Industrial Visit / Cancelled Session
            col_meta[c] = (0, text_reasons[0])
        else:
            col_meta[c] = (1, "")

    new_records = []
    for raw_reg, row in valid_rows:
        st_name = str(row[name_col]).replace('\xa0', '').strip() if name_col and pd.notna(row[name_col]) else "Unknown"
        st_contact = str(row[contact_col]).replace('\xa0', '').strip() if contact_col and pd.notna(row[contact_col]) else ""
        if st_contact.endswith(".0"):
            st_contact = st_contact[:-2]
        st_email = str(row[email_col]).replace('\xa0', '').strip() if email_col and pd.notna(row[email_col]) else ""

        student = student_map.get(raw_reg)
        if not student:
            student = StudentRoster(
                institute=institute,
                roll_no=raw_reg,
                name=st_name,
                department=dept_name,
                section=sec_clean,
                email=st_email,
            )
            db.add(student)
            student_map[raw_reg] = student
        else:
            if st_email and "@" in st_email:
                student.email = st_email

        for c, s_date, s_slot, s_label in session_cols:
            is_cond, default_reason = col_meta[c]
            val = row[c]
            s_val = str(val).replace('\xa0', '').replace('`', '').strip() if pd.notna(val) else ""
            s_up = s_val.upper()

            if is_cond == 0:
                status = "No Class"
                reason = s_val if s_val else default_reason
            else:
                if s_up in ['1', '1.0', 'P']:
                    status = "Present"
                    reason = ""
                elif s_up == 'OD':
                    status = "OD"  # Counted as Present in analytics
                    reason = "On Duty (OD)"
                elif 'MASS BUNK' in s_up:
                    status = "Mass Bunk"  # Counted as Absent in analytics
                    reason = "Mass Bunk"
                elif s_up in ['0', '0.0', 'A', '']:
                    status = "Absent"
                    reason = ""
                else:
                    try:
                        num_v = float(s_val)
                        status = "Present" if num_v >= 1.0 else "Absent"
                        reason = ""
                    except Exception:
                        # Row-level holiday/cancel text
                        is_cond = 0
                        status = "No Class"
                        reason = s_val

            new_records.append(AttendanceRecord(
                institute=institute,
                roll_no=raw_reg,
                name=st_name,
                contact=st_contact,
                email=st_email,
                department=dept_name,
                section=sec_clean,
                session_date=s_date,
                session_slot=s_slot,
                session_label=s_label,
                is_conducted=is_cond,
                status=status,
                cancel_reason=reason,
                source_file=filename,
            ))

    db.bulk_save_objects(new_records)
    db.commit()
    return len(new_records)


@app.post("/upload-attendance/")
def upload_attendance(institute: str = Form(...), files: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    if institute == "ALL":
        return {"message": "Error: Please select a specific institute workspace."}
    try:
        total_cells = 0
        total_sheets = 0
        existing_students = db.query(StudentRoster).filter(StudentRoster.institute == institute).all()
        student_map = {s.roll_no: s for s in existing_students}

        for file in files:
            if not file.filename.endswith(('.xlsx', '.xls', '.csv')):
                continue
            db.query(AttendanceRecord).filter(
                AttendanceRecord.source_file == file.filename,
                AttendanceRecord.institute == institute
            ).delete()
            db.commit()

            file.file.seek(0)
            if file.filename.endswith('.csv'):
                df = pd.read_csv(file.file)
                sec_guess = file.filename.rsplit('.', 1)[0]
                total_cells += process_attendance_sheet(df, sec_guess, file.filename, institute, db, student_map)
                total_sheets += 1
            else:
                xls = pd.ExcelFile(file.file)
                for sheet_name in xls.sheet_names:
                    df = pd.read_excel(xls, sheet_name=sheet_name)
                    added = process_attendance_sheet(df, sheet_name, file.filename, institute, db, student_map)
                    if added > 0:
                        total_cells += added
                        total_sheets += 1

        return {"message": f"Successfully processed {total_sheets} section sheets ({total_cells} session logs) for {institute}!"}
    except Exception as e:
        return {"message": f"Attendance Upload Error: {str(e)}"}


@app.get("/api/attendance/")
def get_attendance_data(institute: str, db: Session = Depends(get_db)):
    query = db.query(AttendanceRecord)
    if institute != "ALL":
        query = query.filter(AttendanceRecord.institute == institute)

    records = query.all()
    if not records:
        return {"students": [], "sessions": [], "logs": []}

    # Compact payload structure so 35,000+ session logs transfer in <0.5 seconds
    students_dict = {}
    sessions_dict = {}
    logs_list = []

    for r in records:
        if r.roll_no not in students_dict:
            students_dict[r.roll_no] = {
                "roll": r.roll_no,
                "name": r.name,
                "contact": r.contact or "-",
                "email": r.email or "-",
                "dept": r.department,
                "sec": r.section,
            }
        date_str = r.session_date.strftime("%Y-%m-%d") if r.session_date else "Unknown"
        sess_key = f"{r.section}||{date_str}||{r.session_slot}"
        if sess_key not in sessions_dict:
            sessions_dict[sess_key] = {
                "key": sess_key,
                "dept": r.department,
                "sec": r.section,
                "date": date_str,
                "slot": r.session_slot,
                "label": r.session_label,
                "conducted": r.is_conducted,
                "reason": r.cancel_reason or "",
            }
        elif r.cancel_reason and not sessions_dict[sess_key]["reason"]:
            sessions_dict[sess_key]["reason"] = r.cancel_reason

        # Status codes: P=Present, OD=On Duty (Present), A=Absent, MB=Mass Bunk (Absent), NC=No Class
        short_st = "P"
        if r.status == "OD":
            short_st = "OD"
        elif r.status == "Absent":
            short_st = "A"
        elif r.status == "Mass Bunk":
            short_st = "MB"
        elif r.status == "No Class" or r.is_conducted == 0:
            short_st = "NC"

        logs_list.append([r.roll_no, sess_key, short_st])

    return {
        "students": list(students_dict.values()),
        "sessions": list(sessions_dict.values()),
        "logs": logs_list,
    }


# ==========================================
# TRAINER FEEDBACK DATA PIPELINE
# ==========================================
def process_feedback_dataframe(df: pd.DataFrame, source_name: str, institute: str, db: Session):
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
    stack_col = next((c for c in cols if 'stack' in str(c).lower() or 'course' in str(c).lower() or 'branch' in str(c).lower()), None)

    fn_lower = source_name.lower()
    inferred_stack = "General"
    if "cyber" in fn_lower:
        inferred_stack = "Cyber Security"
    elif "data science" in fn_lower or "dsml" in fn_lower:
        inferred_stack = "Data Science & ML"
    elif "java" in fn_lower:
        inferred_stack = "Java Full Stack"
    elif "mern" in fn_lower:
        inferred_stack = "MERN Stack"

    new_feedbacks = []
    for _, row in df.iterrows():
        parsed_ts = datetime.now()
        if ts_col and pd.notna(row[ts_col]):
            try:
                parsed_ts = pd.to_datetime(str(row[ts_col]))
            except Exception:
                pass

        num_rating = 0.0
        rating_lbl = ""
        if rating_col and pd.notna(row[rating_col]):
            val = row[rating_col]
            try:
                num_rating = float(val)
                if math.isnan(num_rating) or math.isinf(num_rating):
                    num_rating = 0.0
            except Exception:
                rating_lbl = str(val).strip()
                if "excel" in rating_lbl.lower():
                    num_rating = 5.0
                elif "good" in rating_lbl.lower():
                    num_rating = 4.0
                elif "avg" in rating_lbl.lower() or "average" in rating_lbl.lower():
                    num_rating = 3.0
                elif "poor" in rating_lbl.lower():
                    num_rating = 2.0
                else:
                    num_rating = 3.0

        trainer = str(row[trainer_col]).strip() if trainer_col and pd.notna(row[trainer_col]) else "Assigned Faculty"
        sec = str(row[sec_col]).strip() if sec_col and pd.notna(row[sec_col]) else "General"
        st_name = str(row[name_col]).strip() if name_col and pd.notna(row[name_col]) else "Anonymous"
        st_reg = str(row[reg_col]).strip() if reg_col and pd.notna(row[reg_col]) else ""
        und = str(row[und_col]).strip() if und_col and pd.notna(row[und_col]) else ""
        clarity = str(row[clarity_col]).strip() if clarity_col and pd.notna(row[clarity_col]) else ""
        pace = str(row[pace_col]).strip() if pace_col and pd.notna(row[pace_col]) else ""
        diff = str(row[diff_col]).strip() if diff_col and pd.notna(row[diff_col]) and str(row[diff_col]).lower() not in ['no', 'none', 'nil', 'nan', 'na', '.'] else ""
        sugg = str(row[sugg_col]).strip() if sugg_col and pd.notna(row[sugg_col]) and str(row[sugg_col]).lower() not in ['no', 'none', 'nil', 'nan', 'na', '.'] else ""

        final_stack = inferred_stack
        if stack_col and pd.notna(row[stack_col]):
            final_stack = str(row[stack_col]).strip()

        new_feedbacks.append(TrainerFeedbackRecord(
            institute=institute,
            submission_timestamp=parsed_ts,
            stack=final_stack,
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
            source_file=source_name,
        ))

    db.add_all(new_feedbacks)
    db.commit()
    return len(new_feedbacks)


@app.post("/upload-feedback/")
def upload_feedback(institute: str = Form(...), files: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    if institute == "ALL":
        return {"message": "Error: Select a specific institute for feedback upload."}
    try:
        total = 0
        for file in files:
            if not file.filename.endswith(('.xlsx', '.xls', '.csv')):
                continue
            db.query(TrainerFeedbackRecord).filter(
                TrainerFeedbackRecord.source_file == file.filename,
                TrainerFeedbackRecord.institute == institute
            ).delete()
            db.commit()

            file.file.seek(0)
            df = pd.read_csv(file.file) if file.filename.endswith('.csv') else pd.read_excel(file.file)
            total += process_feedback_dataframe(df, file.filename, institute, db)
        return {"message": f"Successfully ingested {total} trainer feedback records for {institute}!"}
    except Exception as e:
        return {"message": f"Server Error: {str(e)}"}


@app.post("/api/sync-feedback/")
def sync_live_feedback(institute: str, db: Session = Depends(get_db)):
    config = db.query(CommunicationConfig).filter(CommunicationConfig.institute == institute).first()
    if not config or not config.google_sheet_url:
        return {"message": "Error: No Google Sheet URLs configured for this workspace."}

    urls = [url.strip() for url in config.google_sheet_url.split(',') if url.strip()]
    if not urls:
        return {"message": "Error: Invalid URL format."}

    try:
        db.query(TrainerFeedbackRecord).filter(
            TrainerFeedbackRecord.source_file.like("Live_Sheet_%"),
            TrainerFeedbackRecord.institute == institute
        ).delete()
        db.commit()

        total = 0
        for i, url in enumerate(urls):
            source_name = f"Live_Sheet_{i+1}"
            df = pd.read_csv(url)
            total += process_feedback_dataframe(df, source_name, institute, db)

        return {"message": f"Successfully synced {total} live feedback responses from Google Sheets!"}
    except Exception as e:
        return {"message": f"Sync Failed. Ensure your Google Sheet is published as CSV. Error: {str(e)}"}


@app.get("/api/feedbacks/")
def get_feedbacks(institute: str, db: Session = Depends(get_db)):
    query = db.query(TrainerFeedbackRecord)
    if institute != "ALL":
        query = query.filter(TrainerFeedbackRecord.institute == institute)

    output = []
    for r in query.all():
        rating = r.rating if r.rating is not None else 0.0
        if math.isnan(rating) or math.isinf(rating):
            rating = 0.0

        date_str = "Unknown"
        time_str = "00:00:00"
        if r.submission_timestamp:
            try:
                date_str = r.submission_timestamp.strftime("%Y-%m-%d")
                time_str = r.submission_timestamp.strftime("%H:%M:%S")
            except Exception:
                pass

        output.append({
            "Date": date_str,
            "Time": time_str,
            "Stack": str(r.stack) if r.stack else "General",
            "Trainer": str(r.trainer_name) if r.trainer_name else "Assigned Faculty",
            "Section": str(r.section) if r.section else "General",
            "Student": str(r.student_name) if r.student_name else "Anonymous",
            "RegNo": str(r.student_reg_no) if r.student_reg_no else "-",
            "Rating": round(rating, 2),
            "Understanding": str(r.understanding) if r.understanding else "-",
            "Clarity": str(r.clarity) if r.clarity else "-",
            "Pace": str(r.pace) if r.pace else "-",
            "Difficulties": str(r.difficulties) if r.difficulties else "-",
            "Suggestions": str(r.suggestions) if r.suggestions else "-",
        })
    return output


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
            "sender_email": config.sender_email,
            "sender_password": config.sender_password,
            "frequency": config.frequency,
            "cc": config.cc_emails,
            "bcc": config.bcc_emails,
            "template": config.email_template,
            "google_sheet_url": config.google_sheet_url or "",
        }
    return {
        "sender_email": "",
        "sender_password": "",
        "frequency": "Weekly (Friday 5:00 PM)",
        "cc": "",
        "bcc": "",
        "template": "Dear {Student_Name},\n\nYour average score is {Score_Avg}%. Attached is your Scorecard.\n\nRegards,\nAdmin",
        "google_sheet_url": "",
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
        except Exception:
            pass

    records = query.all()
    if not records:
        return {"message": "No assessment records found for this workspace to dispatch."}

    df = pd.DataFrame([{
        "Roll No": r.roll_no,
        "Name": r.name,
        "Department": r.department,
        "Section": r.section,
        "Date": r.assessment_date,
        "Score": r.score_percentage,
        "Status": r.status,
        "Conduct": r.conduct_metrics,
        "Report Link": r.report_link,
    } for r in records])

    emails_sent = 0
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(config.sender_email, config.sender_password)

        for student in students:
            if not student.email or "@" not in student.email:
                continue
            student_df = df[df["Roll No"] == student.roll_no]
            if student_df.empty:
                continue

            avg_score = student_df["Score"].mean() if not student_df["Score"].isnull().all() else 0
            custom_message = config.email_template.replace("{Student_Name}", student.name).replace("{Score_Avg}", f"{avg_score:.1f}")

            msg = MIMEMultipart()
            msg['From'] = config.sender_email
            msg['To'] = student.email
            msg['Cc'] = config.cc_emails
            msg['Subject'] = f"[{institute}] BENCHMARK Performance Scorecard"
            msg.attach(MIMEText(custom_message, 'plain'))

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                student_df.to_excel(writer, index=False, sheet_name="Scorecard")
            attachment = MIMEApplication(output.getvalue(), Name=f"{student.name}_Scorecard.xlsx")
            attachment['Content-Disposition'] = f'attachment; filename="{student.name}_Scorecard.xlsx"'
            msg.attach(attachment)

            recipients = [student.email]
            if config.cc_emails:
                recipients.extend([e.strip() for e in config.cc_emails.split(",") if e.strip()])
            if config.bcc_emails:
                recipients.extend([e.strip() for e in config.bcc_emails.split(",") if e.strip()])

            server.sendmail(config.sender_email, recipients, msg.as_string())
            emails_sent += 1

        server.quit()
        return {"message": f"Success! Dispatched {emails_sent} automated scorecards using {config.sender_email}."}
    except Exception as e:
        return {"message": f"Email System Error: {str(e)}"}
