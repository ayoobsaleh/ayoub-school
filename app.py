from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Depends, Request, Query, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, field_validator
from typing import Optional, List, Union
import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import shutil
import threading
import time

import database as db
import timetable_rules

# تهيئة مجلد البيانات (قرص دائم إن وُجد) قبل أي عملية أخرى
db.bootstrap_data_dir()

try:
    import backup_service
except ImportError:
    backup_service = None

app = FastAPI(title="نظام تحويل ومتابعة سلوك الطلاب - المدرسة", docs_url=None, redoc_url=None, openapi_url=None)

# ضغط الاستجابات: index.html حجمه ~560KB وينخفض إلى ~70KB تقريباً
app.add_middleware(GZipMiddleware, minimum_size=1024)

SCHOOL_STRUCTURE = timetable_rules.load_structure()
STATIC_DIR = os.path.join(db.APP_DIR, "static")

# الجدول المعتمد خط أحمر: مقفل افتراضياً ضد أي تعديل عبر الواجهة.
# لفتحه مؤقتاً (بقرار المدير فقط): ضع متغير البيئة TIMETABLE_LOCK=0 في Render.
TIMETABLE_LOCKED = os.environ.get("TIMETABLE_LOCK", "1") != "0"

# =========================================================================
# المصادقة بالرمز السري (PIN) على الخادم — الرموز المعتمدة دون أي تغيير
# =========================================================================
ADMIN_ACCOUNTS = {
    "0000": {"role": "principal", "name": "أ. حاتم النغيمشي", "title": "مدير المدرسة"},
    "1111": {"role": "vp", "name": "أ. مشعل الخريف", "title": "وكيل شؤون الطلاب"},
    "2222": {"role": "counselor", "name": "أ. فهد السلامة", "title": "الموجه الطلابي"},
}

ALL_ROLES = ("principal", "vp", "counselor", "teacher")
ADMIN_ROLES = ("principal", "vp")
CASE_ROLES = ("principal", "vp", "counselor")


def _load_secret():
    env = os.environ.get("SECRET_KEY")
    if env:
        return env.encode()
    path = os.path.join(db.DATA_DIR, ".secret_key")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read().strip()
    key = secrets.token_hex(32).encode()
    with open(path, "wb") as f:
        f.write(key)
    return key


SECRET_KEY = _load_secret()
TOKEN_TTL_SHORT = 12 * 3600          # جلسة عادية: 12 ساعة
TOKEN_TTL_REMEMBER = 30 * 24 * 3600  # "تذكر هذا الجهاز": 30 يوماً


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue_token(user: dict, remember: bool) -> str:
    payload = dict(user)
    payload["exp"] = int(time.time()) + (TOKEN_TTL_REMEMBER if remember else TOKEN_TTL_SHORT)
    body = _b64(json.dumps(payload, ensure_ascii=False).encode())
    sig = _b64(hmac.new(SECRET_KEY, body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_token(token: str) -> Optional[dict]:
    try:
        body, sig = token.split(".", 1)
        expected = _b64(hmac.new(SECRET_KEY, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_unb64(body))
        if payload.get("exp", 0) < time.time():
            return None
        if payload.get("role") not in ALL_ROLES:
            return None
        return payload
    except Exception:
        return None


def _read_teachers():
    try:
        data = db.get_teachers_list()
        return data if isinstance(data, list) else []
    except Exception:
        return []


def resolve_pin(pin: str) -> Optional[dict]:
    if pin in ADMIN_ACCOUNTS:
        return dict(ADMIN_ACCOUNTS[pin])
    for t in _read_teachers():
        t_pin = str(t.get("pin") or (1000 + int(t.get("id", 0))))
        if hmac.compare_digest(t_pin, pin):
            return {
                "role": "teacher",
                "id": t.get("id"),
                "name": t.get("name", ""),
                "subject": t.get("subject", ""),
                "title": f"معلم - {t.get('subject', '')}",
            }
    return None


# حماية من التخمين: 8 محاولات خاطئة خلال 10 دقائق من نفس العنوان ⇒ إيقاف 10 دقائق
_fail_lock = threading.Lock()
_failed_attempts = {}
MAX_FAILS = 8
FAIL_WINDOW = 600


def _client_ip(request: Request) -> str:
    # آخر عنوان هو الذي أضافه وكيل Render (الأول يمكن للمهاجم تزويره)
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


GLOBAL_MAX_FAILS = 60  # سقف عام لكل العناوين معاً (حماية من التخمين الموزّع)


def _check_rate(ip: str):
    now = time.time()
    with _fail_lock:
        total = sum(1 for lst in _failed_attempts.values() for t in lst if now - t < FAIL_WINDOW)
        if total >= GLOBAL_MAX_FAILS:
            raise HTTPException(status_code=429, detail="تم إيقاف تسجيل الدخول مؤقتاً بسبب محاولات كثيرة. حاول بعد دقائق")
        attempts = [t for t in _failed_attempts.get(ip, []) if now - t < FAIL_WINDOW]
        _failed_attempts[ip] = attempts
        if len(attempts) >= MAX_FAILS:
            wait = int(FAIL_WINDOW - (now - attempts[0]))
            raise HTTPException(status_code=429, detail=f"محاولات كثيرة خاطئة. حاول بعد {max(1, wait // 60)} دقيقة")


def _record_fail(ip: str):
    with _fail_lock:
        _failed_attempts.setdefault(ip, []).append(time.time())


def current_user(request: Request) -> dict:
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else ""
    user = verify_token(token) if token else None
    if not user:
        raise HTTPException(status_code=401, detail="يرجى تسجيل الدخول")
    return user


def require(*roles):
    def dep(user: dict = Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="لا تملك صلاحية لهذا الإجراء")
        return user
    return dep


# =========================================================================
# ترويسات الأمان
# =========================================================================
CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: blob: https:; "
    "connect-src 'self' wss: ws:; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Strict-Transport-Security"] = "max-age=31536000"
    response.headers["Content-Security-Policy"] = CSP
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# =========================================================================
# تنقية المدخلات النصية (حماية من حقن السكربتات XSS لأن الواجهة تعرض البيانات عبر innerHTML)
# =========================================================================
_STRICT_CHARS = re.compile(r"[<>\"'`\\]")
_TEXT_CHARS = re.compile(r"[<>`]")


def clean_name(v, max_len=120):
    if v is None:
        return v
    return _STRICT_CHARS.sub("", str(v)).strip()[:max_len]


def clean_text(v, max_len=4000):
    if v is None:
        return v
    return _TEXT_CHARS.sub("", str(v)).strip()[:max_len]


class CleanModel(BaseModel):
    """يُنقّي كل الحقول النصية تلقائياً."""

    @field_validator("*", mode="before")
    @classmethod
    def _sanitize(cls, v, info):
        if isinstance(v, str):
            strict = {"name", "teacher_name", "grade", "classroom", "national_id", "guardian_phone", "phone",
                      "subject", "period", "behavior_name", "behavior_degree", "status", "user_name", "user_role"}
            return clean_name(v) if info.field_name in strict else clean_text(v)
        return v


# إدارة اتصالات WebSocket للإشعارات اللحظية (تتطلب رمز دخول صالح)
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message, ensure_ascii=False))
            except Exception:
                disconnected.append(connection)
        for dead_conn in disconnected:
            self.disconnect(dead_conn)


manager = ConnectionManager()


@app.on_event("startup")
def on_startup():
    db.init_db()
    print(f"[DB] backend={db.backend_name()} persistent={'yes' if db.IS_PG or os.environ.get('DATA_DIR') else 'NO (ephemeral disk)'}")
    if backup_service:
        backup_service.start_backup_scheduler()


# النماذج
class LoginRequest(BaseModel):
    pin: str
    remember: Optional[bool] = False


class ReferralCreate(CleanModel):
    student_id: int
    teacher_name: str
    subject: Optional[str] = ""
    period: Optional[str] = ""
    behavior_id: Optional[int] = None
    behavior_name: str
    behavior_degree: str
    notes: Optional[str] = ""


class ActionUpdate(CleanModel):
    action_taken: str
    action_notes: Optional[str] = ""
    status: Optional[str] = "resolved"


class StudentCreate(CleanModel):
    name: str
    national_id: Optional[str] = ""
    grade: str
    classroom: str
    guardian_phone: Optional[str] = ""


class AttendanceCreate(CleanModel):
    student_id: int
    date: str
    type: Optional[str] = None
    status: Optional[str] = None
    period: Optional[Union[str, int]] = "اليوم كامل"
    minutes_late: Optional[int] = 0
    has_excuse: Optional[int] = 0
    is_excused: Optional[int] = 0
    excuse_notes: Optional[str] = ""
    notes: Optional[str] = ""
    guardian_notified: Optional[int] = 0
    action_taken: Optional[str] = ""


class CounselorCaseCreate(CleanModel):
    student_id: int
    referral_id: Optional[int] = None
    reason: str
    case_type: Optional[str] = "سلوكي"
    referred_by: Optional[str] = "وكيل شؤون الطلاب"
    referred_to: Optional[str] = "الموجه الطلابي"
    due_date: Optional[str] = None
    required_action: Optional[str] = ""
    intervention_plan: Optional[str] = ""
    notes: Optional[str] = ""


class CounselorCaseUpdate(CleanModel):
    status: str
    intervention_plan: Optional[str] = ""
    outcome: Optional[str] = ""
    notes: Optional[str] = ""


class GuardianCommunicationCreate(CleanModel):
    student_id: int
    comm_type: Optional[str] = None
    channel: Optional[str] = None
    phone: Optional[str] = ""
    message_content: Optional[str] = None
    reason: Optional[str] = ""
    outcome: Optional[str] = ""
    notes: Optional[str] = ""
    referral_id: Optional[int] = None
    attendance_id: Optional[int] = None
    result_status: Optional[str] = None


class AuditLogCreate(CleanModel):
    user_name: Optional[str] = ""
    user_role: Optional[str] = ""
    action: str
    target_type: Optional[str] = ""
    target_id: Optional[str] = ""
    details: Optional[str] = ""


class WaitingItem(CleanModel):
    id: Union[int, str]
    day: str
    period: str
    assignedTeacher: str
    absentTeacher: str
    classroom: Optional[str] = "-"
    notes: Optional[str] = ""
    status: Optional[str] = "assigned"
    selectionReason: Optional[str] = ""
    date: Optional[str] = None
    force: Optional[bool] = False

    @field_validator("assignedTeacher", "absentTeacher", "day", "period", "classroom", mode="after")
    @classmethod
    def _strict(cls, v):
        return clean_name(v)


# =========================================================================
# مسارات المصادقة
# =========================================================================
@app.post("/api/auth/login")
def login(req: LoginRequest, request: Request):
    ip = _client_ip(request)
    _check_rate(ip)
    pin = re.sub(r"\D", "", str(req.pin or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")))[:4]
    user = resolve_pin(pin) if len(pin) == 4 else None
    if not user:
        _record_fail(ip)
        raise HTTPException(status_code=401, detail="الرمز غير صحيح")
    with _fail_lock:
        _failed_attempts.pop(ip, None)
    token = issue_token(user, bool(req.remember))
    try:
        db.log_audit_event(user["name"], user["role"], "login", "auth", "", f"ip={ip}")
    except Exception:
        pass
    return {"token": token, "user": user}


@app.get("/api/auth/me")
def auth_me(user: dict = Depends(current_user)):
    return {k: v for k, v in user.items() if k != "exp"}


# =========================================================================
# المسارات والواجهات البرمجية (API)
# =========================================================================
@app.get("/api/students")
def get_students(search: str = "", user: dict = Depends(require(*ALL_ROLES))):
    rows = db.get_all_students(search[:100])
    if user["role"] == "teacher":
        for r in rows:
            r.pop("national_id", None)
    return rows


@app.get("/api/behaviors")
def get_behaviors(user: dict = Depends(require(*ALL_ROLES))):
    return db.get_behaviors()


@app.get("/api/teachers")
def get_teachers(user: dict = Depends(require(*ALL_ROLES))):
    return db.get_teachers()


@app.get("/api/referrals")
def get_referrals(status: Optional[str] = "all", student_id: Optional[int] = None,
                  user: dict = Depends(require(*ALL_ROLES))):
    rows = db.get_all_referrals(status, student_id)
    if user["role"] == "teacher":
        name = user.get("name", "")
        rows = [r for r in rows if name and name in (r.get("teacher_name") or "")]
    return rows


@app.post("/api/referrals")
async def create_referral(referral_data: ReferralCreate, user: dict = Depends(require(*ALL_ROLES))):
    data = referral_data.model_dump()
    if user["role"] == "teacher" and user.get("name", "") not in (data.get("teacher_name") or ""):
        data["teacher_name"] = f"أ. {user['name']}"
    referral = db.create_referral(data)
    if not referral:
        raise HTTPException(status_code=400, detail="فشل إنشاء الإحالة")
    await manager.broadcast({
        "type": "NEW_REFERRAL",
        "data": referral,
        "message": f"تم تحويل الطالب {referral['student_name']} من قِبل {referral['teacher_name']} بسبب: {referral['behavior_name']}"
    })
    return referral


def _strip_confidential(profile: dict, user: dict) -> dict:
    """جلسات التوجيه سرية: لا تظهر للمعلمين."""
    if user["role"] == "teacher" and profile:
        profile["counselor_cases"] = []
        profile["timeline"] = [t for t in profile.get("timeline", []) if t.get("type") != "counselor"]
        if "stats" in profile and "counselor_cases" in profile["stats"]:
            profile["stats"]["counselor_cases"] = 0
        profile.get("student", {}).pop("national_id", None)
    return profile


@app.get("/api/students/{student_id}/archive")
def get_student_archive(student_id: int, user: dict = Depends(require(*ALL_ROLES))):
    archive = db.get_student_archive(student_id)
    if not archive:
        raise HTTPException(status_code=404, detail="الطالب غير موجود")
    return _strip_confidential(archive, user)


@app.post("/api/referrals/{referral_id}/action")
async def update_referral_action(referral_id: int, action: ActionUpdate, user: dict = Depends(require(*ADMIN_ROLES))):
    updated = db.update_referral_action(referral_id, action.action_taken, action.action_notes or "",
                                        action.status or "resolved")
    if not updated:
        raise HTTPException(status_code=404, detail="الإحالة غير موجودة")
    await manager.broadcast({"type": "REFERRAL_UPDATED", "data": updated,
                             "message": f"تم تحديث الإجراء للإحالة رقم #{referral_id}"})
    return updated


@app.post("/api/students")
def add_new_student(student: StudentCreate, user: dict = Depends(require(*ADMIN_ROLES))):
    student_id = db.add_student(student.name, student.national_id, student.grade, student.classroom,
                                student.guardian_phone)
    return {"id": student_id, "message": "تم إضافة الطالب بنجاح"}


@app.put("/api/students/{student_id}")
def edit_student(student_id: int, student: StudentCreate, user: dict = Depends(require(*ADMIN_ROLES))):
    if not student.name or not student.grade or not student.classroom:
        raise HTTPException(status_code=400, detail="الاسم والصف والفصل مطلوبة")
    if not db.update_student(student_id, student.name, student.national_id, student.grade, student.classroom,
                             student.guardian_phone):
        raise HTTPException(status_code=404, detail="الطالب غير موجود")
    db.log_audit_event(user.get("name", ""), user["role"], "student_update", "student", str(student_id), "")
    return {"status": "success", "message": "تم حفظ بيانات الطالب"}


@app.delete("/api/students/{student_id}")
def remove_student(student_id: int, user: dict = Depends(require(*ADMIN_ROLES))):
    if backup_service:
        backup_service.create_backup(reason="pre_student_delete")
    if not db.delete_student(student_id):
        raise HTTPException(status_code=404, detail="الطالب غير موجود")
    db.log_audit_event(user.get("name", ""), user["role"], "student_delete", "student", str(student_id), "")
    return {"status": "success", "message": "تم حذف الطالب"}


@app.post("/api/students/import-csv")
async def import_students_csv(file: UploadFile = File(...), user: dict = Depends(require(*ADMIN_ROLES))):
    contents = await file.read(5 * 1024 * 1024 + 1)
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="حجم ملف CSV أكبر من 5MB")
    try:
        decoded = contents.decode("utf-8-sig")
    except UnicodeDecodeError:
        decoded = contents.decode("windows-1256", errors="ignore")

    reader = csv.reader(io.StringIO(decoded))
    count = 0
    for row in reader:
        if not row or len(row) < 3:
            continue
        if "الاسم" in row[0] or "name" in row[0].lower():
            continue
        name = clean_name(row[0])
        national_id = clean_name(row[1]) if len(row) > 1 else ""
        grade = clean_name(row[2]) if len(row) > 2 else "عام"
        classroom = clean_name(row[3]) if len(row) > 3 else "1"
        guardian_phone = clean_name(row[4]) if len(row) > 4 else ""
        if name:
            db.add_student(name, national_id, grade, classroom, guardian_phone)
            count += 1
    return {"message": f"تم استيراد {count} طالب بنجاح"}


# =========================================================================
# الحضور والغياب والتأخر
# =========================================================================
@app.get("/api/attendance")
def get_attendance(date: Optional[str] = None, user: dict = Depends(require(*CASE_ROLES))):
    return db.get_daily_attendance(date)


@app.post("/api/attendance")
async def create_attendance(att_data: AttendanceCreate, user: dict = Depends(require(*ADMIN_ROLES))):
    att_type = att_data.type or att_data.status or "absence"
    has_excuse = att_data.has_excuse if att_data.has_excuse else (att_data.is_excused or 0)
    period_str = str(att_data.period) if att_data.period is not None else "اليوم كامل"
    excuse_note = att_data.excuse_notes or att_data.notes or ""

    record = db.record_attendance(
        student_id=att_data.student_id, date_str=att_data.date, att_type=att_type, period=period_str,
        minutes_late=att_data.minutes_late or 0, has_excuse=has_excuse, excuse_notes=excuse_note,
        guardian_notified=att_data.guardian_notified or 0, action_taken=att_data.action_taken or ""
    )
    if not record:
        raise HTTPException(status_code=400, detail="فشل تسجيل الحضور")
    await manager.broadcast({
        "type": "ATTENDANCE_RECORDED", "data": record,
        "message": f"تم تسجيل {('تأخر' if record['type'] == 'tardy' else 'غياب')} للطالب {record.get('student_name', '')}"
    })
    return {"status": "success", "data": record}


@app.get("/api/attendance/repeat")
def get_repeat_attendance(threshold: Optional[int] = None, min_count: Optional[int] = None,
                          user: dict = Depends(require(*CASE_ROLES))):
    # الواجهة ترسل min_count بينما كان الخادم يقرأ threshold فقط
    return db.get_repeat_attendance_offenders(threshold_days=threshold or min_count or 3)


@app.get("/api/students/{student_id}/profile")
def get_student_unified_profile(student_id: int, user: dict = Depends(require(*ALL_ROLES))):
    profile = db.get_unified_student_profile(student_id)
    if not profile:
        raise HTTPException(status_code=404, detail="الطالب غير موجود")
    return _strip_confidential(profile, user)


# =========================================================================
# التوجيه الطلابي (سري: المدير والوكيل والموجه فقط)
# =========================================================================
@app.get("/api/counselor/cases")
def get_counselor_cases(status: Optional[str] = "all", user: dict = Depends(require(*CASE_ROLES))):
    return db.get_counselor_cases_list(status)


@app.post("/api/counselor/cases")
async def create_counselor_case(case_data: CounselorCaseCreate, user: dict = Depends(require(*CASE_ROLES))):
    req_action = case_data.required_action or case_data.case_type or ""
    plan = case_data.intervention_plan or case_data.notes or ""
    case = db.create_counselor_case(
        student_id=case_data.student_id, reason=case_data.reason, referral_id=case_data.referral_id,
        referred_by=case_data.referred_by or "وكيل شؤون الطلاب", referred_to=case_data.referred_to or "الموجه الطلابي",
        due_date=case_data.due_date, required_action=req_action, intervention_plan=plan
    )
    if not case:
        raise HTTPException(status_code=400, detail="فشل إنشاء حالة التحويل")
    # لا نبث تفاصيل الحالة السرية؛ إشعار مختصر فقط
    await manager.broadcast({"type": "NEW_COUNSELOR_CASE", "data": {"id": case.get("id")},
                             "message": "تم تسجيل تحويل جديد إلى الموجه الطلابي"})
    return {"status": "success", "id": case.get("id"), "data": case}


@app.post("/api/counselor/cases/{case_id}/update")
async def update_counselor_case(case_id: int, update_data: CounselorCaseUpdate, user: dict = Depends(require(*CASE_ROLES))):
    ok = db.update_counselor_case_status(case_id=case_id, status=update_data.status,
                                         intervention_plan=update_data.intervention_plan or "",
                                         outcome=update_data.outcome or "", notes=update_data.notes or "")
    if not ok:
        raise HTTPException(status_code=400, detail="فشل تحديث الحالة")
    return {"status": "success", "message": "تم تحديث حالة دراسة الطالب بنجاح"}


@app.post("/api/communications/log")
def log_communication(comm: GuardianCommunicationCreate, user: dict = Depends(require(*CASE_ROLES))):
    c_type = comm.comm_type or comm.channel or "هاتف"
    msg = comm.message_content or (f"{comm.reason} - {comm.notes}" if comm.notes else (comm.reason or "تواصل مع ولي الأمر"))
    res_status = comm.result_status or comm.outcome or "تم الإرسال"
    comm_id = db.log_guardian_communication(student_id=comm.student_id, comm_type=c_type, phone=comm.phone or "",
                                            message_content=msg, referral_id=comm.referral_id,
                                            attendance_id=comm.attendance_id, result_status=res_status)
    return {"id": comm_id, "status": "success"}


@app.post("/api/audit")
def log_audit(audit: AuditLogCreate, user: dict = Depends(require(*ALL_ROLES))):
    # هوية المستخدم تؤخذ من الرمز الموقّع وليس مما يرسله المتصفح
    log_id = db.log_audit_event(user_name=user.get("name", ""), user_role=user["role"], action=audit.action,
                                target_type=audit.target_type or "", target_id=audit.target_id or "",
                                details=audit.details or "")
    return {"id": log_id, "status": "success"}


@app.get("/api/stats")
def get_dashboard_stats(user: dict = Depends(require(*CASE_ROLES))):
    conn = db.get_connection()
    c = conn.cursor()
    total_students = c.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    total_referrals = c.execute("SELECT COUNT(*) FROM referrals").fetchone()[0]
    pending_referrals = c.execute("SELECT COUNT(*) FROM referrals WHERE status = 'pending'").fetchone()[0]
    resolved_referrals = c.execute("SELECT COUNT(*) FROM referrals WHERE status = 'resolved'").fetchone()[0]

    today_str = db.now_riyadh().strftime("%Y-%m-%d")
    today_absences = c.execute("SELECT COUNT(*) FROM attendance WHERE date = ? AND type = 'absence'", (today_str,)).fetchone()[0]
    today_tardies = c.execute("SELECT COUNT(*) FROM attendance WHERE date = ? AND type = 'tardy'", (today_str,)).fetchone()[0]

    repeat_row = c.execute("""
    SELECT COUNT(DISTINCT student_id) FROM (
        SELECT student_id,
               SUM(CASE WHEN type = 'absence' AND has_excuse = 0 THEN 1 ELSE 0 END) as unexcused_absences,
               SUM(CASE WHEN type = 'tardy' THEN 1 ELSE 0 END) as tardies
        FROM attendance GROUP BY student_id
    ) t WHERE unexcused_absences >= 3 OR tardies >= 3""").fetchone()
    repeat_offenders_count = repeat_row[0] if repeat_row else 0

    pending_counselor_cases = c.execute("SELECT COUNT(*) FROM counselor_cases WHERE status != 'completed'").fetchone()[0]
    overdue_counselor_cases = c.execute(
        "SELECT COUNT(*) FROM counselor_cases WHERE status != 'completed' AND due_date IS NOT NULL AND due_date < ?",
        (today_str,)).fetchone()[0]

    top_behaviors = [dict(r) for r in c.execute(
        "SELECT behavior_name, COUNT(*) as count FROM referrals GROUP BY behavior_name ORDER BY count DESC LIMIT 5").fetchall()]
    conn.close()
    return {
        "total_students": total_students, "total_referrals": total_referrals,
        "pending_referrals": pending_referrals, "resolved_referrals": resolved_referrals,
        "today_absences": today_absences, "today_tardies": today_tardies,
        "repeat_offenders_count": repeat_offenders_count, "pending_counselor_cases": pending_counselor_cases,
        "overdue_counselor_cases": overdue_counselor_cases, "top_behaviors": top_behaviors
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(default="")):
    if not verify_token(token):
        await websocket.close(code=4401)
        return
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


# =========================================================================
# الجدول المعتمد (خط أحمر) وبيانات المعلمين
# =========================================================================
@app.get("/api/school-structure")
def school_structure(user: dict = Depends(require(*ALL_ROLES))):
    return {**SCHOOL_STRUCTURE, "timetable_locked": TIMETABLE_LOCKED}


@app.get("/api/timetable")
def get_saved_timetable(user: dict = Depends(require(*ALL_ROLES))):
    return db.get_timetable()


@app.get("/api/timetable/integrity")
def timetable_integrity(user: dict = Depends(require(*ADMIN_ROLES))):
    return {"locked": TIMETABLE_LOCKED, "matches_canonical": db.timetable_matches_canonical(),
            "pending_repo_update": db.get_document("timetable_pending_repo_update", None)}


@app.get("/api/timetable/validate")
def timetable_validate(user: dict = Depends(require(*ADMIN_ROLES))):
    """تقرير الجدول على قواعد المدرسة: المخالفات، الشعب الناقصة، التعارضات، فروقات النصاب."""
    return timetable_rules.validate(db.get_timetable(), _read_teachers(), SCHOOL_STRUCTURE)


@app.get("/api/timetable/sections/{section_id}")
def timetable_section(section_id: int, user: dict = Depends(require(*ALL_ROLES))):
    if section_id not in {int(x["id"]) for x in SCHOOL_STRUCTURE["sections"]}:
        raise HTTPException(status_code=404, detail="الشعبة غير موجودة")
    return {"section": next(x for x in SCHOOL_STRUCTURE["sections"] if int(x["id"]) == section_id),
            "schedule": timetable_rules.section_schedule(db.get_timetable(), _read_teachers(), section_id, SCHOOL_STRUCTURE)}


DAYS = timetable_rules.day_names(SCHOOL_STRUCTURE)


@app.post("/api/timetable")
async def save_timetable(matrix: dict = Body(...), user: dict = Depends(require("principal", "vp"))):
    if TIMETABLE_LOCKED:
        raise HTTPException(status_code=423, detail="الجدول المعتمد مقفل ضد التعديل بقرار إداري")
    teacher_ids = {str(t.get("id")) for t in _read_teachers()}
    if teacher_ids and not teacher_ids <= set(map(str, matrix.keys())):
        raise HTTPException(status_code=400, detail="الجدول المرسل ناقص (لا يشمل جميع المعلمين)")
    width = int(SCHOOL_STRUCTURE.get("max_periods", 7))
    cleaned = {}
    for tid, days in matrix.items():
        if not isinstance(days, dict):
            raise HTTPException(status_code=400, detail="صيغة الجدول غير صحيحة")
        cleaned[clean_name(tid, 60)] = {
            d: ([clean_name(c, 60) or "" for c in (days.get(d) or [])] + [""] * width)[:width]
            for d in DAYS
        }
    report = timetable_rules.validate(cleaned, _read_teachers(), SCHOOL_STRUCTURE)
    if report["errors"]:
        raise HTTPException(status_code=400, detail="الجدول يخالف قواعد الدوام: " + " | ".join(e["msg"] for e in report["errors"][:5]))
    if backup_service:
        backup_service.create_backup(reason="pre_timetable_change")
    db.set_document("timetable", cleaned)
    db.log_audit_event(user.get("name", ""), user["role"], "timetable_change", "timetable", "", "")
    return {"status": "success", "message": "تم حفظ الجدول", "warnings": len(report["warnings"])}


@app.get("/api/teachers-list")
def get_saved_teachers(user: dict = Depends(require(*ALL_ROLES))):
    teachers = _read_teachers()
    if user["role"] != "principal":
        teachers = [{k: v for k, v in t.items() if k != "pin"} for t in teachers]
    return teachers


@app.post("/api/teachers-list")
async def save_teachers_to_disk(teachers: List[dict] = Body(...), user: dict = Depends(require(*ADMIN_ROLES))):
    existing = {str(t.get("id")): t for t in _read_teachers()}
    if existing and len(teachers) < len(existing):
        raise HTTPException(status_code=400, detail="لا يمكن حذف معلمين من القائمة المعتمدة")
    merged = []
    for t in teachers:
        if not isinstance(t, dict) or "id" not in t:
            raise HTTPException(status_code=400, detail="صيغة بيانات المعلمين غير صحيحة")
        old = existing.get(str(t["id"]), {})
        item = {
            "id": t["id"],
            "name": clean_name(t.get("name", old.get("name", ""))) or old.get("name", ""),
            "subject": clean_name(t.get("subject", old.get("subject", ""))) or old.get("subject", ""),
            "load": old.get("load", t.get("load")),             # النصاب من الجدول المعتمد
            "pin": old.get("pin", str(1000 + int(t["id"]))),     # الرموز المعتمدة لا تتغير عبر الواجهة
            "phone": clean_name(t.get("phone", old.get("phone", "")), 20),
        }
        merged.append(item)
    # الاسم والمادة إن خالفا الملف المعتمد يُحفظان كتعديل للمدرسة حتى لا يُستبدلا عند إعادة التشغيل
    repo = {str(t.get("id")): t for t in db.get_repo_teachers()}
    overrides = {}
    for m in merged:
        base = repo.get(str(m["id"]), {})
        diff = {k: m[k] for k in ("name", "subject") if m[k] != base.get(k)}
        if diff:
            overrides[str(m["id"])] = diff
    db.set_document("teacher_overrides", overrides)
    db.set_document("teachers", merged)
    conn = db.get_connection()
    try:
        db.sync_teachers_table(conn)
    finally:
        conn.close()
    return {"status": "success", "message": "تم حفظ بيانات المعلمين"}


# =========================================================================
# سجل حصص الانتظار المشترك (بدلاً من حفظه في متصفح كل جهاز)
# =========================================================================
@app.get("/api/waiting")
def get_waiting(user: dict = Depends(require(*ALL_ROLES))):
    rows = db.list_waiting_records()
    if user["role"] == "teacher":
        rows = [r for r in rows if user.get("name") and user["name"] in (r.get("assignedTeacher") or "")]
    return rows


@app.post("/api/waiting")
def upsert_waiting(item: WaitingItem, user: dict = Depends(require(*ADMIN_ROLES))):
    data = item.model_dump()
    if (data.get("status") or "assigned") != "cancelled" and not data.get("force"):
        conflict = db.find_waiting_conflict(data)
        if conflict:
            raise HTTPException(status_code=409, detail=f"المعلم {data['assignedTeacher']} مكلف مسبقاً بانتظار في نفس اليوم والحصة")
    saved = db.upsert_waiting_record(data)
    db.log_audit_event(user.get("name", ""), user["role"], "waiting_upsert", "waiting", str(data["id"]), data.get("status") or "")
    return saved


# =========================================================================
# غياب المعلمين اليومي وقواعد توزيع الانتظار
# =========================================================================
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TeacherAbsences(BaseModel):
    date: str
    teachers: List[str] = []


class WaitingRules(BaseModel):
    maxDaily: int = 5
    maxWaitingPerDay: int = 2
    preferSameSubject: bool = True
    exempt: List[str] = []


WAITING_RULES_DEFAULT = WaitingRules().model_dump()


@app.get("/api/teacher-absences")
def get_teacher_absences(date: str = "", user: dict = Depends(require(*ADMIN_ROLES))):
    day = date if _DATE_RE.match(date or "") else db.now_riyadh().strftime("%Y-%m-%d")
    return {"date": day, "teachers": (db.get_document("teacher_absences", {}) or {}).get(day, [])}


@app.post("/api/teacher-absences")
def save_teacher_absences(body: TeacherAbsences, user: dict = Depends(require(*ADMIN_ROLES))):
    if not _DATE_RE.match(body.date):
        raise HTTPException(status_code=400, detail="تاريخ غير صحيح")
    known = {t.get("name") for t in _read_teachers()}
    names = list(dict.fromkeys(clean_name(n) for n in body.teachers if clean_name(n) in known))
    data = db.get_document("teacher_absences", {}) or {}
    if names:
        data[body.date] = names
    else:
        data.pop(body.date, None)
    # يُكتفى بآخر 400 يوم
    for old in sorted(data)[:-400]:
        data.pop(old, None)
    db.set_document("teacher_absences", data)
    db.log_audit_event(user.get("name", ""), user["role"], "teacher_absences", "absences", body.date, str(len(names)))
    return {"date": body.date, "teachers": names}


@app.get("/api/waiting-rules")
def get_waiting_rules(user: dict = Depends(require(*ALL_ROLES))):
    return {**WAITING_RULES_DEFAULT, **(db.get_document("waiting_rules", {}) or {})}


@app.post("/api/waiting-rules")
def save_waiting_rules(rules: WaitingRules, user: dict = Depends(require(*ADMIN_ROLES))):
    known = {t.get("name") for t in _read_teachers()}
    data = {
        "maxDaily": max(3, min(7, rules.maxDaily)),
        "maxWaitingPerDay": max(1, min(4, rules.maxWaitingPerDay)),
        "preferSameSubject": bool(rules.preferSameSubject),
        "exempt": [n for n in dict.fromkeys(rules.exempt) if n in known],
    }
    db.set_document("waiting_rules", data)
    return data


# =========================================================================
# النسخ الاحتياطي
# =========================================================================
@app.get("/api/backups")
def get_backups(user: dict = Depends(require(*ADMIN_ROLES))):
    return backup_service.list_backups() if backup_service else []


@app.post("/api/backups")
def create_new_backup(user: dict = Depends(require(*ADMIN_ROLES))):
    if backup_service:
        return backup_service.create_backup(reason="manual")
    return {"status": "error", "message": "خدمة النسخ غير مفعلة"}


@app.get("/api/backups/{filename}/download")
def download_backup_file(filename: str, request: Request, token: str = Query(default="")):
    # روابط التنزيل لا تستطيع إرسال ترويسة Authorization، لذلك يُقبل الرمز عبر الرابط هنا فقط
    auth = request.headers.get("authorization", "")
    tok = auth[7:] if auth.lower().startswith("bearer ") else token
    user = verify_token(tok) if tok else None
    if not user:
        raise HTTPException(status_code=401, detail="يرجى تسجيل الدخول")
    if user["role"] not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="لا تملك صلاحية لهذا الإجراء")
    if not backup_service:
        raise HTTPException(status_code=404, detail="الخدمة غير متوفرة")
    safe_name = os.path.basename(filename)
    if not (safe_name.startswith("backup_") and safe_name.endswith(".zip")):
        raise HTTPException(status_code=400, detail="اسم ملف غير صالح")
    data = backup_service.get_backup_bytes(safe_name)
    if data is None:
        raise HTTPException(status_code=404, detail="الملف غير موجود")
    from fastapi.responses import Response
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{safe_name}"'})


@app.post("/api/backups/{filename}/restore")
def restore_backup_file(filename: str, user: dict = Depends(require("principal"))):
    if not backup_service:
        raise HTTPException(status_code=500, detail="الخدمة غير متوفرة")
    try:
        result = backup_service.restore_backup(filename)
        db.log_audit_event(user.get("name", ""), user["role"], "backup_restore", "backup", os.path.basename(filename), "")
        return result
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="فشل استعادة النسخة")


@app.post("/api/backups/upload")
async def upload_and_restore_backup(file: UploadFile = File(...), user: dict = Depends(require("principal"))):
    if not backup_service:
        raise HTTPException(status_code=500, detail="الخدمة غير متوفرة")
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="يرجى رفع ملف بصيغة zip")
    contents = await file.read(backup_service.MAX_UPLOAD_BYTES + 1)
    try:
        if len(contents) > backup_service.MAX_UPLOAD_BYTES:
            raise ValueError("حجم الملف أكبر من 50MB")
        name = backup_service.save_uploaded_backup(file.filename, contents)
        result = backup_service.restore_backup(name)
        db.log_audit_event(user.get("name", ""), user["role"], "backup_upload_restore", "backup", name, "")
        return result
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=f"فشل استعادة النسخة: {e}")
    except Exception:
        raise HTTPException(status_code=500, detail="فشل استعادة النسخة")


# =========================================================================
# الملفات الثابتة والصفحة الرئيسية
# =========================================================================
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.api_route("/healthz", methods=["GET", "HEAD"])
def healthz():
    return {"ok": True}


@app.get("/api/system/status")
def system_status(user: dict = Depends(require(*ADMIN_ROLES))):
    persistent = db.IS_PG or bool(os.environ.get("DATA_DIR"))
    return {"database": db.backend_name(), "persistent": persistent,
            "timetable_locked": TIMETABLE_LOCKED, "matches_canonical": db.timetable_matches_canonical()}


@app.api_route("/", methods=["GET", "HEAD"])
def serve_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file, headers={"Cache-Control": "no-cache"})
    return {"message": "نظام متابعة الطلاب قيد التشغيل"}
