import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "school.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # 1. جدول الطلاب
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        national_id TEXT,
        grade TEXT NOT NULL,
        classroom TEXT NOT NULL,
        guardian_phone TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 2. جدول أنواع السلوكيات والمخالفات (وفق لائحة قواعد السلوك والمواظبة)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS behavior_types (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        degree TEXT NOT NULL,
        degree_level INTEGER DEFAULT 1,
        deduction_points INTEGER DEFAULT 1,
        description TEXT
    )
    """)

    # 3. جدول التحويلات والإحالات (سجل المتابعة)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        teacher_name TEXT NOT NULL,
        subject TEXT,
        period TEXT,
        behavior_id INTEGER,
        behavior_name TEXT NOT NULL,
        behavior_degree TEXT NOT NULL,
        notes TEXT,
        status TEXT DEFAULT 'pending',
        action_taken TEXT,
        action_notes TEXT,
        action_date TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (student_id) REFERENCES students (id),
        FOREIGN KEY (behavior_id) REFERENCES behavior_types (id)
    )
    """)

    # 4. جدول المعلمين (للتسهيل والاختيار السريع)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS teachers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        subject TEXT
    )
    """)

    conn.commit()

    # بذر البيانات التجريبية إذا كانت الجداول فارغة
    seed_sample_data(conn)
    conn.close()

def seed_sample_data(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM students")
    if cursor.fetchone()[0] > 0:
        return  # البيانات موجودة مسبقاً

    # إضافة المعلمين
    teachers = [
        ("أ. فهد بن عبدالله المطيري", "لغتي الخالدة"),
        ("أ. خالد بن ناصر القحطاني", "الرياضيات"),
        ("أ. تركي بن صالح العتيبي", "العلوم"),
        ("أ. محمد بن سعيد الغامدي", "الدراسات الإسلامية"),
        ("أ. عبدالعزيز بن سالم الدوسري", "اللغة الإنجليزية"),
        ("أ. سلطان بن إبراهيم الشمري", "المهارات الرقمية"),
        ("أ. ريان بن عادل الزهراني", "التربية البدنية")
    ]
    cursor.executemany("INSERT INTO teachers (name, subject) VALUES (?, ?)", teachers)

    # قائمة السلوكيات (لائحة قواعد السلوك والمواظبة)
    behaviors = [
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
    cursor.executemany("""
    INSERT INTO behavior_types (name, degree, degree_level, deduction_points, description)
    VALUES (?, ?, ?, ?, ?)
    """, behaviors)

    # قائمة بالطلاب (عينات واقعية لفصول ومراحل متعددة)
    students = [
        ("سعد بن مشعل الشمري", "1098234123", "أول متوسط", "1/1", "0501112233"),
        ("ريان بن نايف المطيري", "1098234124", "أول متوسط", "1/1", "0502223344"),
        ("عمر بن خالد الدوسري", "1098234125", "أول متوسط", "1/2", "0503334455"),
        ("عبدالله بن يوسف القحطاني", "1098234126", "أول متوسط", "1/2", "0504445566"),
        ("فيصل بن سلطان العتيبي", "1098234127", "أول متوسط", "1/3", "0505556677"),
        ("محمد بن أحمد الغامدي", "1087123456", "ثاني متوسط", "2/1", "0506667788"),
        ("يزيد بن فهد العنزي", "1087123457", "ثاني متوسط", "2/1", "0507778899"),
        ("بندر بن صالح الشهري", "1087123458", "ثاني متوسط", "2/2", "0508889900"),
        ("عبدالعزيز بن ناصر القرني", "1087123459", "ثاني متوسط", "2/2", "0551113355"),
        ("فهد بن نواف الحربي", "1076987651", "ثالث متوسط", "3/1", "0552224466"),
        ("تركي بن سليمان الخالدي", "1076987652", "ثالث متوسط", "3/1", "0553335577"),
        ("سلمان بن مبارك الزهراني", "1076987653", "ثالث متوسط", "3/2", "0554446688"),
        ("خالد بن حمد السبيعي", "1076987654", "ثالث متوسط", "3/2", "0555557799")
    ]
    cursor.executemany("""
    INSERT INTO students (name, national_id, grade, classroom, guardian_phone)
    VALUES (?, ?, ?, ?, ?)
    """, students)

    # إضافة إحالات سابقة تجريبية (لتوضيح الأرشيف للوكيل مباشرة عند التجربة)
    sample_referrals = [
        # إحالة منتهية للطالب سعد الشمري (أول متوسط 1/1)
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

        # إحالة قيد المعالجة للطالب فهد الحربي (ثالث متوسط 3/1)
        (10, "أ. عبدالعزيز بن سالم الدوسري", "اللغة الإنجليزية", "الحصة الرابعة", 9, "الشجار أو الاشتباك بالأيدي مع الزملاء", "الدرجة الثالثة",
         "اشتبك الطالب مع أحد زملائه بسبب خلاف على الأدوات المدرسية وتبادل الصراخ والضرب.", "in_progress",
         "إحالة للموجه الطلابي لدراسة الحالة وطلب ولي الأمر غداً صباحاً.",
         "تم تهدئة الطرفين وفصلهما مؤقتاً.",
         "2026-10-21 11:20:00", "2026-10-21 10:45:00"),

        # إحالة جديدة بانتظار الإجراء للطالب عمر الدوسري (أول متوسط 1/2)
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
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
        date_str = datetime.now().strftime("%Y-%m-%d")
    
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
    SELECT s.id, s.name, s.grade, s.classroom, s.guardian_phone,
           SUM(CASE WHEN a.type = 'absence' AND a.has_excuse = 0 THEN 1 ELSE 0 END) as unexcused_absences,
           SUM(CASE WHEN a.type = 'absence' AND a.has_excuse = 1 THEN 1 ELSE 0 END) as excused_absences,
           SUM(CASE WHEN a.type = 'tardy' THEN 1 ELSE 0 END) as total_tardies,
           COUNT(a.id) as total_incidents,
           MAX(a.date) as last_incident_date
    FROM students s
    JOIN attendance a ON s.id = a.student_id
    GROUP BY s.id
    HAVING (unexcused_absences >= ? OR total_tardies >= ?)
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
    now_date = datetime.now().strftime("%Y-%m-%d")
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
