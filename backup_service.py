import os
import sqlite3
import zipfile
import json
import time
import shutil
import threading
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
DB_PATH = os.path.join(BASE_DIR, "school.db")
TIMETABLE_FILE = os.path.join(BASE_DIR, "school_timetable_saved.json")
TEACHERS_FILE = os.path.join(BASE_DIR, "school_teachers_saved.json")

os.makedirs(BACKUP_DIR, exist_ok=True)

def safe_backup_db(target_path):
    """Atomic and thread-safe backup of SQLite database using native backup API."""
    if not os.path.exists(DB_PATH):
        return False
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(target_path)
    try:
        with dst:
            src.backup(dst)
        return True
    finally:
        dst.close()
        src.close()

def get_stats_summary():
    """Extract quick stats to include in backup metadata."""
    total_students = 0
    total_referrals = 0
    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM students")
            total_students = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM referrals")
            total_referrals = c.fetchone()[0]
            conn.close()
        except Exception:
            pass
    return total_students, total_referrals

def create_backup(reason="manual"):
    """
    Creates a full backup zip containing:
    1. school.db (atomic copy)
    2. school_timetable_saved.json (if exists)
    3. school_teachers_saved.json (if exists)
    4. metadata.json
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)
    now = datetime.now()
    timestamp_str = now.strftime("%Y-%m-%d_%H-%M-%S")
    readable_date = now.strftime("%Y/%m/%d %I:%M %p")
    filename = f"backup_{timestamp_str}_{reason}.zip"
    zip_path = os.path.join(BACKUP_DIR, filename)

    temp_db = os.path.join(BACKUP_DIR, f"temp_{timestamp_str}.db")
    safe_backup_db(temp_db)

    total_students, total_referrals = get_stats_summary()

    metadata = {
        "filename": filename,
        "created_at": readable_date,
        "timestamp": timestamp_str,
        "reason": "تلقائي (2:00 ظهراً)" if "auto" in reason else "يدوي",
        "total_students": total_students,
        "total_referrals": total_referrals,
        "school": "ثانوية أبي أيوب الأنصاري",
        "version": "1.0"
    }

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        if os.path.exists(temp_db):
            z.write(temp_db, arcname="school.db")
        if os.path.exists(TIMETABLE_FILE):
            z.write(TIMETABLE_FILE, arcname="school_timetable_saved.json")
        if os.path.exists(TEACHERS_FILE):
            z.write(TEACHERS_FILE, arcname="school_teachers_saved.json")
        z.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))

    if os.path.exists(temp_db):
        try:
            os.remove(temp_db)
        except Exception:
            pass

    cleanup_old_backups(keep_count=30)

    file_size_kb = round(os.path.getsize(zip_path) / 1024, 1)
    metadata["size_kb"] = file_size_kb
    return metadata

def list_backups():
    """Returns list of backups with metadata, newest first."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backups = []
    for f in os.listdir(BACKUP_DIR):
        if f.endswith(".zip") and f.startswith("backup_"):
            full_path = os.path.join(BACKUP_DIR, f)
            try:
                size_kb = round(os.path.getsize(full_path) / 1024, 1)
                meta = {}
                with zipfile.ZipFile(full_path, "r") as z:
                    if "metadata.json" in z.namelist():
                        meta = json.loads(z.read("metadata.json").decode("utf-8"))
                
                if not meta:
                    meta = {
                        "filename": f,
                        "created_at": datetime.fromtimestamp(os.path.getmtime(full_path)).strftime("%Y/%m/%d %I:%M %p"),
                        "reason": "تلقائي" if "auto" in f else "يدوي",
                        "total_students": "-",
                        "total_referrals": "-"
                    }
                meta["size_kb"] = size_kb
                meta["filename"] = f
                backups.append(meta)
            except Exception as e:
                pass

    backups.sort(key=lambda x: x.get("timestamp", x.get("filename", "")), reverse=True)
    return backups

def restore_backup(filename):
    """
    Safely restores backup from the backups directory:
    First takes a safety snapshot, then unpacks files.
    """
    safe_filename = os.path.basename(filename)
    zip_path = os.path.join(BACKUP_DIR, safe_filename)
    if not os.path.exists(zip_path):
        raise FileNotFoundError("ملف النسخة الاحتياطية غير موجود")

    # 1. إنشاء نسخة أمان احتياطية قبل الاستعادة
    create_backup(reason="pre_restore_safety")

    # 2. استخراج وفك الملفات
    with zipfile.ZipFile(zip_path, "r") as z:
        if "school.db" in z.namelist():
            temp_db = os.path.join(BACKUP_DIR, "restore_temp.db")
            with open(temp_db, "wb") as f_out:
                f_out.write(z.read("school.db"))
            shutil.copyfile(temp_db, DB_PATH)
            try:
                os.remove(temp_db)
            except Exception:
                pass
        
        if "school_timetable_saved.json" in z.namelist():
            with open(TIMETABLE_FILE, "wb") as f_out:
                f_out.write(z.read("school_timetable_saved.json"))

        if "school_teachers_saved.json" in z.namelist():
            with open(TEACHERS_FILE, "wb") as f_out:
                f_out.write(z.read("school_teachers_saved.json"))

    return {"status": "success", "message": "تمت استعادة البيانات بنجاح"}

def cleanup_old_backups(keep_count=30):
    """Keep only latest keep_count backups."""
    backups = []
    for f in os.listdir(BACKUP_DIR):
        if f.endswith(".zip") and f.startswith("backup_"):
            full_path = os.path.join(BACKUP_DIR, f)
            backups.append((os.path.getmtime(full_path), full_path))
    
    backups.sort(key=lambda x: x[0], reverse=True)
    if len(backups) > keep_count:
        for _, path in backups[keep_count:]:
            try:
                os.remove(path)
            except Exception:
                pass

# Background daemon for 14:00 daily backups
_last_daily_backup_date = None

def _daily_backup_worker():
    global _last_daily_backup_date
    while True:
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            # If current hour is 14 (2:00 PM) and we haven't backed up today
            if now.hour == 14 and _last_daily_backup_date != today_str:
                create_backup(reason="auto_daily_14_00")
                _last_daily_backup_date = today_str
                print(f"[Auto-Backup] Successfully created daily backup for {today_str} at 14:00")
        except Exception as e:
            print("[Auto-Backup Error]:", e)
        time.sleep(60)

def start_backup_scheduler():
    t = threading.Thread(target=_daily_backup_worker, daemon=True)
    t.start()
