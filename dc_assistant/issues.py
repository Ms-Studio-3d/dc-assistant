"""Stable issue codes alongside human-readable, backwards-compatible messages."""


def add_issue(item, code, severity, message, **details):
    item.setdefault("issues", []).append(message)
    item.setdefault("issue_details", []).append(
        {
            "code": code,
            "severity": severity,
            "message": message,
            **details,
        }
    )


def status_meaning(code, settings):
    return settings.get("statuses", {}).get(code, "") if code else ""


def format_status(item, settings):
    code = item.get("status", "")
    meaning = item.get("status_meaning", status_meaning(code, settings))
    return f"{code} — {meaning}" if code and meaning else code


def pdf_check_label(item):
    label = item.get("pdf_check", "")
    if item.get("format") == "PDF" and "pdf_check_state" not in item:
        return label + " — نتيجة قديمة لبحث نصي؛ خانة اللوحة غير متحققة"
    return label
