"""
قواعد الجدول المدرسي لثانوية أبي أيوب الأنصاري والتحقق منها.

البنية في school_structure.json:
  - الأحد والاثنين ٧ حصص، الثلاثاء والأربعاء والخميس ٦ حصص.
  - شعبة ٧ (ثاني ثانوي — إدارة الأعمال) ٥ حصص يوم الخميس فقط.
  - ٩ شعب: أول ثانوي ١–٣، ثاني ثانوي ٥–٦ + إدارة أعمال ٧، ثالث ثانوي ٨–٩ + إدارة أعمال ١٠ (لا توجد شعبة ٤).

الجدول نفسه (school_timetable_saved.json) مصفوفة: رقم المعلم → اليوم → قائمة الحصص،
وكل خلية نص مثل «لغوية 6» أو «قرآن 2 / قانون 10» (الأرقام = الشعب).
هذا الملف لا يعدّل الجدول أبداً؛ يقرأ ويحكم فقط.
"""
import json
import os
import re
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
STRUCTURE_FILE = os.path.join(ROOT, "school_structure.json")
EMPTY_MARKS = {"", "فراغ", "-", "—"}


def load_structure(path=STRUCTURE_FILE):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def day_names(structure):
    return [d["name"] for d in structure["days"]]


def day_periods(structure, day):
    for d in structure["days"]:
        if d["name"] == day:
            return d["periods"]
    return 0


def section_periods(structure, section_id, day):
    """عدد حصص الشعبة في اليوم (مع استثناء المسار يوم الخميس)."""
    for s in structure["sections"]:
        if int(s["id"]) == int(section_id):
            return int((s.get("periods_override") or {}).get(day, day_periods(structure, day)))
    return 0


def is_busy(cell):
    return str(cell or "").strip() not in EMPTY_MARKS


def cell_sections(cell):
    """الشعب المذكورة في الخلية: «قرآن 2 / قانون 10» ← [2, 10]."""
    digits = str(cell or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    return sorted({int(n) for n in re.findall(r"\d+", digits)})


def section_label(structure, section_id):
    for s in structure["sections"]:
        if int(s["id"]) == int(section_id):
            return f"شعبة {s['id']} — {s['grade']} ({s['track']})"
    return f"شعبة {section_id}"


def weekly_capacity(structure, section_id):
    return sum(section_periods(structure, section_id, d) for d in day_names(structure))


def validate(matrix, teachers, structure=None):
    """
    يرجع تقريراً: errors (مخالفات تمنع الاعتماد)، warnings (تحتاج مراجعة)، وإحصاءات.
    """
    structure = structure or load_structure()
    days = day_names(structure)
    section_ids = [int(s["id"]) for s in structure["sections"]]
    errors, warnings = [], []
    slots = defaultdict(list)          # (section, day, period) -> [(teacher, cell)]
    teacher_slot = defaultdict(list)   # (teacher_id, day, period) for structure checks
    total_cells = 0
    load_diffs = []

    for t in teachers:
        tid = str(t["id"])
        sched = matrix.get(tid)
        if not isinstance(sched, dict):
            errors.append({"type": "missing_teacher", "teacher": t["name"], "msg": f"لا يوجد جدول للمعلم {t['name']}"})
            continue
        actual = 0
        for d in days:
            row = sched.get(d) or []
            limit = day_periods(structure, d)
            for p, cell in enumerate(row, start=1):
                if not is_busy(cell):
                    continue
                total_cells += 1
                actual += 1
                if p > limit:
                    errors.append({"type": "outside_day", "teacher": t["name"], "day": d, "period": p, "cell": cell,
                                   "msg": f"{t['name']}: «{cell}» في الحصة {p} يوم {d}، واليوم {limit} حصص فقط"})
                secs = cell_sections(cell)
                if not secs:
                    warnings.append({"type": "no_section", "teacher": t["name"], "day": d, "period": p, "cell": cell,
                                     "msg": f"{t['name']}: «{cell}» يوم {d} الحصة {p} بلا رقم شعبة"})
                for s in secs:
                    if s not in section_ids:
                        errors.append({"type": "unknown_section", "teacher": t["name"], "day": d, "period": p, "cell": cell,
                                       "msg": f"{t['name']}: «{cell}» يشير إلى شعبة {s} غير موجودة"})
                        continue
                    if p > section_periods(structure, s, d) and p <= limit:
                        errors.append({"type": "outside_section_day", "teacher": t["name"], "day": d, "period": p, "cell": cell,
                                       "msg": f"{t['name']}: «{cell}» في الحصة {p} يوم {d}، والشعبة {s} تنتهي عند الحصة {section_periods(structure, s, d)}"})
                    slots[(s, d, p)].append((t["name"], cell))
        if t.get("load") is not None and int(t["load"]) != actual:
            load_diffs.append({"teacher": t["name"], "id": t["id"], "declared": int(t["load"]), "actual": actual})

    # تغطية الشعب وتعارضاتها
    coverage = []
    for s in section_ids:
        cap = filled = multi = 0
        empty_slots = []
        for d in days:
            for p in range(1, section_periods(structure, s, d) + 1):
                cap += 1
                here = slots.get((s, d, p), [])
                if here:
                    filled += 1
                    if len(here) > 1:
                        multi += 1
                        warnings.append({"type": "section_clash", "section": s, "day": d, "period": p,
                                         "msg": f"شعبة {s} يوم {d} الحصة {p}: " + " ، ".join(f"{c} ({n})" for n, c in here)})
                else:
                    empty_slots.append({"day": d, "period": p})
        coverage.append({"section": s, "label": section_label(structure, s), "capacity": cap, "filled": filled,
                         "empty": cap - filled, "multi": multi, "empty_slots": empty_slots})
        if filled == 0:
            warnings.append({"type": "section_missing", "section": s, "msg": f"شعبة {s} غير موجودة في الجدول إطلاقاً"})
        elif cap - filled:
            warnings.append({"type": "section_gaps", "section": s, "msg": f"شعبة {s}: {cap - filled} حصة فارغة من {cap}"})
    for ld in load_diffs:
        warnings.append({"type": "load_diff", "teacher": ld["teacher"],
                         "msg": f"{ld['teacher']}: النصاب المسجّل {ld['declared']} والفعلي في الجدول {ld['actual']}"})

    capacity = sum(c["capacity"] for c in coverage)
    covered = sum(c["filled"] for c in coverage)
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "stats": {
            "teachers": len(teachers),
            "cells": total_cells,
            "section_capacity": capacity,
            "section_slots_covered": covered,
            "section_slots_empty": capacity - covered,
            "declared_load_total": sum(int(t.get("load") or 0) for t in teachers),
        },
        "coverage": coverage,
        "load_diffs": load_diffs,
    }


def section_schedule(matrix, teachers, section_id, structure=None):
    """جدول شعبة واحدة مشتقاً من جداول المعلمين: اليوم ← [ {period, entries:[{teacher, cell}]} ]."""
    structure = structure or load_structure()
    out = {}
    names = {str(t["id"]): t["name"] for t in teachers}
    for d in day_names(structure):
        rows = []
        for p in range(1, section_periods(structure, section_id, d) + 1):
            entries = []
            for tid, sched in matrix.items():
                if tid not in names:
                    continue
                row = (sched or {}).get(d) or []
                if p <= len(row) and is_busy(row[p - 1]) and int(section_id) in cell_sections(row[p - 1]):
                    entries.append({"teacher": names[tid], "teacher_id": int(tid), "cell": row[p - 1]})
            rows.append({"period": p, "entries": entries})
        out[d] = rows
    return out
