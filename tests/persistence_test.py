"""
اختبار حفظ البيانات والنسخ الاحتياطي (مكتبة بايثون القياسية فقط).

    python tests/persistence_test.py http://127.0.0.1:8765 [legacy_backup.zip]

يتحقق من: تسجيل بيانات عبر كل الوحدات، إنشاء نسخة، حذف/تعديل، استعادة النسخة
وعودة البيانات كما كانت، إضافة سجلات جديدة بعد الاستعادة (تسلسل المعرّفات سليم)،
واستعادة نسخة بالصيغة القديمة (school.db) إن مُرّر ملفها.
تنبيه: يكتب ويستعيد بيانات — للتشغيل على قاعدة اختبار فقط.
"""
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765").rstrip("/")
LEGACY = sys.argv[2] if len(sys.argv) > 2 else None
passed, failed = 0, []


def call(method, path, body=None, token=None, raw=None):
    h = {}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if raw is not None:
        data, h["Content-Type"] = raw
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            t = r.read()
            try:
                return r.status, json.loads(t)
            except Exception:
                return r.status, t
    except urllib.error.HTTPError as e:
        t = e.read()
        try:
            return e.code, json.loads(t)
        except Exception:
            return e.code, t


def check(name, cond, detail=""):
    global passed
    if cond:
        passed += 1
    else:
        failed.append(name)
        print("  ✗", name, detail)


def upload(token, filename, content):
    b = uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: application/zip\r\n\r\n").encode() + content + f"\r\n--{b}--\r\n".encode()
    return call("POST", "/api/backups/upload", token=token, raw=(body, f"multipart/form-data; boundary={b}"))


def main():
    for _ in range(30):
        try:
            if call("GET", "/healthz")[0] == 200:
                break
        except Exception:
            time.sleep(1)
    P = call("POST", "/api/auth/login", {"pin": "0000"})[1]["token"]
    V = call("POST", "/api/auth/login", {"pin": "1111"})[1]["token"]

    st, sysinfo = call("GET", "/api/system/status", token=P)
    print(f"• القاعدة: {sysinfo.get('database')} — دائمة: {sysinfo.get('persistent')}")

    print("• تسجيل بيانات عبر الوحدات")
    tag = uuid.uuid4().hex[:6]
    st, s1 = call("POST", "/api/students", {"name": f"طالب حفظ {tag}", "grade": "أول ثانوي", "classroom": "1", "national_id": "1000000001", "guardian_phone": "0500000001"}, token=V)
    check("إضافة طالب", st == 200)
    sid = s1["id"]
    st, ref = call("POST", "/api/referrals", {"student_id": sid, "teacher_name": "أ. أيوب السالم", "behavior_name": "النوم أو الاسترخاء أثناء الدرس", "behavior_degree": "الدرجة الأولى", "notes": "اختبار"}, token=V)
    check("إحالة", st == 200)
    st, _ = call("POST", f"/api/referrals/{ref['id']}/action", {"action_taken": "تنبيه", "status": "resolved"}, token=V)
    check("قرار الإحالة", st == 200)
    today = time.strftime("%Y-%m-%d")
    for i in range(3):
        st, _ = call("POST", "/api/attendance", {"student_id": sid, "date": today, "type": "absence"}, token=V)
    check("رصد غياب ×٣", st == 200)
    st, _ = call("POST", "/api/counselor/cases", {"student_id": sid, "reason": "متابعة غياب"}, token=V)
    check("تحويل للموجه", st == 200)
    st, _ = call("POST", "/api/communications/log", {"student_id": sid, "comm_type": "واتساب", "message_content": "إشعار"}, token=V)
    check("توثيق تواصل", st == 200)
    st, rep = call("GET", "/api/attendance/repeat?min_count=3", token=V)
    check("متكررو الغياب", st == 200 and any(r["id"] == sid for r in rep), str(rep)[:200])
    st, stats = call("GET", "/api/stats", token=V)
    check("الإحصاءات", st == 200 and stats["repeat_offenders_count"] >= 1, str(stats)[:200])
    st, prof = call("GET", f"/api/students/{sid}/profile", token=V)
    check("الملف الموحد", st == 200 and prof["stats"]["unexcused_absences"] == 3 and len(prof["timeline"]) >= 5, str(prof.get("stats")))
    st, val = call("GET", "/api/timetable/validate", token=V)
    check("تقرير قواعد الجدول", st == 200 and "coverage" in val)
    st, sec = call("GET", "/api/timetable/sections/7", token=V)
    check("جدول شعبة ٧ (الخميس ٥ حصص)", st == 200 and len(sec["schedule"]["الخميس"]) == 5, str(st))
    st, _ = call("GET", "/api/timetable/sections/4", token=V)
    check("الشعبة ٤ غير موجودة", st == 404)

    print("• نسخة ← تعديل ← استعادة")
    st, meta = call("POST", "/api/backups", token=V)
    check("إنشاء نسخة", st == 200)
    count_before = len(call("GET", "/api/students", token=V)[1])
    call("POST", "/api/students", {"name": f"بعد النسخة {tag}", "grade": "ثاني ثانوي", "classroom": "5"}, token=V)
    check("إضافة بعد النسخة", len(call("GET", "/api/students", token=V)[1]) == count_before + 1)
    st, r = call("POST", f"/api/backups/{meta['filename']}/restore", token=P)
    check("الاستعادة", st == 200, str(r))
    students = call("GET", "/api/students", token=V)[1]
    check("عاد عدد الطلاب كما كان", len(students) == count_before, f"{len(students)} vs {count_before}")
    check("بيانات الطالب سليمة", any(s["name"] == f"طالب حفظ {tag}" and s["guardian_phone"] == "0500000001" for s in students))
    prof2 = call("GET", f"/api/students/{sid}/profile", token=V)[1]
    check("السجل الكامل بعد الاستعادة", prof2["stats"] == prof["stats"], f"{prof2['stats']} vs {prof['stats']}")
    st, s3 = call("POST", "/api/students", {"name": f"جديد بعد الاستعادة {tag}", "grade": "ثالث ثانوي", "classroom": "8"}, token=V)
    check("إضافة جديدة بعد الاستعادة (تسلسل سليم)", st == 200 and s3["id"] not in {s["id"] for s in students}, str(s3))
    st, integ = call("GET", "/api/timetable/integrity", token=P)
    check("الجدول ما زال مطابقاً للمعتمد", integ.get("matches_canonical") is True)
    st, dl = call("GET", f"/api/backups/{meta['filename']}/download?token={P}")
    check("تنزيل النسخة", st == 200 and isinstance(dl, bytes) and dl[:2] == b"PK")
    if isinstance(dl, bytes):
        st, r = upload(P, "roundtrip.zip", dl)
        check("رفع نسخة منزّلة واستعادتها", st == 200, str(r))

    if LEGACY:
        print("• استعادة نسخة بالصيغة القديمة (school.db)")
        st, r = upload(P, "legacy.zip", open(LEGACY, "rb").read())
        check("استعادة النسخة القديمة", st == 200, str(r))
        st, lst = call("GET", "/api/students", token=V)
        check("طلاب النسخة القديمة ظاهرون", st == 200 and len(lst) > 0, str(len(lst)))
        st, s4 = call("POST", "/api/students", {"name": f"بعد القديمة {tag}", "grade": "أول ثانوي", "classroom": "2"}, token=V)
        check("إضافة بعد استعادة القديمة", st == 200)

    print(f"\nالنتيجة: {passed} نجح، {len(failed)} فشل")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
