from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
import zipfile
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

ROLE_LABELS = {
    "literal": "جزء ثابت", "project": "كود المشروع", "discipline": "التخصص",
    "area": "المنطقة / المبنى", "number": "رقم تسلسلي", "revision": "الإصدار",
    "originator": "جهة الإصدار", "recipient": "الجهة المستلمة", "type": "نوع المستند",
}
DEFAULT_STATUSES = {"A": "Approved", "B": "Approved with Comments", "C": "Revise and Resubmit", "U": "Under Review"}
SUPPORTED_FILES = {".pdf", ".dwg"}
ATTACHMENT_FILES = {".xlsx", ".xls", ".rvt", ".ifc", ".nwc", ".jpg", ".jpeg", ".png", ".pcp", ".docx"}


def now():
    return datetime.now(timezone.utc).isoformat()


def new_id():
    return uuid.uuid4().hex


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS projects(
            id TEXT PRIMARY KEY, name TEXT NOT NULL, code TEXT NOT NULL,
            settings TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS registers(
            project_id TEXT PRIMARY KEY REFERENCES projects(id), source TEXT NOT NULL,
            mapping TEXT NOT NULL, records TEXT NOT NULL, imported TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS batches(
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
            folder TEXT NOT NULL, created TEXT NOT NULL, settings TEXT NOT NULL,
            results TEXT NOT NULL);
        """)
        self.db.commit()

    def projects(self):
        return [self._project(row) for row in self.db.execute("SELECT * FROM projects ORDER BY name COLLATE NOCASE")]

    @staticmethod
    def _project(row):
        return {**dict(row), "settings": json.loads(row["settings"])} if row else None

    def get_project(self, project_id):
        return self._project(self.db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())

    def save_project(self, name, code, settings, project_id=None):
        if not name.strip():
            raise ValueError("اسم المشروع مطلوب")
        if settings.get("parts"):
            NamingRule(settings)  # Validate before storing.
        project_id = project_id or new_id()
        old = self.get_project(project_id)
        with self.db:
            self.db.execute("""INSERT INTO projects VALUES(?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,code=excluded.code,
                settings=excluded.settings,updated=excluded.updated""",
                (project_id, name.strip(), code, json.dumps(settings, ensure_ascii=False), old["created"] if old else now(), now()))
        return project_id

    def save_register(self, project_id, source, mapping, records):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO registers VALUES(?,?,?,?,?)", (project_id, str(source), json.dumps(mapping, ensure_ascii=False), json.dumps(records, ensure_ascii=False), now()))

    def get_register(self, project_id):
        row = self.db.execute("SELECT * FROM registers WHERE project_id=?", (project_id,)).fetchone()
        if row is None:
            return None
        return {**dict(row), "mapping": json.loads(row["mapping"]), "records": json.loads(row["records"])}

    def save_batch(self, project_id, folder, settings, results):
        batch_id = new_id()
        with self.db:
            self.db.execute("INSERT INTO batches VALUES(?,?,?,?,?,?)", (batch_id, project_id, str(folder), now(), json.dumps(settings, ensure_ascii=False), json.dumps(results, ensure_ascii=False)))
        return batch_id

    def batches(self, project_id):
        return [dict(row) for row in self.db.execute("SELECT id,folder,created FROM batches WHERE project_id=? ORDER BY created DESC", (project_id,))]

    def get_batch(self, project_id, batch_id):
        row = self.db.execute("SELECT * FROM batches WHERE id=? AND project_id=?", (batch_id, project_id)).fetchone()
        return {**dict(row), "results": json.loads(row["results"]), "settings": json.loads(row["settings"])} if row else None

    def close(self):
        self.db.close()


class NamingRule:
    """Compile only user-configured parts. No implicit zero stripping or aliases."""
    def __init__(self, settings):
        self.settings = settings
        self.parts = settings.get("parts", [])
        self.separator = settings.get("separator", "-")
        self.ignore_case = settings.get("ignore_case", False)
        if not self.parts or not self.separator:
            raise ValueError("حدد مثال التسمية وأجزاءه أولًا")
        roles = [p["role"] for p in self.parts if p["role"] != "literal"]
        if "number" not in roles:
            raise ValueError("حدد الجزء الذي يمثل رقم اللوحة التسلسلي في المثال")
        if len(roles) != len(set(roles)):
            raise ValueError("كل نوع جزء متغير يُستخدم مرة واحدة. الأجزاء المتكررة يمكن ضبطها كأجزاء ثابتة.")
        if "revision" in roles and self.parts[-1]["role"] != "revision":
            raise ValueError("هذه النسخة تدعم الإصدار في آخر الاسم، أو في عمود منفصل باللوج")
        self.optional_revision = bool(settings.get("optional_revision", True))
        sep = re.escape(self.separator)
        pieces = []
        for i, part in enumerate(self.parts):
            role, sample = part["role"], str(part["sample"])
            if role not in ROLE_LABELS or not sample:
                raise ValueError("راجع تعريف أجزاء اسم اللوحة")
            if role == "literal":
                token = re.escape(sample)
            elif role == "project":
                codes = list(dict.fromkeys([sample] + settings.get("project_aliases", [])))
                token = "(?P<project>" + "|".join(re.escape(x) for x in sorted(codes, key=len, reverse=True)) + ")"
            else:
                token = "(?P<" + role + ">[A-Za-z0-9]+)"
            chunk = (sep if i else "") + token
            if role == "revision" and self.optional_revision:
                chunk = "(?:" + chunk + ")?"
            pieces.append(chunk)
        flags = re.IGNORECASE if self.ignore_case else 0
        self.pattern = re.compile("".join(pieces), flags)

    def key(self, value):
        return value.casefold() if self.ignore_case else value

    def revision(self, value):
        if value is None or value == "":
            return ""
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        value = str(value).strip()
        sample = next((p["sample"] for p in self.parts if p["role"] == "revision"), "")
        if sample.isdigit() and re.fullmatch(r"\d+\.0", value):
            value = value[:-2]
        if sample.isdigit() and value.isdigit():
            return value.zfill(len(sample))
        return value

    def parse(self, value):
        value = str(value).strip()
        value = re.sub(r"\.(pdf|dwg)$", "", value, flags=re.IGNORECASE)
        # Ignore whitespace around an explicitly configured separator, not zeroes.
        value = re.sub(r"\s*" + re.escape(self.separator) + r"\s*", lambda _: self.separator, value)
        match = self.pattern.fullmatch(value)
        if not match:
            return None
        groups = match.groupdict()
        raw_parts = value.split(self.separator)
        doc_parts = raw_parts[:]
        rev = groups.get("revision") or ""
        if rev:
            doc_parts.pop()
        original_number = self.separator.join(doc_parts)
        canonical = doc_parts[:]
        for i, part in enumerate(self.parts):
            if part["role"] == "project":
                canonical[i] = part["sample"]
        number = self.separator.join(canonical)
        return {"number": original_number, "key": self.key(number), "revision": self.revision(rev),
                "discipline": groups.get("discipline", ""), "area": groups.get("area", "")}

    def find_in_pdf_text(self, text):
        # CAD exporters can insert spaces/newlines within an identifier.
        compact = re.sub(r"\s*" + re.escape(self.separator) + r"\s*", lambda _: self.separator, text)
        found = {}
        for match in self.pattern.finditer(compact):
            # Do not accept a valid-looking prefix of a longer identifier.
            if match.start() and compact[match.start()-1].isalnum():
                continue
            if match.end() < len(compact) and compact[match.end()].isalnum():
                continue
            item = self.parse(match.group())
            if item:
                found[(item["key"], item["revision"])] = item
        return list(found.values())

    def expected_in_pdf_text(self, text, parsed):
        """Verify an expected identifier despite character-by-character CAD text runs."""
        parts=parsed["number"].split(self.separator)
        project_index=next((i for i,p in enumerate(self.parts) if p["role"]=="project"),None)
        variants=[parts]
        if project_index is not None:
            variants=[]
            for code in [self.parts[project_index]["sample"]]+self.settings.get("project_aliases",[]):
                variant=parts[:];variant[project_index]=code;variants.append(variant)
        for variant in variants:
            expected=self.separator.join(variant)
            if parsed["revision"]:expected+=self.separator+parsed["revision"]
            pattern=r"(?<![A-Za-z0-9])"+r"\s*".join(re.escape(c) for c in expected)+r"(?![A-Za-z0-9])"
            if re.search(pattern,text,re.IGNORECASE if self.ignore_case else 0):return True
        return False


def excel_sheets(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    names = wb.sheetnames[:]
    wb.close()
    return names


def excel_columns(path, sheet, header_row):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    row = next(wb[sheet].iter_rows(min_row=header_row, max_row=header_row))
    result = [(i, str(c.value).strip() if c.value is not None else "") for i, c in enumerate(row)]
    wb.close()
    return result


def read_register(path, mapping):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    records = []
    warnings = []
    sh = wb[mapping["sheet"]]
    first_row=mapping.get("data_start_row",mapping["header_row"]+1)
    for rownum, row in enumerate(sh.iter_rows(min_row=first_row, values_only=True), start=first_row):
        def cell(key):
            i = mapping.get(key)
            v = row[i] if i is not None and i < len(row) else None
            if isinstance(v, datetime):
                return v.isoformat()
            return "" if v is None else str(v)
        number = cell("number").strip()
        if not number:
            continue
        records.append({"number": number, "title": cell("title"), "revision": cell("revision"),
                        "discipline": cell("discipline"), "area": cell("area"), "status": cell("status"),
                        "row": rownum, "source": str(path), "sheet": sh.title})
    wb.close()
    if not records:
        warnings.append("لم تُقرأ أرقام مستندات. راجع الشيت وصف العناوين وعمود رقم المستند.")
    return records, warnings


def prepare_register(records, rule):
    lookup = defaultdict(list)
    invalid = []
    for rec in records:
        parsed = rule.parse(rec["number"])
        if not parsed:
            invalid.append(rec)
            continue
        revision = rule.revision(rec.get("revision")) or parsed["revision"]
        enriched = {**rec, "key": parsed["key"], "revision": revision}
        lookup[parsed["key"]].append(enriched)
    return lookup, invalid


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def scan_batch(folder, settings, records=(), check_pdf=True, progress=None):
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError("فولدر الدفعة غير موجود")
    rule = NamingRule(settings)
    register, invalid_register = prepare_register(records, rule)
    excluded = {x.casefold() for x in settings.get("excluded_folders", []) if x}
    inventory = sorted(p for p in folder.rglob("*") if p.is_file() and not p.name.startswith("~$") and
                   not any(part.casefold() in excluded for part in p.relative_to(folder).parts[:-1]))
    files=[p for p in inventory if p.suffix.lower() in SUPPORTED_FILES]
    attachments=[{"path":str(p),"file":p.name,"format":p.suffix.lower()[1:].upper()} for p in inventory if p.suffix.lower() in ATTACHMENT_FILES]
    results = []
    for index, path in enumerate(files):
        if progress:
            progress(index+1, len(files), path.name)
        item = {"path": str(path), "file": path.name, "format": path.suffix.lower()[1:].upper(), "number": "",
                "revision": "", "discipline": "", "area": "", "title": "", "status": "", "issues": [],
                "key": "", "register_row": "", "pdf_check": "لم يُطلب", "hash": ""}
        parsed = rule.parse(path.name)
        try:
            item["hash"] = digest(path)
        except OSError as exc:
            item["issues"].append("تعذرت قراءة الملف: " + str(exc))
        if not parsed:
            item["issues"].append("الاسم خارج نموذج التسمية الحالي؛ حدّد نوع المستند أو راجع القاعدة")
        else:
            item.update(parsed)
            candidates = register.get(parsed["key"], [])
            exact = [r for r in candidates if r["revision"] and r["revision"] == parsed["revision"]]
            unspecified = [r for r in candidates if not r["revision"]]
            matches = (exact or unspecified) if parsed["revision"] else candidates
            if records and not candidates:
                item["issues"].append("غير موجود في اللوج المستورد")
            elif candidates and not matches:
                item["issues"].append("الإصدار يختلف عن اللوج المستورد")
            if not parsed["revision"]:
                item["issues"].append("إصدار الملف غير محدد في الاسم")
            if len(matches) > 1:
                item["issues"].append("أكثر من سجل مطابق في اللوج؛ يلزم حسم الربط")
            elif len(matches) == 1:
                rec = matches[0]
                item.update(title=rec.get("title", ""), status=rec.get("status", ""), register_row=rec["row"])
                if not parsed["revision"]:
                    item["status"]=""
                # A status belongs to the revision explicitly read, not an arbitrary latest column.
                if not rec["revision"] and parsed["revision"]:
                    item["status"] = ""
                    if rec.get("status"):
                        item["issues"].append("حالة اللوج غير مرتبطة بإصدار محدد؛ لم تُنقل")
        if check_pdf and path.suffix.lower() == ".pdf":
            try:
                from pypdf import PdfReader
                fallback=False
                try:
                    reader = PdfReader(path)
                    text = reader.pages[0].extract_text() or "" if reader.pages else ""
                except Exception:
                    if not settings.get("pdf_fallback",True):raise
                    from pdfminer.high_level import extract_text
                    text=extract_text(str(path),page_numbers={0}) or ""
                    fallback=True
                found = rule.find_in_pdf_text(text)
                if not parsed:
                    item["pdf_check"] = "تعذر ربط اسم الملف"
                elif rule.expected_in_pdf_text(text,parsed):
                    item["pdf_check"] = "وُجد الرقم والإصدار داخل أول صفحة" if parsed["revision"] else "وُجد رقم المستند داخل أول صفحة؛ إصدار الاسم غير محدد"
                elif not found:
                    item["pdf_check"] = "لم يُقرأ رقم مطابق للقالب"
                    item["issues"].append("بيانات PDF تحتاج قراءة يدوية أو OCR")
                else:
                    item["pdf_check"] = "لم يُعثر على رقم الملف وإصداره داخل النص المقروء"
                    item["issues"].append("راجع اختلاف بيانات PDF عن الاسم أو وجود مراجع للوحات أخرى")
                if fallback:item["pdf_check"]+=" — باستخدام القراءة الموسعة"
            except Exception as exc:
                item["pdf_check"] = "تعذرت قراءة PDF"
                item["issues"].append("خطأ قراءة PDF: " + str(exc)[:200])
        results.append(item)
    groups = defaultdict(list)
    for item in results:
        if item["key"]:
            groups[(item["key"], item["revision"], item["format"])].append(item)
    for group in groups.values():
        if len(group) > 1:
            hashes = {x["hash"] for x in group if x["hash"]}
            label = "نسخ متطابقة لنفس الرقم والإصدار والصيغة" if len(hashes)==1 and all(x["hash"] for x in group) else "ملفات مختلفة لنفس الرقم والإصدار والصيغة"
            for item in group:
                item["issues"].append(label)
    pdf_keys = {r["key"] for r in results if r["format"]=="PDF" and r["key"]}
    pdf_versions = {(r["key"],r["revision"]) for r in results if r["format"]=="PDF" and r["key"]}
    # Missing means absent from this selected batch, not absent from the project.
    missing = [rec for key, entries in register.items() for rec in entries
               if ((key,rec["revision"]) not in pdf_versions if rec["revision"] else key not in pdf_keys)]
    return {"items": results, "attachments":attachments,"register_sources":sorted({r.get("source","") for r in records if r.get("source")}),"register_not_in_batch": missing, "invalid_register": invalid_register,
            "summary": {"files": len(results), "pdf": sum(x["format"]=="PDF" for x in results),
                        "dwg": sum(x["format"]=="DWG" for x in results),
                        "attachments":len(attachments),
                        "with_observations": sum(bool(x["issues"]) for x in results)}}


def write_xlsx(path, sheets):
    """Export literal values to a new XLSX. Source workbooks are never rewritten."""
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    relns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    def col_name(n):
        s = ""
        while n:
            n, r = divmod(n-1, 26)
            s = chr(65+r) + s
        return s
    def clean(value):
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value))[:32767]
    types = '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
    workbook = f'<workbook xmlns="{ns}" xmlns:r="{relns}"><sheets>'
    rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for i, (name, rows) in enumerate(sheets.items(), 1):
            types += f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            workbook += f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
            rels += f'<Relationship Id="rId{i}" Type="{relns}/worksheet" Target="worksheets/sheet{i}.xml"/>'
            width = max((len(r) for r in rows), default=1)
            header_widths={"اسم الملف":60,"رقم المستند":58,"الإصدار":12,"العنوان من اللوج":72,"العنوان":72,"الملاحظات":75,"المسار":95,"فحص نص PDF":55,"المصدر":85,"القيمة":100}
            widths=[header_widths.get(str(rows[0][c]) if rows and c<len(rows[0]) else "",28) for c in range(width)]
            cols=''.join(f'<col min="{c+1}" max="{c+1}" width="{w}" customWidth="1"/>' for c,w in enumerate(widths))
            xml = f'<worksheet xmlns="{ns}"><sheetViews><sheetView workbookViewId="0" rightToLeft="1" showGridLines="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>{cols}</cols><sheetData>'
            for rn, row in enumerate(rows, 1):
                lines=max((sum(max(1,math.ceil(len(line)/max(1,widths[cn]-2))) for line in str(value or "").split("\n")) for cn,value in enumerate(row)),default=1)
                xml += f'<row r="{rn}" ht="{min(400,max(30,lines*16+8))}" customHeight="1">'
                for cn, value in enumerate(row, 1):
                    style = ' s="1"' if rn == 1 else ''
                    address = f'{col_name(cn)}{rn}'
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        xml += f'<c r="{address}"{style}><v>{value}</v></c>'
                    else:
                        xml += f'<c r="{address}" t="inlineStr"{style}><is><t xml:space="preserve">{escape(clean(value if value is not None else ""))}</t></is></c>'
                xml += '</row>'
            xml += '</sheetData>'
            if rows:
                xml += f'<autoFilter ref="A1:{col_name(width)}{len(rows)}"/>'
            xml += '</worksheet>'
            z.writestr(f'xl/worksheets/sheet{i}.xml', xml)
        types += '</Types>'
        workbook += '</sheets></workbook>'
        rels += f'<Relationship Id="styles" Type="{relns}/styles" Target="styles.xml"/></Relationships>'
        z.writestr('[Content_Types].xml', types)
        z.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="book" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml', workbook)
        z.writestr('xl/_rels/workbook.xml.rels', rels)
        z.writestr('xl/styles.xml', f'<styleSheet xmlns="{ns}"><fonts count="2"><font><sz val="11"/><name val="Arial"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Arial"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF234B76"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf><xf fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')


def export_results(path, project, results):
    target=os.path.normcase(str(Path(path).resolve()))
    sources=results.get("register_sources",[])+[r["path"] for r in results["items"]]+[r["path"] for r in results.get("attachments",[])]
    if any(target==os.path.normcase(str(Path(source).resolve())) for source in sources):
        raise ValueError("اختار اسم ملف جديد للتقرير؛ هذا المسار من ملفات المصدر")
    items = [["اسم الملف", "رقم المستند", "الإصدار", "العنوان من اللوج", "التخصص", "المنطقة", "الحالة من اللوج", "الصيغة", "فحص نص PDF", "الملاحظات", "صف اللوج", "المسار"]]
    for r in results["items"]:
        items.append([r["file"],r["number"],r["revision"],r["title"],r["discipline"],r["area"],r["status"],r["format"],r["pdf_check"],"؛ ".join(r["issues"]),r["register_row"],r["path"]])
    absent = [["رقم المستند", "الإصدار", "العنوان", "صف اللوج", "المصدر"]] + [[r["number"],r["revision"],r["title"],r["row"],r["source"]] for r in results["register_not_in_batch"]]
    invalid = [["رقم المستند", "العنوان", "صف اللوج", "الملاحظة"]] + [[r["number"],r["title"],r["row"],"لا يطابق قواعد المشروع الحالية"] for r in results["invalid_register"]]
    snapshot=results.get("context",{})
    settings=project["settings"]
    context = [["البند","القيمة"],["المشروع",snapshot.get("project_name",project["name"])],["كود المشروع",snapshot.get("project_code",project["code"])],["فولدر الدفعة",snapshot.get("folder","")],["اللوج المستخدم",snapshot.get("register_source","")],["نطاق المطابقة","الدفعة المختارة مقابل اللوج المستورد"],["المستندات غير الموجودة","سجلات لا يوجد لها PDF مطابق بالرقم والإصدار في هذه الدفعة فقط"],["فحص PDF","قراءة نص أول صفحة؛ النتيجة لا تثبت اكتمال الشكل أو الاعتماد"],["مثال التسمية",settings.get("example","")],["بدائل كود المشروع",", ".join(settings.get("project_aliases",[]))],["الفولدرات المستبعدة",", ".join(settings.get("excluded_folders",[]))],["أجزاء الاسم", "\n".join(ROLE_LABELS[p["role"]]+": "+p["sample"] for p in settings.get("parts",[]))]]
    attachments=[["اسم الملف","الصيغة","المسار"]]+[[r["file"],r["format"],r["path"]] for r in results.get("attachments",[])]
    write_xlsx(path, {"المطابقة":items,"غير موجود في الدفعة":absent,"سجلات تحتاج تعريف":invalid,"ملفات إضافية":attachments,"نطاق التقرير":context})
