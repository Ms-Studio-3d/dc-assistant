"""Create an independent Excel report with literal cell values."""

import math
import os
from pathlib import Path
import re
import uuid

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .constants import ROLE_LABELS
from .issues import pdf_check_label, status_meaning

HEADER_WIDTHS = {
    "اسم الملف": 60,
    "رقم المستند": 58,
    "الإصدار": 12,
    "العنوان من اللوج": 72,
    "العنوان": 72,
    "الملاحظات": 75,
    "المسار": 95,
    "فحص نص PDF": 65,
    "المصدر": 85,
    "القيمة": 100,
}


def _literal(value):
    if value is None:
        return ""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value))[:32767]


def write_xlsx(path, sheets):
    """Atomic output; strings beginning with '=' remain literal strings."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.stem}-{uuid.uuid4().hex}.tmp.xlsx")
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    try:
        for name, rows in sheets.items():
            sheet = workbook.create_sheet(name)
            sheet.sheet_view.rightToLeft = True
            sheet.sheet_view.showGridLines = False
            sheet.freeze_panes = "A2"
            width = max((len(row) for row in rows), default=1)
            widths = [
                HEADER_WIDTHS.get(
                    str(rows[0][index]) if rows and index < len(rows[0]) else "", 28
                )
                for index in range(width)
            ]
            for index, column_width in enumerate(widths, start=1):
                sheet.column_dimensions[get_column_letter(index)].width = column_width
            for row_number, row in enumerate(rows, start=1):
                lines = 1
                for column_number, value in enumerate(row, start=1):
                    cell = sheet.cell(row_number, column_number)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        cell.value = value
                    else:
                        cell.value = _literal(value)
                        cell.data_type = "s"
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
                    if row_number == 1:
                        cell.font = Font(
                            name="Arial", size=11, bold=True, color="FFFFFF"
                        )
                        cell.fill = PatternFill("solid", fgColor="234B76")
                        cell.alignment = Alignment(
                            horizontal="center", vertical="center", wrap_text=True
                        )
                    else:
                        cell.font = Font(name="Arial", size=11)
                    cell_lines = sum(
                        max(
                            1,
                            math.ceil(
                                len(line) / max(1, widths[column_number - 1] - 2)
                            ),
                        )
                        for line in str(value if value is not None else "").split("\n")
                    )
                    lines = max(lines, cell_lines)
                sheet.row_dimensions[row_number].height = min(
                    400, max(30, lines * 16 + 8)
                )
            if rows:
                sheet.auto_filter.ref = f"A1:{get_column_letter(width)}{len(rows)}"
        workbook.save(temporary)
        temporary.replace(path)
    finally:
        workbook.close()
        if temporary.exists():
            temporary.unlink()


def export_results(path, project, results):
    target = os.path.normcase(str(Path(path).resolve()))
    sources = [
        *results.get("register_sources", []),
        *(item["path"] for item in results["items"]),
        *(item["path"] for item in results.get("attachments", [])),
    ]
    if any(
        target == os.path.normcase(str(Path(source).resolve())) for source in sources
    ):
        raise ValueError("اختر اسم ملف جديد للتقرير؛ هذا المسار من ملفات المصدر")
    settings = project["settings"]
    items = [
        [
            "اسم الملف",
            "رقم المستند",
            "الإصدار",
            "إصدار اللوج",
            "العنوان من اللوج",
            "التخصص من الاسم",
            "التخصص من اللوج",
            "المنطقة من الاسم",
            "المنطقة من اللوج",
            "كود الحالة من اللوج",
            "الحالة الخام بالسجل",
            "معنى الحالة",
            "الصيغة",
            "فحص نص PDF",
            "الملاحظات",
            "أكواد الملاحظات",
            "درجات الخطورة",
            "صف اللوج",
            "المسار",
        ]
    ]
    for item in results["items"]:
        details = item.get("issue_details", [])
        items.append(
            [
                item["file"],
                item["number"],
                item["revision"],
                item.get("register_revision", ""),
                item["title"],
                item["discipline"],
                item.get("register_discipline", ""),
                item["area"],
                item.get("register_area", ""),
                item["status"],
                item.get("register_status_raw", item["status"]),
                item.get("status_meaning", status_meaning(item["status"], settings)),
                item["format"],
                pdf_check_label(item),
                "؛ ".join(item["issues"]),
                "؛ ".join(issue["code"] for issue in details),
                "؛ ".join(issue["severity"] for issue in details),
                item["register_row"],
                item["path"],
            ]
        )
    absent = [["رقم المستند", "الإصدار", "العنوان", "صف اللوج", "المصدر"]] + [
        [row["number"], row["revision"], row["title"], row["row"], row["source"]]
        for row in results["register_not_in_batch"]
    ]
    invalid = [["رقم المستند", "العنوان", "صف اللوج", "الملاحظة"]] + [
        [
            row["number"],
            row["title"],
            row["row"],
            row.get("invalid_reason", "لا يطابق قواعد المشروع الحالية"),
        ]
        for row in results["invalid_register"]
    ]
    snapshot = results.get("context", {})
    context = [
        ["البند", "القيمة"],
        ["المشروع", snapshot.get("project_name", project["name"])],
        ["كود المشروع", snapshot.get("project_code", project["code"])],
        ["فولدر الدفعة", snapshot.get("folder", "")],
        ["اللوج المستخدم", snapshot.get("register_source", "")],
        ["نطاق المطابقة", "الدفعة المختارة مقابل اللوج المستورد"],
        [
            "المستندات غير الموجودة",
            "سجلات لا يوجد لها PDF مطابق بالرقم والإصدار في هذه الدفعة فقط",
        ],
        [
            "فحص PDF",
            "بحث نصي في أول صفحة فقط؛ خانة اللوحة والإصدار غير متحققة، والصفحات التالية لم تفحص",
        ],
        ["مثال التسمية", settings.get("example", "")],
        ["بدائل كود المشروع", ", ".join(settings.get("project_aliases", []))],
        ["الفولدرات المستبعدة", ", ".join(settings.get("excluded_folders", []))],
        [
            "أجزاء الاسم",
            "\n".join(
                ROLE_LABELS[part["role"]] + ": " + part["sample"]
                for part in settings.get("parts", [])
            ),
        ],
        [
            "تعريف الحالات وقت الفحص",
            "\n".join(
                f"{code} = {meaning}"
                for code, meaning in settings.get("statuses", {}).items()
            ),
        ],
    ]
    attachments = [["اسم الملف", "الصيغة", "المسار"]] + [
        [row["file"], row["format"], row["path"]]
        for row in results.get("attachments", [])
    ]
    write_xlsx(
        path,
        {
            "المطابقة": items,
            "غير موجود في الدفعة": absent,
            "سجلات تحتاج تعريف": invalid,
            "ملفات إضافية": attachments,
            "نطاق التقرير": context,
        },
    )
