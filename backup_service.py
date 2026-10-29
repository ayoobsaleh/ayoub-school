"""
النسخ الاحتياطي والاستعادة — يعمل مع PostgreSQL وSQLite بنفس الصيغة.

- النسخة ملف zip فيه backup.json (كل الجداول والمستندات) + metadata.json.
- تُحفظ النسخ داخل القاعدة نفسها (جدول backups)، فلا تضيع إذا مُسح قرص الخادم.
- تقبل الاستعادة أيضاً النسخ القديمة (التي تحتوي school.db).
- نسخة يومية تلقائية الساعة 2:00 ظهراً بتوقيت الرياض، مع تعويض إن كان الخادم نائماً وقتها.
"""
import base64
import io
import json
import os
import sqlite3
import tempfile
import threading
import time
import zipfile

import database as db

BACKUP_DIR = os.path.join(db.DATA_DIR, "backups")   # مجلد مؤقت فقط
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_MEMBER_BYTES = 200 * 1024 * 1024
KEEP_BACKUPS = 30
FORMAT_VERSION = 2
V2_MEMBERS = {"backup.json", "metadata.json"}
LEGACY_MEMBERS = {"school.db", "school_timetable_saved.json", "school_teachers_saved.json", "metadata.json"}

_lock = threading.Lock()


# =========================================================================
# التصدير
# =========================================================================
def export_data():
    conn = db.get_connection()
    try:
        tables = {}
        for t in db.TABLES:
            cols = db.table_columns(conn, t)
            if not cols:
                continue
            rows = conn.execute(f"SELECT {', '.join(cols)} FROM {t} ORDER BY 1").fetchall()
            tables[t] = {"columns": cols, "rows": [[r[i] for i in range(len(cols))] for r in rows]}
        return tables
    finally:
        conn.close()


def _counts(tables):
    return {
        "total_students": len(tables.get("students", {}).get("rows", [])),
        "total_referrals": len(tables.get("referrals", {}).get("rows", [])),
    }


def _reason_label(reason):
    if "auto" in reason:
        return "تلقائي (2:00 ظهراً)"
    if "pre_restore" in reason:
        return "أمان قبل الاستعادة"
    if "pre_timetable" in reason:
        return "قبل تعديل الجدول"
    if "uploaded" in reason:
        return "مرفوعة"
    return "يدوي"


def build_backup_zip(reason="manual"):
    now = db.now_riyadh()
    stamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"backup_{stamp}_{reason}.zip"
    tables = export_data()
    meta = {
        "filename": filename,
        "created_at": now.strftime("%Y/%m/%d %I:%M %p"),
        "timestamp": stamp,
        "reason": _reason_label(reason),
        "school": "ثانوية أبي أيوب الأنصاري",
        "backend": db.backend_name(),
        "version": FORMAT_VERSION,
        **_counts(tables),
    }
    payload = {"version": FORMAT_VERSION, "created_at": db.now_str(), "tables": tables}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("backup.json", json.dumps(payload, ensure_ascii=False, default=str))
        z.writestr("metadata.json", json.dumps(meta, ensure_ascii=False, indent=2))
    return filename, buf.getvalue(), meta


def create_backup(reason="manual"):
    with _lock:
        filename, data, meta = build_backup_zip(reason)
        meta["size_kb"] = round(len(data) / 1024, 1)
        conn = db.get_connection()
        try:
            conn.execute("INSERT INTO backups (filename, reason, meta, data) VALUES (?, ?, ?, ?)",
                         (filename, reason, json.dumps(meta, ensure_ascii=False), base64.b64encode(data).decode()))
            conn.commit()
            _cleanup(conn)
        finally:
            conn.close()
        return meta


def _cleanup(conn):
    rows = conn.execute("SELECT id FROM backups ORDER BY id DESC").fetchall()
    for r in rows[KEEP_BACKUPS:]:
        conn.execute("DELETE FROM backups WHERE id = ?", (r[0],))
    conn.commit()


def list_backups():
    conn = db.get_connection()
    try:
        rows = conn.execute("SELECT filename, meta FROM backups ORDER BY id DESC").fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        try:
            meta = json.loads(r[1] or "{}")
        except Exception:
            meta = {}
        meta["filename"] = r[0]
        out.append(meta)
    return out


def get_backup_bytes(filename):
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT data FROM backups WHERE filename = ? ORDER BY id DESC", (filename,)).fetchone()
    finally:
        conn.close()
    return base64.b64decode(row[0]) if row else None


# =========================================================================
# التحقق والقراءة
# =========================================================================
def _read_zip(data):
    """يرجع {"tables": {...}} من نسخة جديدة أو قديمة، بعد التحقق. يرفع ValueError عند أي خلل."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("حجم الملف أكبر من 50MB")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("الملف ليس أرشيف zip صالحاً")
    with z:
        infos = z.infolist()
        names = {i.filename for i in infos}
        for i in infos:
            if i.file_size > MAX_MEMBER_BYTES:
                raise ValueError(f"حجم {i.filename} بعد فك الضغط أكبر من المسموح")

        if "backup.json" in names:
            if names - V2_MEMBERS:
                raise ValueError("الأرشيف يحتوي ملفات غير متوقعة")
            payload = json.loads(z.read("backup.json").decode("utf-8"))
            tables = payload.get("tables")
            if not isinstance(tables, dict) or "students" not in tables:
                raise ValueError("ملف النسخة لا يخص هذا النظام")
            for t, spec in tables.items():
                if t not in db.TABLES or not isinstance(spec.get("columns"), list) or not isinstance(spec.get("rows"), list):
                    raise ValueError(f"جدول غير صالح في النسخة: {t}")
            return tables

        # صيغة قديمة (school.db + ملفات JSON)
        if names - LEGACY_MEMBERS or not names & {"school.db", "school_timetable_saved.json", "school_teachers_saved.json"}:
            raise ValueError("الأرشيف لا يحتوي بيانات قابلة للاستعادة")
        tables = {}
        if "school.db" in names:
            fd, tmp = tempfile.mkstemp(suffix=".db")
            os.close(fd)
            try:
                with open(tmp, "wb") as f:
                    f.write(z.read("school.db"))
                conn = sqlite3.connect(tmp)
                try:
                    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise ValueError("قاعدة البيانات داخل النسخة تالفة")
                    present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if not {"students", "referrals", "behavior_types"} <= present:
                        raise ValueError("قاعدة البيانات داخل النسخة لا تخص هذا النظام")
                    for t in db.TABLES:
                        if t in present:
                            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
                            rows = conn.execute(f"SELECT {', '.join(cols)} FROM {t}").fetchall()
                            tables[t] = {"columns": cols, "rows": [list(r) for r in rows]}
                finally:
                    conn.close()
            except sqlite3.DatabaseError:
                raise ValueError("ملف school.db داخل النسخة ليس قاعدة بيانات صالحة")
            finally:
                try:
                    os.remove(tmp)
                except Exception:
                    pass
        docs = []
        if "school_timetable_saved.json" in names:
            tt = json.loads(z.read("school_timetable_saved.json").decode("utf-8"))
            if not isinstance(tt, dict) or not tt:
                raise ValueError("ملف الجدول داخل النسخة غير صالح")
            docs.append(["timetable", json.dumps(tt, ensure_ascii=False), db.now_str()])
        if "school_teachers_saved.json" in names:
            te = json.loads(z.read("school_teachers_saved.json").decode("utf-8"))
            if not isinstance(te, list) or not te:
                raise ValueError("ملف المعلمين داخل النسخة غير صالح")
            docs.append(["teachers", json.dumps(te, ensure_ascii=False), db.now_str()])
        if docs:
            tables["app_documents"] = {"columns": ["key", "value", "updated_at"], "rows": docs, "merge": True}
        return tables


# =========================================================================
# الاستعادة
# =========================================================================
def _import_tables(tables):
    conn = db.get_connection()
    try:
        for t in db.TABLES:
            spec = tables.get(t)
            if not spec:
                continue
            live_cols = db.table_columns(conn, t)
            idx = [i for i, c in enumerate(spec["columns"]) if c in live_cols]
            cols = [spec["columns"][i] for i in idx]
            if not cols:
                continue
            if spec.get("merge"):
                # مستندات من نسخة قديمة: استبدال مفاتيحها فقط
                for row in spec["rows"]:
                    conn.execute("DELETE FROM app_documents WHERE key = ?", (row[0],))
            else:
                conn.execute(f"DELETE FROM {t}")
            placeholders = ", ".join("?" for _ in cols)
            rows = [[row[i] for i in idx] for row in spec["rows"]]
            if rows:
                conn.executemany(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({placeholders})", rows)
            if db.IS_PG and "id" in cols:
                conn.execute(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {t}")
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def restore_from_bytes(data, label="upload"):
    tables = _read_zip(data)          # تحقق كامل قبل لمس أي بيانات
    create_backup(reason="pre_restore_safety")
    with _lock:
        _import_tables(tables)
    db.init_db()                      # ترقية المخطط وتحديث جدول المعلمين
    return {"status": "success", "message": "تمت استعادة البيانات بنجاح"}


def restore_backup(filename):
    data = get_backup_bytes(os.path.basename(filename))
    if data is None:
        raise FileNotFoundError("ملف النسخة الاحتياطية غير موجود")
    return restore_from_bytes(data, label=filename)


def save_uploaded_backup(original_name, contents):
    """يتحقق من الملف المرفوع ثم يحفظه ضمن النسخ ويرجع اسمه."""
    _read_zip(contents)
    name = f"backup_{db.now_riyadh().strftime('%Y-%m-%d_%H-%M-%S')}_uploaded.zip"
    meta = {"filename": name, "created_at": db.now_riyadh().strftime("%Y/%m/%d %I:%M %p"),
            "reason": _reason_label("uploaded"), "size_kb": round(len(contents) / 1024, 1),
            "total_students": "-", "total_referrals": "-"}
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO backups (filename, reason, meta, data) VALUES (?, ?, ?, ?)",
                     (name, "uploaded", json.dumps(meta, ensure_ascii=False), base64.b64encode(contents).decode()))
        conn.commit()
    finally:
        conn.close()
    return name


# =========================================================================
# الجدولة اليومية
# =========================================================================
_scheduler_started = False


def _has_auto_backup_today(today):
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) FROM backups WHERE reason LIKE ? AND filename LIKE ?",
                           ("auto%", f"backup_{today}_%")).fetchone()
        return bool(row and row[0])
    finally:
        conn.close()


def _daily_backup_worker():
    while True:
        try:
            now = db.now_riyadh()
            today = now.strftime("%Y-%m-%d")
            # الساعة 2 ظهراً أو بعدها (تعويض إن كان الخادم نائماً وقتها)
            if now.hour >= 14 and not _has_auto_backup_today(today):
                create_backup(reason="auto_daily_14_00")
                print(f"[Auto-Backup] daily backup created for {today} (Riyadh)")
        except Exception as e:
            print("[Auto-Backup Error]:", e)
        time.sleep(300)


def start_backup_scheduler():
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True
    threading.Thread(target=_daily_backup_worker, daemon=True).start()
