"""
اختبار دخان شامل للخادم (مكتبة بايثون القياسية فقط).

التشغيل:
    DATA_DIR=/tmp/school-test uvicorn app:app --port 8765 &
    python tests/smoke_test.py http://127.0.0.1:8765

يتحقق من: الرموز المعتمدة، رفض الطلبات بلا دخول، صلاحيات كل دور، ثبات الرموز،
قفل الجدول، تنقية المدخلات، منع الإسناد المزدوج للانتظار، والنسخ الاحتياطي.
تنبيه: يكتب بيانات اختبار — شغّله على مجلد بيانات مؤقت فقط، لا على الخادم الحي.
"""
import io
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765").rstrip("/")
ADMIN_PINS = {"0000": "principal", "1111": "vp", "2222": "counselor"}
TEACHER_PINS = [str(1000 + i) for i in range(1, 23)]

passed, failed = 0, []


def call(method, path, body=None, token=None, raw=None, headers=None):
    h = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if raw is not None:
        data, ctype = raw
        h["Content-Type"] = ctype
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            txt = r.read()
            try:
                return r.status, json.loads(txt)
            except Exception:
                return r.status, txt
    except urllib.error.HTTPError as e:
        txt = e.read()
        try:
            return e.code, json.loads(txt)
        except Exception:
            return e.code, txt


def check(name, cond, detail=""):
    global passed
    if cond:
        passed += 1
    else:
        failed.append(f"{name} {detail}")
        print("  ✗", name, detail)


def login(pin):
    st, d = call("POST", "/api/auth/login", {"pin": pin})
    return d.get("token") if st == 200 else None


def main():
    for _ in range(30):
        try:
            if call("GET", "/healthz")[0] == 200:
                break
        except Exception:
            time.sleep(1)

    print("• الرموز المعتمدة")
    tokens = {}
    for pin, role in ADMIN_PINS.items():
        st, d = call("POST", "/api/auth/login", {"pin": pin})
        check(f"دخول {pin}", st == 200 and d["user"]["role"] == role, str(st))
        tokens[role] = d.get("token")
    for pin in TEACHER_PINS:
        st, d = call("POST", "/api/auth/login", {"pin": pin})
        check(f"دخول معلم {pin}", st == 200 and d["user"]["role"] == "teacher", str(st))
    tokens["teacher"] = login("1001")
    st, _ = call("POST", "/api/auth/login", {"pin": "١١١١"})
    check("قبول الأرقام العربية", st == 200)
    for bad in ["1234", "9999", "", "abcd"]:
        st, _ = call("POST", "/api/auth/login", {"pin": bad}, headers={"X-Forwarded-For": "203.0.113.7"})
        check(f"رفض الرمز {bad!r}", st == 401, str(st))

    print("• الحماية بلا دخول")
    for path in ["/api/students", "/api/referrals", "/api/backups", "/api/timetable", "/api/waiting", "/api/stats"]:
        check(f"401 {path}", call("GET", path)[0] == 401)
    check("رمز مزوّر مرفوض", call("GET", "/api/students", token=(tokens["principal"] or "") + "x")[0] == 401)

    print("• صلاحيات الأدوار")
    matrix = {
        "/api/stats": {"principal": 200, "vp": 200, "counselor": 200, "teacher": 403},
        "/api/counselor/cases": {"principal": 200, "vp": 200, "counselor": 200, "teacher": 403},
        "/api/attendance": {"principal": 200, "vp": 200, "counselor": 200, "teacher": 403},
        "/api/backups": {"principal": 200, "vp": 200, "counselor": 403, "teacher": 403},
        "/api/students": {"principal": 200, "vp": 200, "counselor": 200, "teacher": 200},
        "/api/timetable": {"principal": 200, "vp": 200, "counselor": 200, "teacher": 200},
    }
    for path, expected in matrix.items():
        for role, code in expected.items():
            st, _ = call("GET", path, token=tokens[role])
            check(f"{role} {path}", st == code, f"→ {st} (متوقع {code})")

    print("• ثبات الرموز وإخفاؤها")
    st, tl = call("GET", "/api/teachers-list", token=tokens["vp"])
    check("الوكيل لا يرى الرموز", st == 200 and all("pin" not in t for t in tl))
    st, tl_p = call("GET", "/api/teachers-list", token=tokens["principal"])
    check("المدير يرى 22 معلماً", st == 200 and len(tl_p) == 22)
    tampered = [dict(t, pin="5555") for t in tl_p]
    call("POST", "/api/teachers-list", tampered, token=tokens["principal"])
    check("الرمز 1001 ما زال يعمل بعد محاولة تغييره", login("1001") is not None)
    check("الرمز 5555 لا يعمل", login("5555") is None)

    print("• قفل الجدول المعتمد")
    st, integ = call("GET", "/api/timetable/integrity", token=tokens["principal"])
    check("الجدول مطابق للنسخة المرجعية", st == 200 and integ.get("matches_canonical") is True, str(integ))
    if integ.get("locked"):
        st, _ = call("POST", "/api/timetable", {"1": {}}, token=tokens["principal"])
        check("تعديل الجدول مرفوض (مقفل)", st == 423, str(st))

    print("• تنقية المدخلات والصلاحيات")
    st, d = call("POST", "/api/students", {"name": "<script>x</script>طالب اختبار", "grade": "أول ثانوي", "classroom": "1"},
                 token=tokens["vp"])
    check("إضافة طالب (وكيل)", st == 200, str(st))
    sid = d.get("id")
    st, _ = call("POST", "/api/students", {"name": "x", "grade": "1", "classroom": "1"}, token=tokens["teacher"])
    check("المعلم لا يضيف طلاباً", st == 403)
    st, prof = call("GET", f"/api/students/{sid}/profile", token=tokens["vp"])
    check("الاسم منقّى من الوسوم", st == 200 and "<" not in prof["student"]["name"], str(prof.get("student")))
    st, prof_t = call("GET", f"/api/students/{sid}/profile", token=tokens["teacher"])
    check("المعلم لا يرى الهوية ولا جلسات التوجيه",
          st == 200 and "national_id" not in prof_t["student"] and prof_t["counselor_cases"] == [])

    print("• حصص الانتظار")
    wid = int(time.time() * 1000)
    today = time.strftime("%Y-%m-%d")
    item = {"id": wid, "day": "الأحد", "period": "الحصة الأولى", "assignedTeacher": "أيوب السالم",
            "absentTeacher": "الشبرمي", "classroom": "لغوية 6", "date": today}
    check("إسناد انتظار", call("POST", "/api/waiting", item, token=tokens["vp"])[0] == 200)
    dup = dict(item, id=wid + 1, absentTeacher="تركي الرزق")
    check("رفض الإسناد المزدوج", call("POST", "/api/waiting", dup, token=tokens["vp"])[0] == 409)
    check("المعلم لا يُسند انتظاراً", call("POST", "/api/waiting", dict(item, id=wid + 2), token=tokens["teacher"])[0] == 403)
    st, d = call("POST", "/api/waiting", dict(item, status="executed"), token=tokens["vp"])
    check("تحديث الحالة إلى منفذ", st == 200 and d["status"] == "executed")

    print("• النسخ الاحتياطي")
    st, meta = call("POST", "/api/backups", token=tokens["vp"])
    check("إنشاء نسخة", st == 200 and meta.get("filename", "").startswith("backup_"))
    st, _ = call("POST", f"/api/backups/{meta.get('filename')}/restore", token=tokens["vp"])
    check("الوكيل لا يستعيد النسخ", st == 403)
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"bad.zip\"\r\n"
            f"Content-Type: application/zip\r\n\r\nnot a zip\r\n--{boundary}--\r\n").encode()
    st, _ = call("POST", "/api/backups/upload", token=tokens["principal"], raw=(body, f"multipart/form-data; boundary={boundary}"))
    check("رفض ملف نسخة تالف", st == 400, str(st))

    print("• الواجهة")
    st, html = call("GET", "/")
    check("الصفحة الرئيسية تعمل", st == 200 and b"pinAuthOverlay" in html)
    check("لا توجد أزرار تخطي الرمز", "تخطي الرمز".encode() not in html)

    print()
    print(f"النتيجة: {passed} نجح، {len(failed)} فشل")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
