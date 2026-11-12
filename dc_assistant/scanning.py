"""Inventory and reconciliation, with explicit field provenance."""

from collections import defaultdict
import hashlib
from pathlib import Path

from .constants import ATTACHMENT_FILES, SUPPORTED_FILES
from .issues import add_issue, status_meaning
from .naming import NamingRule
from .pdf_checks import ScanCancelled, check_cancelled, inspect_pdf


def prepare_register(records, rule):
    lookup = defaultdict(list)
    invalid = []
    for record in records:
        parsed = rule.parse(record["number"])
        if not parsed:
            invalid.append(record)
            continue
        column_revision = rule.revision(record.get("revision"))
        if (
            column_revision
            and parsed["revision"]
            and column_revision != parsed["revision"]
        ):
            invalid.append(
                {
                    **record,
                    "invalid_reason": "إصدار الرقم داخل اللوج يختلف عن عمود الإصدار؛ لم يعتمد الربط",
                }
            )
            continue
        revision = column_revision or parsed["revision"]
        lookup[parsed["key"]].append(
            {**record, "key": parsed["key"], "revision": revision}
        )
    return lookup, invalid


def digest(path, cancel_event=None):
    checksum = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            check_cancelled(cancel_event)
            checksum.update(block)
    return checksum.hexdigest()


def _match_register(item, parsed, register, has_register, settings, rule):
    candidates = register.get(parsed["key"], [])
    exact = [
        r for r in candidates if r["revision"] and r["revision"] == parsed["revision"]
    ]
    unspecified = [r for r in candidates if not r["revision"]]
    matches = (exact or unspecified) if parsed["revision"] else candidates
    if has_register and not candidates:
        add_issue(item, "REGISTER_NOT_FOUND", "warning", "غير موجود في اللوج المستورد")
    elif candidates and not matches:
        add_issue(item, "REVISION_MISMATCH", "error", "الإصدار يختلف عن اللوج المستورد")
    if not parsed["revision"]:
        revision_in_template = any(part["role"] == "revision" for part in rule.parts)
        add_issue(
            item,
            "REVISION_UNSPECIFIED",
            "warning" if revision_in_template else "info",
            "إصدار الملف غير محدد في الاسم",
        )
    if len(matches) > 1:
        add_issue(
            item,
            "REGISTER_AMBIGUOUS",
            "error",
            "أكثر من سجل مطابق في اللوج؛ يلزم حسم الربط",
        )
        return
    if len(matches) != 1:
        return
    record = matches[0]
    item.update(
        title=record.get("title", ""),
        register_row=record["row"],
        register_source=record.get("source", ""),
        register_revision=record["revision"],
        register_discipline=record.get("discipline", ""),
        register_area=record.get("area", ""),
        register_status_raw=record.get("status", ""),
    )
    for field, label in (("discipline", "التخصص"), ("area", "المنطقة")):
        file_value = parsed[field].strip()
        register_value = str(record.get(field, "")).strip()
        if (
            file_value
            and register_value
            and rule.key(file_value) != rule.key(register_value)
        ):
            add_issue(
                item,
                f"REGISTER_{field.upper()}_MISMATCH",
                "warning",
                f"{label} يختلف: الاسم «{file_value}» واللوج «{register_value}»",
                filename_value=file_value,
                register_value=register_value,
            )
    code = str(record.get("status", "")).strip()
    if code and (not parsed["revision"] or not record["revision"]):
        add_issue(
            item,
            "STATUS_REVISION_UNSPECIFIED",
            "warning",
            "حالة اللوج غير مرتبطة بإصدار محدد؛ لم تُنقل",
        )
        return
    item["status"] = code
    item["status_meaning"] = status_meaning(code, settings)
    if code and not item["status_meaning"]:
        add_issue(
            item,
            "STATUS_UNDEFINED",
            "warning",
            f"كود الحالة «{code}» غير معرف في إعدادات هذا المشروع",
        )


def _check_duplicates(items, cancel_event):
    groups = defaultdict(list)
    for item in items:
        if item["key"]:
            groups[(item["key"], item["revision"], item["format"])].append(item)
    for group in groups.values():
        if len(group) < 2:
            continue
        for item in group:
            check_cancelled(cancel_event)
            try:
                item["hash"] = digest(item["path"], cancel_event)
            except OSError as exc:
                add_issue(
                    item, "FILE_READ_ERROR", "error", "تعذرت قراءة الملف: " + str(exc)
                )
        hashes = {item["hash"] for item in group if item["hash"]}
        identical = len(hashes) == 1 and all(item["hash"] for item in group)
        for item in group:
            if identical:
                add_issue(
                    item,
                    "DUPLICATE_IDENTICAL",
                    "info",
                    "نسخ متطابقة لنفس الرقم والإصدار والصيغة",
                )
            else:
                add_issue(
                    item,
                    "DUPLICATE_CONFLICT",
                    "error",
                    "ملفات مختلفة لنفس الرقم والإصدار والصيغة",
                )


def scan_batch(
    folder, settings, records=(), check_pdf=True, progress=None, cancel_event=None
):
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError("فولدر الدفعة غير موجود")
    rule = NamingRule(settings)
    register, invalid_register = prepare_register(records, rule)
    excluded = {
        value.casefold() for value in settings.get("excluded_folders", []) if value
    }
    inventory = []
    for path in folder.rglob("*"):
        check_cancelled(cancel_event)
        if not path.is_file() or path.name.startswith("~$"):
            continue
        if any(
            part.casefold() in excluded for part in path.relative_to(folder).parts[:-1]
        ):
            continue
        inventory.append(path)
    inventory.sort()
    files = [path for path in inventory if path.suffix.lower() in SUPPORTED_FILES]
    attachments = [
        {"path": str(path), "file": path.name, "format": path.suffix[1:].upper()}
        for path in inventory
        if path.suffix.lower() in ATTACHMENT_FILES
    ]
    items = []
    for index, path in enumerate(files, start=1):
        check_cancelled(cancel_event)
        if progress:
            progress(index, len(files), path.name)
        item = {
            "path": str(path),
            "file": path.name,
            "format": path.suffix[1:].upper(),
            "number": "",
            "revision": "",
            "discipline": "",
            "area": "",
            "title": "",
            "status": "",
            "status_meaning": "",
            "issues": [],
            "issue_details": [],
            "key": "",
            "register_row": "",
            "pdf_check": "لم يطلب",
            "hash": "",
            "pdf_verified": False,
            "pdf_check_state": "not_requested",
        }
        parsed = rule.parse(path.name)
        if parsed:
            item.update(parsed)
            _match_register(item, parsed, register, bool(records), settings, rule)
        else:
            add_issue(
                item,
                "NAME_UNRECOGNIZED",
                "warning",
                "الاسم خارج نموذج التسمية الحالي؛ حدد نوع المستند أو راجع القاعدة",
            )
        if check_pdf and path.suffix.lower() == ".pdf":
            inspect_pdf(item, path, rule, parsed, settings, cancel_event)
        items.append(item)
    _check_duplicates(items, cancel_event)
    check_cancelled(cancel_event)
    pdf_keys = {
        item["key"] for item in items if item["format"] == "PDF" and item["key"]
    }
    pdf_versions = {
        (item["key"], item["revision"])
        for item in items
        if item["format"] == "PDF" and item["key"]
    }
    missing = []
    for key, entries in register.items():
        for record in entries:
            present = (
                (key, record["revision"]) in pdf_versions
                if record["revision"]
                else key in pdf_keys
            )
            if not present:
                missing.append(record)
    return {
        "items": items,
        "attachments": attachments,
        "register_sources": sorted({r["source"] for r in records if r.get("source")}),
        "register_not_in_batch": missing,
        "invalid_register": invalid_register,
        "summary": {
            "files": len(items),
            "pdf": sum(item["format"] == "PDF" for item in items),
            "dwg": sum(item["format"] == "DWG" for item in items),
            "attachments": len(attachments),
            "with_observations": sum(bool(item["issues"]) for item in items),
            "with_warnings_or_errors": sum(
                any(
                    issue["severity"] in {"warning", "error"}
                    for issue in item["issue_details"]
                )
                for item in items
            ),
        },
    }
