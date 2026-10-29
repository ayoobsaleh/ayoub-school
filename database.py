import sqlite3
import os
import re
import json
import shutil
import hashlib
from datetime import datetime, timezone, timedelta

# =========================================================================
# اختيار قاعدة البيانات
#   - DATABASE_URL (postgresql://...) ⇒ PostgreSQL دائمة (موصى به على Render: Neon أو Render Postgres)
#   - بدونه ⇒ SQLite في DATA_DIR (للتشغيل المحلي، أو مع قرص دائم على Render)
# =========================================================================
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", APP_DIR)
DB_PATH = os.path.join(DATA_DIR, "school.db")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
IS_PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))

# ملفات الجدول والمعلمين في المستودع = المصدر المعتمد (يُبذر منها جدول المستندات في القاعدة)
TIMETABLE_SEED_FILE = os.path.join(APP_DIR, "school_timetable_saved.json")
TEACHERS_SEED_FILE = os.path.join(APP_DIR, "school_teachers_saved.json")
# للتوافق مع الكود القديم
TIMETABLE_FILE = TIMETABLE_SEED_FILE
TEACHERS_FILE = TEACHERS_SEED_FILE

# توقيت المدرسة الرسمي (الرياض UTC+3) بدلاً من توقيت الخادم (UTC على Render)
RIYADH_TZ = timezone(timedelta(hours=3))


def now_riyadh():
    return datetime.now(RIYADH_TZ).replace(tzinfo=None)


def now_str():
    return now_riyadh().strftime("%Y-%m-%d %H:%M:%S")


def backend_name():
    return "PostgreSQL" if IS_PG else "SQLite"


def bootstrap_data_dir():
    """تجهيز مجلد البيانات المحلي (SQLite والنسخ المؤقتة)."""
    os.makedirs(DATA_DIR, exist_ok=True)


# قائمة السلوكيات (لائحة قواعد السلوك والمواظبة)
BEHAVIOR_TYPES = [
    # الدرجة الأولى (مخالفات بسيطة)
    ("العرقلة غير المتعمدة لسير الحصة (كالتحدث بدون إذن)", "الدرجة الأولى", 1, 1, "عرقلة سير الدرس أو إزعاج الزملاء دون قصد الإفساد"),
    ("النوم أو الاسترخاء أثناء الدرس", "الدرجة الأولى", 1, 1, "عدم الانتباه وتكرار النوم في الحصة"),
    ("عدم إحضار الكتب والأدوات المدرسية", "الدرجة الأولى", 1, 1, "تكرار إهمال المستلزمات المدرسية"),
    ("تناول الأطعمة والمشروبات أثناء الدرس", "الدرجة الأولى", 1, 1, "الأكل أو الشرب أثناء وقت الشرح"),

    # الدرجة الثانية
    ("استخدام الهاتف المحمول داخل الفصل دون إذن", "الدرجة الثانية", 2, 2, "تشغيل الجوال أو العبث به في وقت الحصة"),
    ("الهروب من الحصة الدراسية", "الدرجة الثانية", 2, 2, "مغادرة الفصل دون استئذان المعلم"),
    ("العبث بممتلكات المدرسة أو ممتلكات الزملاء", "الدرجة الثانية", 2, 2, "الكتابة على الطاولات أو إتلاف أدوات الفصل"),
    ("التلفظ بألفاظ غير لائقة على الزملاء", "الدرجة الثانية", 2, 2, "استخدام كلمات غير مقبولة تجاه أحد الطلاب"),

    # الدرجة الثالثة
    ("الشجار أو الاشتباك بالأيدي مع الزملاء", "الدرجة الثالثة", 3, 3, "عراك جسدي أو تبادل ضرب داخل الفصل أو الساحة"),
    ("التنمر أو الاستهزاء المتكرر بأحد الطلاب", "الدرجة الثالثة", 3, 3, "ممارسة سلوك عدواني أو تهكمي متكرر"),
    ("مغادرة المدرسة دون إذن رسمي (الهروب من المدرسة)", "الدرجة الثالثة", 3, 3, "الخروج من أسوار المدرسة أثناء اليوم الدراسي"),
    ("تصوير الطلاب أو المعلمين بالأجهزة الذكية", "الدرجة الثالثة", 3, 4, "استخدام الكاميرا وتصوير أي شخص دون إذن رسمي"),

    # الدرجة الرابعة
    ("التطاول اللفظي أو الإساءة لأحد منسوبي المدرسة", "الدرجة الرابعة", 4, 10, "عدم احترام المعلم أو موظف المدرسة والتلفظ عليه"),
    ("تعمد إتلاف تجهيزات المدرسة (كأجهزة الحاسب أو المكيفات)", "الدرجة الرابعة", 4, 8, "تخريب متعمد لمرافق المدرسة"),
    ("إشعال الألعاب النارية أو إحضار أدوات خطرة", "الدرجة الرابعة", 4, 10, "حيازة أو استخدام أي مادة تهدد سلامة المدرسة"),

    # مخالفات المواظبة
    ("التأخر الصباحي المتكرر عن الطابور والحصة الأولى", "مخالفة مواظبة", 0, 1, "تكرار التأخر الصباحي دون عذر مقبول"),
    ("الغياب المتكرر بدون عذر رسمي", "مخالفة مواظبة", 0, 2, "غياب أيام متفرقة أو متصلة دون تقديم عذر")
]


# =========================================================================
# طبقة توافق: نفس واجهة sqlite3 (execute / fetchone / fetchall / lastrowid / row[0] / dict(row))
# فوق PostgreSQL، حتى تبقى كل دوال النظام كما هي.
# =========================================================================
class Row(dict):
    """صف يُقرأ بالاسم أو بالرقم، مثل sqlite3.Row."""
    __slots__ = ("_vals",)

    def __init__(self, names, values):
        super().__init__(zip(names, values))
        self._vals = values

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._vals[key]
        return super().__getitem__(key)

    def keys(self):
        return super().keys()


NO_ID_TABLES = {"app_documents"}


def _pg_sql(sql):
    # % حرفي ⇒ %% ثم ? ⇒ %s (لا توجد علامات ? حرفية في استعلامات النظام)
    return sql.replace("%", "%%").replace("?", "%s")


class PGCursor:
    def __init__(self, raw):
        self._c = raw
        self.lastrowid = None

    def execute(self, sql, params=()):
        q = _pg_sql(sql)
        m = re.match(r"\s*INSERT\s+INTO\s+(\w+)", q, re.I)
        wants_id = bool(m) and m.group(1).lower() not in NO_ID_TABLES and " RETURNING " not in q.upper()
        if wants_id:
            q = q.rstrip().rstrip(";") + " RETURNING id"
        self._c.execute(q, tuple(params) if params else None)
        if wants_id:
            r = self._c.fetchone()
            self.lastrowid = r[0] if r else None
        return self

    def executemany(self, sql, seq):
        self._c.executemany(_pg_sql(sql), [tuple(p) for p in seq])
        return self

    def fetchone(self):
        return self._c.fetchone()

    def fetchall(self):
        return self._c.fetchall()

    def __iter__(self):
        return iter(self._c.fetchall())


class PGConnection:
    def __init__(self):
        import psycopg
        self._conn = psycopg.connect(DATABASE_URL, connect_timeout=15)

        def factory(cursor):
            names = [d.name for d in (cursor.description or [])]
            return lambda values: Row(names, values)
        self._conn.row_factory = factory

    def cursor(self):
        return PGCursor(self._conn.cursor())

    def execute(self, sql, params=()):
        return self.cursor().execute(sql, params)

    def executemany(self, sql, seq):
        return self.cursor().executemany(sql, seq)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass


def get_connection():
    if IS_PG:
        return PGConnection()
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def table_columns(conn, table):
    if IS_PG:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ? AND table_schema = current_schema()",
            (table,)).fetchall()
        return [r[0] for r in rows]
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


# =========================================================================
# المخطط (واحد للقاعدتين؛ الاختلاف في نوع المفتاح وقيمة الوقت الافتراضية فقط)
# =========================================================================
TABLES = ["students", "behavior_types", "referrals", "teachers", "attendance", "counselor_cases",
          "guardian_communications", "waiting_records", "audit_logs", "app_documents"]


def _schema():
    ID = "SERIAL PRIMARY KEY" if IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    NOW = ("TEXT DEFAULT (to_char(now() AT TIME ZONE 'Asia/Riyadh', 'YYYY-MM-DD HH24:MI:SS'))" if IS_PG
           else "TIMESTAMP DEFAULT (datetime('now', '+3 hours'))")
    TS = "TEXT"
    return [
        f"""CREATE TABLE IF NOT EXISTS students (
            id {ID}, name TEXT NOT NULL, national_id TEXT, grade TEXT NOT NULL, classroom TEXT NOT NULL,
            guardian_phone TEXT, created_at {NOW})""",
        f"""CREATE TABLE IF NOT EXISTS behavior_types (
            id {ID}, name TEXT NOT NULL, degree TEXT NOT NULL, degree_level INTEGER DEFAULT 1,
            deduction_points INTEGER DEFAULT 1, description TEXT)""",
        f"""CREATE TABLE IF NOT EXISTS referrals (
            id {ID}, student_id INTEGER NOT NULL, teacher_name TEXT NOT NULL, subject TEXT, period TEXT,
            behavior_id INTEGER, behavior_name TEXT NOT NULL, behavior_degree TEXT NOT NULL, notes TEXT,
            status TEXT DEFAULT 'pending', action_taken TEXT, action_notes TEXT, action_date {TS},
            created_at {NOW})""",
        f"""CREATE TABLE IF NOT EXISTS teachers (id {ID}, name TEXT NOT NULL, subject TEXT)""",
        f"""CREATE TABLE IF NOT EXISTS attendance (
            id {ID}, student_id INTEGER NOT NULL, date TEXT NOT NULL, type TEXT NOT NULL,
            period TEXT DEFAULT 'اليوم كامل', minutes_late INTEGER DEFAULT 0, has_excuse INTEGER DEFAULT 0,
            excuse_notes TEXT, guardian_notified INTEGER DEFAULT 0, action_taken TEXT, created_at {NOW})""",
        f"""CREATE TABLE IF NOT EXISTS counselor_cases (
            id {ID}, student_id INTEGER NOT NULL, referral_id INTEGER, reason TEXT NOT NULL,
            referred_by TEXT DEFAULT 'وكيل شؤون الطلاب', referred_to TEXT DEFAULT 'الموجه الطلابي',
            referral_date TEXT NOT NULL, due_date TEXT, status TEXT DEFAULT 'new', required_action TEXT,
            intervention_plan TEXT, outcome TEXT, notes TEXT, created_at {NOW})""",
        f"""CREATE TABLE IF NOT EXISTS guardian_communications (
            id {ID}, student_id INTEGER NOT NULL, referral_id INTEGER, attendance_id INTEGER,
            comm_type TEXT NOT NULL, phone TEXT, message_content TEXT, result_status TEXT DEFAULT 'تم الإرسال',
            created_at {NOW})""",
        f"""CREATE TABLE IF NOT EXISTS waiting_records (
            id {ID}, assignment_id TEXT, teacher_name TEXT NOT NULL, absent_teacher TEXT NOT NULL,
            day TEXT NOT NULL, period TEXT NOT NULL, classroom TEXT NOT NULL, status TEXT DEFAULT 'assigned',
            selection_reason TEXT, executed_at {TS}, notes TEXT, created_at {NOW}, assign_date TEXT)""",
        f"""CREATE TABLE IF NOT EXISTS audit_logs (
            id {ID}, user_name TEXT NOT NULL, user_role TEXT NOT NULL, action TEXT NOT NULL,
            target_type TEXT, target_id TEXT, details TEXT, created_at {NOW})""",
        # مستندات النظام: الجدول، المعلمون، بصمة النسخة المعتمدة… (بدلاً من ملفات على قرص قد يُمسح)
        f"""CREATE TABLE IF NOT EXISTS app_documents (
            key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at {NOW})""",
        # النسخ الاحتياطية داخل القاعدة نفسها (تبقى ما دامت القاعدة باقية)
        f"""CREATE TABLE IF NOT EXISTS backups (
            id {ID}, filename TEXT NOT NULL, reason TEXT, meta TEXT, data TEXT NOT NULL, created_at {NOW})""",
    ]


def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    for ddl in _schema():
        cursor.execute(ddl)

    # ترقية قاعدة SQLite قديمة: عمود تاريخ التكليف في سجل الانتظار
    if "assign_date" not in table_columns(conn, "waiting_records"):
        cursor.execute("ALTER TABLE waiting_records ADD COLUMN assign_date TEXT")

    # فهارس لتسريع الاستعلامات الأكثر تكراراً
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_att_date ON attendance(date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_att_student ON attendance(student_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ref_student ON referrals(student_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ref_status ON referrals(status)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_wait_assignment ON waiting_records(assignment_id)")
    conn.commit()

    # المستندات المعتمدة (الجدول والمعلمون) ثم البيانات المرجعية
    sync_documents_from_repo(conn)
    seed_reference_data(conn)
    # بيانات تجريبية وهمية فقط عند الطلب الصريح (SEED_DEMO=1) — لا تُخلط مع بيانات المدرسة الحقيقية
    if os.environ.get("SEED_DEMO") == "1":
        seed_sample_data(conn)
    conn.close()


# =========================================================================
# المستندات: الجدول المعتمد والمعلمون محفوظون في القاعدة
# =========================================================================
def _sha(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def get_document(key, default=None, conn=None):
    own = conn is None
    conn = conn or get_connection()
    try:
        row = conn.execute("SELECT value FROM app_documents WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default
    finally:
        if own:
            conn.close()


def set_document(key, value, conn=None):
    own = conn is None
    conn = conn or get_connection()
    try:
        conn.execute(
            """INSERT INTO app_documents (key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
            (key, json.dumps(value, ensure_ascii=False), now_str()))
        conn.commit()
    finally:
        if own:
            conn.close()


def _read_json_file(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def sync_documents_from_repo(conn):
    """
    يبذر الجدول والمعلمين من ملفات المستودع المعتمدة عند أول تشغيل.
    وعند تحديث الملفات المعتمدة في المستودع (جدول مصحّح بقرار المدرسة):
      - إن لم يُعدَّل الجدول داخل النظام ⇒ يُستبدل بالنسخة المعتمدة الجديدة.
      - إن عُدِّل داخل النظام ⇒ يبقى كما هو ويُسجّل تنبيه للمدير (لا ضياع لأي تعديل).
    المعلمون: الاسم والمادة والنصاب والرمز من المستودع، والجوال يبقى كما أدخلته المدرسة.
    """
    repo_tt = _read_json_file(TIMETABLE_SEED_FILE, {})
    repo_teachers = _read_json_file(TEACHERS_SEED_FILE, [])

    if repo_tt:
        repo_sha = _sha(repo_tt)
        current = get_document("timetable", None, conn)
        canon_sha = get_document("timetable_canonical_sha", None, conn)
        if current is None:
            set_document("timetable", repo_tt, conn)
            set_document("timetable_canonical_sha", repo_sha, conn)
        elif canon_sha != repo_sha:
            if _sha(current) == canon_sha or canon_sha is None and _sha(current) == repo_sha:
                set_document("timetable", repo_tt, conn)
                set_document("timetable_pending_repo_update", None, conn)
            else:
                set_document("timetable_pending_repo_update", {"repo_sha": repo_sha, "at": now_str()}, conn)
            set_document("timetable_canonical_sha", repo_sha, conn)

    if repo_teachers:
        current = get_document("teachers", None, conn)
        if current is None:
            set_document("teachers", repo_teachers, conn)
        else:
            phones = {str(t.get("id")): t.get("phone", "") for t in current}
            merged = [dict(t, phone=phones.get(str(t.get("id")), t.get("phone", ""))) for t in repo_teachers]
            if merged != current:
                set_document("teachers", merged, conn)


def get_timetable():
    return get_document("timetable", {}) or {}


def get_teachers_list():
    return get_document("teachers", []) or []


def get_canonical_timetable():
    return _read_json_file(TIMETABLE_SEED_FILE, {})


def timetable_matches_canonical():
    return _sha(get_timetable()) == _sha(get_canonical_timetable())


def sync_teachers_table(conn):
    """جدول teachers في القاعدة = نسخة من قائمة المعلمين المعتمدة."""
    official = get_document("teachers", [], conn) or []
    rows = sorted((int(t["id"]), t.get("name", ""), t.get("subject", "")) for t in official if "id" in t)
    if not rows:
        return
    cursor = conn.cursor()
    current = [tuple(r) for r in cursor.execute("SELECT id, name, subject FROM teachers ORDER BY id").fetchall()]
    if current != rows:
        cursor.execute("DELETE FROM teachers")
        cursor.executemany("INSERT INTO teachers (id, name, subject) VALUES (?, ?, ?)", rows)
        conn.commit()


def seed_reference_data(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM behavior_types")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("""
        INSERT INTO behavior_types (name, degree, degree_level, deduction_points, description)
        VALUES (?, ?, ?, ?, ?)
        """, BEHAVIOR_TYPES)
        conn.commit()
    sync_teachers_table(conn)


def seed_sample_data(conn):
    """بيانات وهمية للعرض والتجربة فقط (SEED_DEMO=1)."""
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM students")
    if cursor.fetchone()[0] > 0:
        return  # البيانات موجودة مسبقاً

    # (المعلمون الوهميون السابقون أُزيلوا: جدول المعلمين يُبنى من القائمة المعتمدة)

    # قائمة بالطلاب (عينات واقعية لفصول ومراحل متعددة)
    students = [
        ("سعد بن مشعل الشمري", "1098234123", "أول ثانوي", "1/1", "0501112233"),
        ("ريان بن نايف المطيري", "1098234124", "أول ثانوي", "1/1", "0502223344"),
        ("عمر بن خالد الدوسري", "1098234125", "أول ثانوي", "1/2", "0503334455"),
        ("عبدالله بن يوسف القحطاني", "1098234126", "أول ثانوي", "1/2", "0504445566"),
        ("فيصل بن سلطان العتيبي", "1098234127", "أول ثانوي", "1/3", "0505556677"),
        ("محمد بن أحمد الغامدي", "1087123456", "ثاني ثانوي", "2/1", "0506667788"),
        ("يزيد بن فهد العنزي", "1087123457", "ثاني ثانوي", "2/1", "0507778899"),
        ("بندر بن صالح الشهري", "1087123458", "ثاني ثانوي", "2/2", "0508889900"),
        ("عبدالعزيز بن ناصر القرني", "1087123459", "ثاني ثانوي", "2/2", "0551113355"),
        ("فهد بن نواف الحربي", "1076987651", "ثالث ثانوي", "3/1", "0552224466"),
        ("تركي بن سليمان الخالدي", "1076987652", "ثالث ثانوي", "3/1", "0553335577"),
        ("سلمان بن مبارك الزهراني", "1076987653", "ثالث ثانوي", "3/2", "0554446688"),
        ("خالد بن حمد السبيعي", "1076987654", "ثالث ثانوي", "3/2", "0555557799")
    ]
    cursor.executemany("""
    INSERT INTO students (name, national_id, grade, classroom, guardian_phone)
    VALUES (?, ?, ?, ?, ?)
    """, students)

    # إضافة إحالات سابقة تجريبية (لتوضيح الأرشيف للوكيل مباشرة عند التجربة)
    sample_referrals = [
        # إحالة منتهية للطالب سعد الشمري (أول ثانوي 1/1)
        (1, "أ. تركي بن صالح العتيبي", "العلوم", "الحصة الثانية", 5, "استخدام الهاتف المحمول داخل الفصل دون إذن", "الدرجة الثانية",
         "تم ضبط الطالب يصور مقطع فيديو لزملائه أثناء شرح الدرس بعد تنبيهه مرتين.", "resolved",
         "تم استدعاء ولي الأمر وتوقيع تعهد خطي على الطالب بمصادرة الجهاز حتى نهاية الفصل الدراسي.",
         "حضر والد الطالب وتم التفاهم معه وإحالة الطالب للموجه الطلابي لمتابعة حالته.",
         "2026-10-18 10:30:00", "2026-10-18 09:15:00"),

        # إحالة قديمة أخرى لنفس الطالب (تظهر في الأرشيف)
        (1, "أ. فهد بن عبدالله المطيري", "لغتي الخالدة", "الحصة الأولى", 1, "العرقلة غير المتعمدة لسير الحصة (كالتحدث بدون إذن)", "الدرجة الأولى",
         "تكرار مقاطعة الدرس والحديث الجانبي مع زميله ريان.", "resolved",
         "توجيه وتنبيه خطي من الوكيل مع تغيير المقعد داخل الفصل.",
         "تم التواصل مع ولي الأمر هاتفياً وإشعاره بالملاحظة.",
         "2026-10-10 08:45:00", "2026-10-10 08:00:00"),

        # إحالة قيد المعالجة للطالب فهد الحربي (ثالث ثانوي 3/1)
        (10, "أ. عبدالعزيز بن سالم الدوسري", "اللغة الإنجليزية", "الحصة الرابعة", 9, "الشجار أو الاشتباك بالأيدي مع الزملاء", "الدرجة الثالثة",
         "اشتبك الطالب مع أحد زملائه بسبب خلاف على الأدوات المدرسية وتبادل الصراخ والضرب.", "in_progress",
         "إحالة للموجه الطلابي لدراسة الحالة وطلب ولي الأمر غداً صباحاً.",
         "تم تهدئة الطرفين وفصلهما مؤقتاً.",
         "2026-10-21 11:20:00", "2026-10-21 10:45:00"),

        # إحالة جديدة بانتظار الإجراء للطالب عمر الدوسري (أول ثانوي 1/2)
        (3, "أ. خالد بن ناصر القحطاني", "الرياضيات", "الحصة الثالثة", 6, "الهروب من الحصة الدراسية", "الدرجة الثانية",
         "استأذن الطالب لدورة المياه ولم يعد حتى نهاية الحصة، ووجد في فناء المدرسة.", "pending",
         None, None, None, "2026-10-22 10:15:00")
    ]

    cursor.executemany("""
    INSERT INTO referrals (
        student_id, teacher_name, subject, period, behavior_id,
        behavior_name, behavior_degree, notes, status,
        action_taken, action_notes, action_date, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, sample_referrals)

    conn.commit()

# دوال العمليات (CRUD)

def get_all_students(search=""):
    conn = get_connection()
    cursor = conn.cursor()
    if search:
        search_term = f"%{search}%"
        cursor.execute("""
        SELECT * FROM students 
        WHERE name LIKE ? OR national_id LIKE ? OR grade LIKE ? OR classroom LIKE ?
        ORDER BY grade, classroom, name
        """, (search_term, search_term, search_term, search_term))
    else:
        cursor.execute("SELECT * FROM students ORDER BY grade, classroom, name")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_student_by_id(student_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students WHERE id = ?", (student_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_behaviors():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM behavior_types ORDER BY degree_level, name")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_teachers():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM teachers ORDER BY name")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def create_referral(data):
    conn = get_connection()
    cursor = conn.cursor()
    now_str = now_riyadh().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    INSERT INTO referrals (
        student_id, teacher_name, subject, period, behavior_id,
        behavior_name, behavior_degree, notes, status, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
    """, (
        data['student_id'],
        data['teacher_name'],
        data.get('subject', ''),
        data.get('period', ''),
        data.get('behavior_id'),
        data['behavior_name'],
        data['behavior_degree'],
        data.get('notes', ''),
        now_str
    ))
    ref_id = cursor.lastrowid
    conn.commit()

    # جلب تفاصيل الإحالة المنشأة مع معلومات الطالب
    cursor.execute("""
    SELECT r.*, s.name as student_name, s.grade, s.classroom, s.guardian_phone
    FROM referrals r
    JOIN students s ON r.student_id = s.id
    WHERE r.id = ?
    """, (ref_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_referrals(status=None, student_id=None):
    conn = get_connection()
    cursor = conn.cursor()
    query = """
    SELECT r.*, s.name as student_name, s.grade, s.classroom, s.guardian_phone
    FROM referrals r
    JOIN students s ON r.student_id = s.id
    """
    conditions = []
    params = []
    if status and status != 'all':
        conditions.append("r.status = ?")
        params.append(status)
    if student_id:
        conditions.append("r.student_id = ?")
        params.append(student_id)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY r.created_at DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_student_archive(student_id):
    """جلب الأرشيف الكامل للطالب متضمناً السجل التاريخي والإحصائيات"""
    conn = get_connection()
    cursor = conn.cursor()
    # معلومات الطالب
    cursor.execute("SELECT * FROM students WHERE id = ?", (student_id,))
    student = cursor.fetchone()
    if not student:
        conn.close()
        return None

    # كل إحالات الطالب السابقة والحالية
    cursor.execute("""
    SELECT r.*, b.deduction_points
    FROM referrals r
    LEFT JOIN behavior_types b ON r.behavior_id = b.id
    WHERE r.student_id = ?
    ORDER BY r.created_at DESC
    """, (student_id,))
    referrals = [dict(r) for r in cursor.fetchall()]

    # إحصائيات سريعة
    total_violations = len(referrals)
    pending_count = sum(1 for r in referrals if r['status'] == 'pending')
    resolved_count = sum(1 for r in referrals if r['status'] == 'resolved')
    in_progress_count = sum(1 for r in referrals if r['status'] == 'in_progress')
    total_points = sum((r.get('deduction_points') or 0) for r in referrals if r['status'] == 'resolved')

    conn.close()
    return {
        "student": dict(student),
        "referrals": referrals,
        "stats": {
            "total_violations": total_violations,
            "pending": pending_count,
            "resolved": resolved_count,
            "in_progress": in_progress_count,
            "total_deducted_points": total_points
        }
    }

def update_referral_action(ref_id, action_taken, action_notes, status="resolved"):
    conn = get_connection()
    cursor = conn.cursor()
    now_str = now_riyadh().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    UPDATE referrals
    SET action_taken = ?, action_notes = ?, status = ?, action_date = ?
    WHERE id = ?
    """, (action_taken, action_notes, status, now_str, ref_id))
    conn.commit()

    cursor.execute("""
    SELECT r.*, s.name as student_name, s.grade, s.classroom, s.guardian_phone
    FROM referrals r
    JOIN students s ON r.student_id = s.id
    WHERE r.id = ?
    """, (ref_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def add_student(name, national_id, grade, classroom, guardian_phone):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO students (name, national_id, grade, classroom, guardian_phone)
    VALUES (?, ?, ?, ?, ?)
    """, (name, national_id, grade, classroom, guardian_phone))
    student_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return student_id
# =========================================================================
# دوال سجل الحضور والغياب والتأخر اليومي (Attendance & Tardy Module)
# =========================================================================

def record_attendance(student_id, date_str, att_type, period="اليوم كامل", minutes_late=0, has_excuse=0, excuse_notes="", guardian_notified=0, action_taken=""):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO attendance (student_id, date, type, period, minutes_late, has_excuse, excuse_notes, guardian_notified, action_taken)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (student_id, date_str, att_type, period, minutes_late, has_excuse, excuse_notes, guardian_notified, action_taken))
    record_id = cursor.lastrowid
    conn.commit()

    cursor.execute("""
    SELECT a.*, s.name as student_name, s.grade, s.classroom, s.guardian_phone
    FROM attendance a
    JOIN students s ON a.student_id = s.id
    WHERE a.id = ?
    """, (record_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_daily_attendance(date_str=None):
    conn = get_connection()
    cursor = conn.cursor()
    if not date_str:
        date_str = now_riyadh().strftime("%Y-%m-%d")
    
    cursor.execute("""
    SELECT a.*, s.name as student_name, s.national_id, s.grade, s.classroom, s.guardian_phone
    FROM attendance a
    JOIN students s ON a.student_id = s.id
    WHERE a.date = ?
    ORDER BY a.type DESC, a.created_at DESC
    """, (date_str,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_repeat_attendance_offenders(threshold_days=3):
    """يكتشف الطلاب الذين تكرر لديهم الغياب أو التأخر لتنبيه الوكيل فوراً"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM (
        SELECT s.id, s.name, s.grade, s.classroom, s.guardian_phone,
               SUM(CASE WHEN a.type = 'absence' AND a.has_excuse = 0 THEN 1 ELSE 0 END) as unexcused_absences,
               SUM(CASE WHEN a.type = 'absence' AND a.has_excuse = 1 THEN 1 ELSE 0 END) as excused_absences,
               SUM(CASE WHEN a.type = 'tardy' THEN 1 ELSE 0 END) as total_tardies,
               COUNT(a.id) as total_incidents,
               MAX(a.date) as last_incident_date
        FROM students s
        JOIN attendance a ON s.id = a.student_id
        GROUP BY s.id, s.name, s.grade, s.classroom, s.guardian_phone
    ) t
    WHERE unexcused_absences >= ? OR total_tardies >= ?
    ORDER BY unexcused_absences DESC, total_tardies DESC
    """, (threshold_days, threshold_days))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

# =========================================================================
# الملف الإلكتروني الموحد للطالب والسجل الزمني (Unified Student Profile & Timeline)
# =========================================================================

def get_unified_student_profile(student_id):
    """
    يجمع الملف الشامل والموحد لكل طالب وفق متطلبات وكيل شؤون الطلاب:
    1. البيانات الأساسية.
    2. سجل الغياب والتأخر.
    3. سجل المخالفات والإحالات السلوكية وقرارات الوكالة.
    4. التحويلات للموجه الطلابي وخطط الرعاية.
    5. سجل التواصل مع ولي الأمر.
    6. سجل زمني موحد (Timeline) مرتب من الأحدث للأقدم.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM students WHERE id = ?", (student_id,))
    student_row = cursor.fetchone()
    if not student_row:
        conn.close()
        return None
    student = dict(student_row)

    # 1. سجل الحضور والغياب
    cursor.execute("""
    SELECT * FROM attendance
    WHERE student_id = ?
    ORDER BY date DESC, created_at DESC
    """, (student_id,))
    attendance_records = [dict(r) for r in cursor.fetchall()]

    # 2. سجل الإحالات والمخالفات
    cursor.execute("""
    SELECT r.*, b.deduction_points
    FROM referrals r
    LEFT JOIN behavior_types b ON r.behavior_id = b.id
    WHERE r.student_id = ?
    ORDER BY r.created_at DESC
    """, (student_id,))
    referrals = [dict(r) for r in cursor.fetchall()]

    # 3. سجل التحويلات للتوجيه الطلابي
    cursor.execute("""
    SELECT * FROM counselor_cases
    WHERE student_id = ?
    ORDER BY referral_date DESC, created_at DESC
    """, (student_id,))
    counselor_cases = [dict(r) for r in cursor.fetchall()]

    # 4. سجل التواصل مع ولي الأمر
    cursor.execute("""
    SELECT * FROM guardian_communications
    WHERE student_id = ?
    ORDER BY created_at DESC
    """, (student_id,))
    communications = [dict(r) for r in cursor.fetchall()]

    conn.close()

    # حساب درجات السلوك والمواظبة الحالية
    total_deducted = sum((r.get('deduction') or r.get('deduction_points') or 0) for r in referrals if r['status'] == 'resolved')
    unexcused_absences = sum(1 for a in attendance_records if a['type'] == 'absence' and not a['has_excuse'])
    attendance_deducted = unexcused_absences * 2 # 2 درجات لكل غياب بدون عذر
    current_behavior_score = max(0, 100 - total_deducted)
    current_attendance_score = max(0, 100 - attendance_deducted)

    # بناء السجل الزمني التراكمي الموحد (Timeline)
    timeline = []

    for a in attendance_records:
        timeline.append({
            "type": "attendance",
            "title": f"رصد {'تأخر صباحي (' + str(a['minutes_late']) + ' دقيقة)' if a['type'] == 'tardy' else 'غياب عن المدرسة (' + ('بعذر مقبول' if a['has_excuse'] else 'بدون عذر') + ')'}",
            "date": a['date'],
            "timestamp": a['created_at'],
            "details": a.get('excuse_notes') or a.get('action_taken') or "رصد الحضور اليومي",
            "status": "excused" if a['has_excuse'] else "unexcused",
            "icon": "⏰" if a['type'] == 'tardy' else "⚠️"
        })

    for r in referrals:
        timeline.append({
            "type": "referral",
            "title": f"إحالة سلوكية: {r['behavior_name']} ({r.get('behavior_degree', 'مخالفة')})",
            "date": r.get('created_at', '')[:10],
            "timestamp": r.get('created_at', ''),
            "details": f"المعلم المحيل: {r['teacher_name']} (الحصة {r.get('period', '-')}) - {r.get('notes', '')}",
            "action_taken": r.get('action_taken'),
            "action_notes": r.get('action_notes'),
            "status": r.get('status'),
            "icon": "📋"
        })

    for c in counselor_cases:
        timeline.append({
            "type": "counselor",
            "title": f"تحويل للموجه الطلابي: {c['reason']}",
            "date": c.get('referral_date', ''),
            "timestamp": c.get('created_at', ''),
            "details": f"الإجراء المطلوب: {c.get('required_action', '')} | الخطة: {c.get('intervention_plan', 'قيد الإعداد')}",
            "status": c.get('status'),
            "icon": "🌱"
        })

    for g in communications:
        timeline.append({
            "type": "communication",
            "title": f"تواصل مع ولي الأمر عبر {g['comm_type']}",
            "date": g.get('created_at', '')[:10],
            "timestamp": g.get('created_at', ''),
            "details": g.get('message_content', ''),
            "status": g.get('result_status', 'تم'),
            "icon": "📱"
        })

    # ترتيب الخط الزمني من الأحدث للأقدم
    timeline.sort(key=lambda x: str(x.get('timestamp') or x.get('date')), reverse=True)

    return {
        "student": student,
        "behavior_score": current_behavior_score,
        "attendance_score": current_attendance_score,
        "stats": {
            "total_referrals": len(referrals),
            # المفاتيح التي تقرؤها الواجهة (كانت تظهر "undefined" في ملف الطالب)
            "violations_count": len(referrals),
            "total_deductions": total_deducted,
            "unexcused_tardies": sum(1 for a in attendance_records if a['type'] == 'tardy' and not a['has_excuse']),
            "unexcused_absences": unexcused_absences,
            "excused_absences": sum(1 for a in attendance_records if a['type'] == 'absence' and a['has_excuse']),
            "total_tardies": sum(1 for a in attendance_records if a['type'] == 'tardy'),
            "counselor_cases": len(counselor_cases),
            "guardian_communications": len(communications)
        },
        "attendance_records": attendance_records,
        "referrals": referrals,
        "counselor_cases": counselor_cases,
        "communications": communications,
        "timeline": timeline
    }

# =========================================================================
# دوال التحويلات للموجه الطلابي (Counselor Cases & Referrals)
# =========================================================================

def create_counselor_case(student_id, reason, referral_id=None, referred_by="وكيل شؤون الطلاب", referred_to="الموجه الطلابي", due_date=None, required_action="", intervention_plan=""):
    conn = get_connection()
    cursor = conn.cursor()
    now_date = now_riyadh().strftime("%Y-%m-%d")
    cursor.execute("""
    INSERT INTO counselor_cases (student_id, referral_id, reason, referred_by, referred_to, referral_date, due_date, status, required_action, intervention_plan)
    VALUES (?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)
    """, (student_id, referral_id, reason, referred_by, referred_to, now_date, due_date, required_action, intervention_plan))
    case_id = cursor.lastrowid
    conn.commit()

    cursor.execute("""
    SELECT c.*, s.name as student_name, s.grade, s.classroom, s.guardian_phone
    FROM counselor_cases c
    JOIN students s ON c.student_id = s.id
    WHERE c.id = ?
    """, (case_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_counselor_cases_list(status=None):
    conn = get_connection()
    cursor = conn.cursor()
    if status and status != 'all':
        cursor.execute("""
        SELECT c.*, s.name as student_name, s.grade, s.classroom, s.guardian_phone
        FROM counselor_cases c
        JOIN students s ON c.student_id = s.id
        WHERE c.status = ?
        ORDER BY c.created_at DESC
        """, (status,))
    else:
        cursor.execute("""
        SELECT c.*, s.name as student_name, s.grade, s.classroom, s.guardian_phone
        FROM counselor_cases c
        JOIN students s ON c.student_id = s.id
        ORDER BY c.created_at DESC
        """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def update_counselor_case_status(case_id, status, intervention_plan="", outcome="", notes=""):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE counselor_cases
    SET status = ?, intervention_plan = COALESCE(NULLIF(?, ''), intervention_plan),
        outcome = COALESCE(NULLIF(?, ''), outcome), notes = COALESCE(NULLIF(?, ''), notes)
    WHERE id = ?
    """, (status, intervention_plan, outcome, notes, case_id))
    conn.commit()
    conn.close()
    return True

# =========================================================================
# دوال سجل التواصل مع أولياء الأمور وسجل التدقيق (Communications & Audit Logs)
# =========================================================================

def log_guardian_communication(student_id, comm_type, phone, message_content, referral_id=None, attendance_id=None, result_status="تم الإرسال"):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO guardian_communications (student_id, referral_id, attendance_id, comm_type, phone, message_content, result_status)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (student_id, referral_id, attendance_id, comm_type, phone, message_content, result_status))
    comm_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return comm_id

def log_audit_event(user_name, user_role, action, target_type="", target_id="", details=""):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO audit_logs (user_name, user_role, action, target_type, target_id, details)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (user_name, user_role, action, target_type, str(target_id), details))
    log_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return log_id


# =========================================================================
# سجل حصص الانتظار المشترك بين جميع الأجهزة (كان محفوظاً في متصفح كل جهاز فقط)
# =========================================================================

def _waiting_row_to_client(r):
    d = dict(r)
    return {
        "id": int(d["assignment_id"]) if str(d.get("assignment_id") or "").isdigit() else d.get("assignment_id"),
        "assignedTeacher": d.get("teacher_name"),
        "absentTeacher": d.get("absent_teacher"),
        "day": d.get("day"),
        "period": d.get("period"),
        "classroom": d.get("classroom"),
        "status": d.get("status") or "assigned",
        "notes": d.get("notes") or "",
        "selectionReason": d.get("selection_reason") or "",
        "date": d.get("assign_date") or (str(d.get("created_at") or "")[:10]),
        "executedAt": d.get("executed_at"),
    }


def list_waiting_records(limit=2000):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM waiting_records ORDER BY COALESCE(assign_date, created_at) DESC, id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [_waiting_row_to_client(r) for r in rows]


def upsert_waiting_record(item):
    conn = get_connection()
    c = conn.cursor()
    aid = str(item["id"])
    status = item.get("status") or "assigned"
    executed_at = now_riyadh().strftime("%Y-%m-%d %H:%M:%S") if status == "executed" else None
    existing = c.execute("SELECT id, executed_at FROM waiting_records WHERE assignment_id = ?", (aid,)).fetchone()
    if existing:
        c.execute(
            """UPDATE waiting_records SET teacher_name=?, absent_teacher=?, day=?, period=?, classroom=?,
               status=?, notes=?, selection_reason=?, assign_date=?, executed_at=COALESCE(executed_at, ?)
               WHERE assignment_id=?""",
            (item["assignedTeacher"], item["absentTeacher"], item["day"], item["period"], item.get("classroom") or "-",
             status, item.get("notes") or "", item.get("selectionReason") or "", item.get("date") or None,
             executed_at, aid),
        )
    else:
        c.execute(
            """INSERT INTO waiting_records (assignment_id, teacher_name, absent_teacher, day, period, classroom,
               status, notes, selection_reason, assign_date, executed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (aid, item["assignedTeacher"], item["absentTeacher"], item["day"], item["period"], item.get("classroom") or "-",
             status, item.get("notes") or "", item.get("selectionReason") or "", item.get("date") or None, executed_at),
        )
    conn.commit()
    row = c.execute("SELECT * FROM waiting_records WHERE assignment_id = ?", (aid,)).fetchone()
    conn.close()
    return _waiting_row_to_client(row)


def find_waiting_conflict(item):
    """يرجع تكليفاً قائماً لنفس المعلم في نفس اليوم والحصة خلال آخر 6 أيام (منع الإسناد المزدوج)."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM waiting_records
           WHERE teacher_name = ? AND day = ? AND period = ? AND status != 'cancelled' AND assignment_id != ?""",
        (item["assignedTeacher"], item["day"], item["period"], str(item["id"])),
    ).fetchall()
    conn.close()
    ref = item.get("date") or now_riyadh().strftime("%Y-%m-%d")
    try:
        ref_d = datetime.strptime(ref[:10], "%Y-%m-%d")
    except ValueError:
        ref_d = now_riyadh()
    for r in rows:
        d = (r["assign_date"] or str(r["created_at"] or ""))[:10]
        try:
            delta = (ref_d - datetime.strptime(d, "%Y-%m-%d")).days
        except ValueError:
            continue
        if 0 <= delta <= 6:
            return _waiting_row_to_client(r)
    return None
