"""Read Excel registers with explicit diagnostics and deterministic cleanup."""

from contextlib import ExitStack
from datetime import date, datetime
from itertools import zip_longest
import math
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

import openpyxl
from openpyxl.utils import get_column_letter

FIELDS = ("number", "title", "revision", "discipline", "area", "status")


def _cached_empty_formulas(path, sheet_name):
    """Distinguish a stored empty string from an absent formula cache value."""
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    office_rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package_rel = "http://schemas.openxmlformats.org/package/2006/relationships"
    with zipfile.ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheet = next(
            item
            for item in workbook.findall(f"{{{main}}}sheets/{{{main}}}sheet")
            if item.get("name") == sheet_name
        )
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relation = next(
            item
            for item in relationships.findall(f"{{{package_rel}}}Relationship")
            if item.get("Id") == sheet.get(f"{{{office_rel}}}id")
        )
        target = relation.get("Target")
        member = (
            target.lstrip("/")
            if target.startswith("/")
            else posixpath.normpath("xl/" + target)
        )
        empty = set()
        with archive.open(member) as stream:
            for _, element in ET.iterparse(stream, events=("end",)):
                if element.tag == f"{{{main}}}c":
                    if (
                        element.get("t") == "str"
                        and element.find(f"{{{main}}}f") is not None
                        and element.find(f"{{{main}}}v") is not None
                    ):
                        empty.add(element.get("r"))
                    element.clear()
        return empty


def _workbook(stack, path, *, data_only):
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=data_only)
    stack.callback(workbook.close)
    return workbook


def _sheet(workbook, name):
    if name not in workbook.sheetnames:
        raise ValueError(f"الشيت المحدد غير موجود: {name}")
    sheet = workbook[name]
    # Some producers publish dimensions that omit real XML rows/columns.
    sheet.reset_dimensions()
    return sheet


def excel_sheets(path):
    with ExitStack() as stack:
        workbook = _workbook(stack, path, data_only=True)
        if not workbook.sheetnames:
            raise ValueError("ملف Excel لا يحتوي شيتات")
        return workbook.sheetnames[:]


def excel_columns(path, sheet, header_row):
    if not isinstance(header_row, int) or header_row < 1:
        raise ValueError("صف العناوين يبدأ من 1")
    with ExitStack() as stack:
        workbook = _workbook(stack, path, data_only=True)
        worksheet = _sheet(workbook, sheet)
        row = next(worksheet.iter_rows(min_row=header_row, max_row=header_row), ())
        if not row or not any(cell.value is not None for cell in row):
            raise ValueError(
                f"صف العناوين {header_row} فارغ أو خارج بيانات الشيت {sheet}"
            )
        return [
            (index, str(cell.value).strip() if cell.value is not None else "")
            for index, cell in enumerate(row)
        ]


def _text(value):
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _identifier(cell):
    if cell is None:
        return ""
    value = cell.value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("رقم المستند يحتوي قيمة رقمية غير صالحة")
        if isinstance(value, int) or value.is_integer():
            digits = str(int(value))
            # Honor an explicit Excel zero format, never guess a project's width.
            if re.fullmatch(r"0+", cell.number_format or ""):
                digits = digits.zfill(len(cell.number_format))
            return digits
    return _text(value).strip()


def read_register(path, mapping):
    number_column = mapping.get("number")
    if (
        not isinstance(number_column, int)
        or isinstance(number_column, bool)
        or number_column < 0
    ):
        raise ValueError("حدد عمود رقم المستند")
    header_row = mapping.get("header_row", 1)
    first_row = mapping.get("data_start_row", header_row + 1)
    if not isinstance(first_row, int) or header_row < 1 or first_row <= header_row:
        raise ValueError("أول صف بيانات يجب أن يكون بعد صف العناوين")
    for key in FIELDS:
        index = mapping.get(key)
        if index is not None and (
            not isinstance(index, int) or isinstance(index, bool) or index < 0
        ):
            raise ValueError(f"عمود غير صالح: {key}")

    records = []
    warnings = []
    skipped = 0
    cached_empty = None
    with ExitStack() as stack:
        cached = _sheet(_workbook(stack, path, data_only=True), mapping["sheet"])
        formulas = _sheet(_workbook(stack, path, data_only=False), mapping["sheet"])
        pairs = zip_longest(
            cached.iter_rows(min_row=first_row),
            formulas.iter_rows(min_row=first_row),
            fillvalue=(),
        )
        for row_number, (values, raw) in enumerate(pairs, start=first_row):

            def selected(row, key):
                index = mapping.get(key)
                return row[index] if index is not None and index < len(row) else None

            raw_number = selected(raw, "number")
            number_cell = selected(values, "number")
            if (raw_number is None or raw_number.value in (None, "")) and (
                number_cell is None or number_cell.value in (None, "")
            ):
                # Formula-filled blank template rows are not document records.
                meaningful = any(
                    (cell := selected(values, key)) is not None
                    and cell.value not in (None, "")
                    for key in FIELDS
                    if key != "number"
                )
                if meaningful:
                    skipped += 1
                    warnings.append(
                        f"الشيت {cached.title}، الصف {row_number}: بيانات بلا رقم مستند"
                    )
                continue

            incomplete = False
            for key in FIELDS:
                formula_cell = selected(raw, key)
                value_cell = selected(values, key)
                if value_cell is not None and value_cell.data_type == "e":
                    warnings.append(
                        f"الشيت {cached.title}، الصف {row_number}: خطأ Excel في حقل {key}"
                    )
                    incomplete = True
                elif formula_cell is not None and formula_cell.data_type == "f":
                    address = f"{get_column_letter(mapping[key] + 1)}{row_number}"
                    stored_empty = False
                    if (
                        value_cell is not None
                        and value_cell.value is None
                        and value_cell.data_type == "str"
                    ):
                        if cached_empty is None:
                            cached_empty = _cached_empty_formulas(path, cached.title)
                        stored_empty = address in cached_empty
                    if value_cell is None or (
                        value_cell.value is None and not stored_empty
                    ):
                        address = f"{get_column_letter(mapping[key] + 1)}{row_number}"
                        warnings.append(
                            f"{cached.title}!{address}: معادلة بلا نتيجة محفوظة؛ أعد حساب الملف واحفظه في Excel"
                        )
                        incomplete = True
            if incomplete:
                skipped += 1
                continue

            number_cell = selected(values, "number")
            number = _identifier(number_cell)
            fields = {
                key: (
                    _text(cell.value)
                    if (cell := selected(values, key)) is not None
                    else ""
                )
                for key in FIELDS
                if key != "number"
            }
            if not number:
                if any(value.strip() for value in fields.values()):
                    skipped += 1
                    warnings.append(
                        f"الشيت {cached.title}، الصف {row_number}: بيانات بلا رقم مستند"
                    )
                continue
            records.append(
                {
                    "number": number,
                    **fields,
                    "row": row_number,
                    "source": str(path),
                    "sheet": cached.title,
                    "number_raw": _text(number_cell.value),
                    "number_format": number_cell.number_format,
                }
            )

    if skipped:
        warnings.insert(
            0,
            f"قُرئ {len(records)} سجل؛ تعذر استيراد {skipped} صف. لم يعتمد الاستيراد في الواجهة.",
        )
    if not records:
        warnings.append(
            "لم تُقرأ أرقام مستندات. راجع الشيت وصف العناوين وعمود رقم المستند."
        )
    return records, warnings
