"""Bounded text reading; a text hit never verifies the title-block location."""

import json
import multiprocessing
from pathlib import Path
import shutil
import tempfile
import time
import uuid

from .issues import add_issue


class ScanCancelled(Exception):
    """Cancellation discards the partial scan, without changing saved batches."""


def check_cancelled(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise ScanCancelled("أُلغي الفحص؛ لم تحفظ نتيجة جزئية")


def _read_pdfium(path):
    from contextlib import closing
    import pypdfium2 as pdfium

    with pdfium.PdfDocument(str(path)) as document:
        count = len(document)
        if not count:
            return {"text": "", "pages": 0, "reader": "pypdfium2"}
        with closing(document[0]) as page, closing(page.get_textpage()) as text:
            return {
                "text": text.get_text_bounded(),
                "pages": count,
                "reader": "pypdfium2",
            }


def _read_pypdf(path):
    from pypdf import PdfReader

    with open(path, "rb") as stream:
        document = PdfReader(stream)
        count = len(document.pages)
        text = document.pages[0].extract_text() or "" if count else ""
    return {"text": text, "pages": count, "reader": "pypdf"}


def _read_pdfminer(path):
    from pdfminer.high_level import extract_text
    from pdfminer.pdfpage import PDFPage

    with open(path, "rb") as stream:
        count = sum(1 for _ in PDFPage.get_pages(stream))
    return {
        "text": extract_text(str(path), page_numbers={0}) or "",
        "pages": count,
        "reader": "pdfminer",
    }


def read_first_page(path, fallback=True, reader="auto"):
    """Fast CAD text reading, with explicit alternate-reader diagnostics."""
    readers = {
        "pypdfium2": _read_pdfium,
        "pypdf": _read_pypdf,
        "pdfminer": _read_pdfminer,
    }
    if reader == "auto":
        order = ["pypdfium2", "pypdf", "pdfminer"] if fallback else ["pypdfium2"]
    elif reader in readers:
        order = [reader]
        if reader == "pypdf" and fallback:
            order.append("pdfminer")
    else:
        raise ValueError("Unknown PDF reader: " + reader)
    empty_result = None
    last_error = None
    for name in order:
        try:
            result = readers[name](path)
            if result["text"].strip():
                return result
            empty_result = result
        except Exception as exc:
            last_error = exc
    if empty_result is not None:
        return empty_result
    raise last_error


def _pdf_worker(output_path, path, fallback, reader):
    try:
        message = {"result": read_first_page(path, fallback, reader)}
    except Exception as exc:
        message = {"error": f"{type(exc).__name__}: {exc}"[:500]}
    destination = Path(output_path)
    pending = destination.with_suffix(".pending")
    pending.write_text(json.dumps(message, ensure_ascii=False), encoding="utf-8")
    pending.replace(destination)


def read_pdf_isolated(path, settings, cancel_event=None, *, reader="auto", worker=None):
    check_cancelled(cancel_event)
    timeout = float(settings.get("pdf_timeout_seconds", 30))
    if not 0 < timeout <= 300:
        raise ValueError("مهلة قراءة PDF يجب أن تكون أكبر من صفر ولا تتجاوز 300 ثانية")
    context = multiprocessing.get_context("spawn")
    # File IPC works on Windows hosts that restrict named-pipe creation.
    scratch = Path(tempfile.gettempdir()) / "DC-Assistant-workers"
    scratch.mkdir(exist_ok=True)
    job = scratch / uuid.uuid4().hex
    job.mkdir()
    output = job / "result.json"
    process = context.Process(
        target=worker or _pdf_worker,
        args=(str(output), str(path), settings.get("pdf_fallback", True), reader),
        daemon=True,
    )
    started = False
    deadline = time.monotonic() + timeout
    try:
        process.start()
        started = True
        while True:
            check_cancelled(cancel_event)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"تجاوزت قراءة PDF مهلة {timeout:g} ثانية")
            if output.exists():
                message = json.loads(output.read_text(encoding="utf-8"))
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message["result"]
            if not process.is_alive():
                if not output.exists():
                    raise RuntimeError("توقف قارئ PDF قبل إرجاع النتيجة")
                continue
            time.sleep(min(0.05, remaining))
    finally:
        if started:
            process.join(0.2)
            if process.is_alive():
                process.terminate()
                process.join(1)
            if process.is_alive():
                process.kill()
                process.join(1)
            process.close()
        job.resolve().relative_to(scratch.resolve())
        shutil.rmtree(job)


def inspect_pdf(item, path, rule, parsed, settings, cancel_event=None):
    item["pdf_verified"] = False
    try:
        result = read_pdf_isolated(path, settings, cancel_event)
        item["pdf_pages"] = result["pages"]
        item["pdf_reader"] = result["reader"]
        text = result["text"]
        item["pdf_check_state"] = "unverified"
        add_issue(
            item,
            "PDF_TITLEBLOCK_UNVERIFIED",
            "warning",
            "لم تتحقق خانة رقم اللوحة والإصدار؛ الفحص بحث نصي في أول صفحة فقط",
        )
        if result["pages"] > 1:
            add_issue(
                item,
                "PDF_MULTIPAGE_UNCHECKED",
                "warning",
                f"الملف {result['pages']} صفحات؛ الصفحات بعد الأولى لم تفحص",
            )
        if not parsed:
            item["pdf_check"] = "تعذر ربط اسم الملف؛ خانة اللوحة غير متحققة"
            return
        found = rule.find_in_pdf_text(text)
        hit = rule.expected_in_pdf_text(text, parsed)
        item["pdf_text_hit"] = hit
        if hit:
            item["pdf_check"] = (
                "عُثر على النص المتوقع في أول صفحة؛ خانة اللوحة غير متحققة"
            )
            other = [
                value["number"] for value in found if value["key"] != parsed["key"]
            ]
            if other:
                add_issue(
                    item,
                    "PDF_MULTIPLE_IDENTIFIERS",
                    "warning",
                    "توجد أرقام مستندات أخرى بالصفحة؛ قد يكون النص المطلوب مرجعًا",
                    other_numbers=other,
                )
        elif not text.strip():
            item["pdf_check_state"] = "no_text"
            item["pdf_check"] = "لم يقرأ نص في أول صفحة؛ تحتاج قراءة يدوية أو OCR"
            add_issue(item, "PDF_NO_TEXT", "warning", item["pdf_check"])
        else:
            item["pdf_check_state"] = "not_found"
            item["pdf_check"] = (
                "لم يعثر على نص الرقم والإصدار المتوقعين؛ خانة اللوحة غير متحققة"
            )
            add_issue(item, "PDF_EXPECTED_NOT_FOUND", "warning", item["pdf_check"])
        if result["reader"] == "pdfminer":
            item["pdf_check"] += " — باستخدام القراءة الموسعة"
    except ScanCancelled:
        raise
    except Exception as exc:
        item["pdf_check_state"] = "unreadable"
        item["pdf_check"] = "تعذرت قراءة PDF؛ لم يتم التحقق"
        code = "PDF_TIMEOUT" if isinstance(exc, TimeoutError) else "PDF_READ_ERROR"
        add_issue(item, code, "error", "خطأ قراءة PDF: " + str(exc)[:250])
