"""
فحص سلامة الجدول المعتمد على قواعد المدرسة (قراءة فقط — لا يعدّل أي ملف).

الاستخدام:
    python tools/verify_timetable.py            # تقرير كامل
    python tools/verify_timetable.py --strict   # يفشل (exit 1) عند خلل بنيوي في الملفات
    python tools/verify_timetable.py --rules    # يفشل أيضاً عند مخالفة قواعد الدوام

القواعد في school_structure.json وtimetable_rules.py.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import timetable_rules as rules  # noqa: E402


def load_json(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return json.load(f)


def extract_js_literal(html, const_name):
    i = html.index(f"const {const_name} =")
    start = min(p for p in (html.find("{", i), html.find("[", i)) if p != -1)
    depth, j = 0, start
    while True:
        ch = html[j]
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                break
        j += 1
    return json.loads(html[start:j + 1])


def main():
    strict = "--strict" in sys.argv
    enforce_rules = "--rules" in sys.argv
    structural = []

    structure = rules.load_structure()
    matrix = load_json("school_timetable_saved.json")
    teachers = load_json("school_teachers_saved.json")

    # تطابق نسخة الواجهة الاحتياطية مع ملف الجدول (إن وُجدت في index.html)
    html_path = os.path.join(ROOT, "static", "index.html")
    if os.path.exists(html_path):
        html = open(html_path, encoding="utf-8").read()
        if "const DEFAULT_TIMETABLE_MATRIX =" in html:
            html_matrix = extract_js_literal(html, "DEFAULT_TIMETABLE_MATRIX")
            html_teachers = extract_js_literal(html, "DEFAULT_OFFICIAL_TEACHERS")
            for t in teachers:
                if html_matrix.get(str(t["id"])) != matrix.get(str(t["id"])):
                    structural.append(f"جدول المعلم {t['name']} في index.html لا يطابق ملف الجدول")
            key = lambda t: (t["id"], t["name"], t["subject"], t["load"], str(t["pin"]))
            if [key(t) for t in html_teachers] != [key(t) for t in teachers]:
                structural.append("قائمة المعلمين/الرموز في index.html لا تطابق school_teachers_saved.json")
    pins = [str(t["pin"]) for t in teachers]
    if len(set(pins)) != len(pins):
        structural.append("يوجد رمز معلم مكرر")
    for t in teachers:
        for d in rules.day_names(structure):
            row = (matrix.get(str(t["id"])) or {}).get(d)
            if row is None or len(row) != structure["max_periods"]:
                structural.append(f"المعلم {t['name']} يوم {d}: عدد الخانات {0 if row is None else len(row)} بدلاً من {structure['max_periods']}")

    report = rules.validate(matrix, teachers, structure)
    s = report["stats"]

    print("═" * 64)
    print("تقرير الجدول على قواعد ثانوية أبي أيوب الأنصاري")
    print("═" * 64)
    overrides = [f"شعبة {x['id']}: {d} {n}" for x in structure["sections"] for d, n in (x.get("periods_override") or {}).items()]
    print("الدوام: " + " · ".join(f"{d['name']} {d['periods']}" for d in structure["days"]) +
          (" · " + " · ".join(overrides) if overrides else ""))
    print("الشعب: " + "، ".join(str(x["id"]) for x in structure["sections"]))
    print(f"المعلمون {s['teachers']} | خلايا مملوءة {s['cells']} | مجموع النصاب المسجّل {s['declared_load_total']}")
    print(f"حصص الشعب المطلوبة أسبوعياً {s['section_capacity']} | المغطاة {s['section_slots_covered']} | الفارغة {s['section_slots_empty']}")
    print("\nتغطية الشعب:")
    for c in report["coverage"]:
        bar = "█" * round(20 * c["filled"] / c["capacity"]) if c["capacity"] else ""
        print(f"  {c['section']:>2}  {bar:<20} {c['filled']:>2}/{c['capacity']}  فارغة {c['empty']:>2}  تعارض {c['multi']}")

    if report["errors"]:
        print(f"\nمخالفات لقواعد الدوام ({len(report['errors'])}):")
        for e in report["errors"]:
            print("  ✗", e["msg"])
    groups = {}
    for w in report["warnings"]:
        groups.setdefault(w["type"], []).append(w["msg"])
    titles = {"section_missing": "شعب غير موجودة", "section_gaps": "شعب ناقصة", "load_diff": "فروقات النصاب",
              "section_clash": "أكثر من معلم في نفس الشعبة والحصة", "no_section": "خلايا بلا رقم شعبة"}
    for k, msgs in groups.items():
        print(f"\n{titles.get(k, k)} ({len(msgs)}):")
        for m in msgs:
            print("  •", m)
    if structural:
        print("\nأخطاء بنيوية في الملفات:")
        for e in structural:
            print("  ✗", e)
    else:
        print("\n✓ بنية الملفات سليمة.")

    if (strict and structural) or (enforce_rules and report["errors"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
