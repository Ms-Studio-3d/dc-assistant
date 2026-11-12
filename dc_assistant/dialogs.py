import tkinter as tk
from tkinter import ttk
from . import ui_messages as messagebox
from .theme import apply_window_theme
from .windows import place_window
from .constants import DEFAULT_STATUSES, ROLE_LABELS
from .naming import NamingRule
from .registers import excel_columns, excel_sheets


def field(parent, row, label, value="", width=60):
    ttk.Label(parent, text=label, anchor="e").grid(
        row=row, column=1, sticky="e", padx=8, pady=6
    )
    var = tk.StringVar(value=value)
    ttk.Entry(parent, textvariable=var, width=width, justify="right").grid(
        row=row, column=0, sticky="ew", padx=8, pady=6
    )
    return var


class ProjectDialog(tk.Toplevel):
    def __init__(self, app, project=None):
        super().__init__(app)
        self.withdraw()
        self.app, self.project, self.result = app, project, None
        self.title("إعدادات المشروع" if project else "مشروع جديد")
        self.minsize(850, 620)
        self.transient(app)
        settings = project["settings"] if project else {}
        book = ttk.Notebook(self)
        book.pack(fill="both", expand=True, padx=14, pady=12)
        basic, naming, procedure = [ttk.Frame(book, padding=14) for _ in range(3)]
        book.add(basic, text="المشروع")
        book.add(naming, text="قواعد التسمية")
        book.add(procedure, text="الحالات والإجراءات")
        basic.columnconfigure(0, weight=1)
        self.name_var = field(
            basic, 0, "اسم المشروع *", project["name"] if project else ""
        )
        self.code_var = field(
            basic, 1, "كود المشروع كما هو", project["code"] if project else ""
        )
        self.alias_var = field(
            basic,
            2,
            "بدائل كود المشروع المسموحة، مفصولة بفاصلة",
            ", ".join(settings.get("project_aliases", [])),
        )
        self.exclude_var = field(
            basic,
            3,
            "أسماء فولدرات تُستبعد من الفحص، مفصولة بفاصلة",
            ", ".join(settings.get("excluded_folders", [])),
        )
        ttk.Label(
            basic,
            text="تسجيل المشروع يحتاج الاسم فقط. أكمل قواعد التسمية قبل فحص الملفات.",
            anchor="e",
        ).grid(row=4, column=0, columnspan=2, sticky="e", padx=8, pady=18)
        self.case_var = tk.BooleanVar(value=settings.get("ignore_case", False))
        ttk.Checkbutton(
            basic,
            text="السماح باختلاف الحروف الكبيرة والصغيرة عند المطابقة",
            variable=self.case_var,
        ).grid(row=5, column=0, columnspan=2, sticky="e", padx=8)

        naming.columnconfigure(0, weight=1)
        self.example_var = field(
            naming, 0, "مثال صحيح لاسم ملف لوحة", settings.get("example", "")
        )
        ttk.Label(naming, text="الفاصل بين أجزاء الاسم").grid(
            row=1, column=1, sticky="e", padx=8
        )
        self.separator_var = tk.StringVar(value=settings.get("separator", "-"))
        ttk.Combobox(
            naming,
            textvariable=self.separator_var,
            values=["-", "_", "."],
            width=8,
            state="readonly",
        ).grid(row=1, column=0, sticky="e", padx=8)
        ttk.Button(naming, text="عرض أجزاء المثال", command=self.build_parts).grid(
            row=2, column=0, columnspan=2, sticky="e", padx=8, pady=8
        )
        ttk.Label(
            naming,
            text="حدد وظيفة كل جزء. الأجزاء الثابتة يجب أن تظل مطابقة للمثال.",
            anchor="e",
        ).grid(row=3, column=0, columnspan=2, sticky="e", padx=8)
        container = ttk.Frame(naming)
        container.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=8)
        naming.rowconfigure(4, weight=1)
        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self.parts_frame = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=self.parts_frame, anchor="nw")
        self.parts_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.bind(
            "<Configure>", lambda e: canvas.itemconfigure(window, width=e.width)
        )
        self.part_vars = []
        self.optional_var = tk.BooleanVar(value=settings.get("optional_revision", True))
        ttk.Checkbutton(
            naming,
            text="السماح برقم لوحة دون إصدار عند قراءة اللوج",
            variable=self.optional_var,
        ).grid(row=5, column=0, columnspan=2, sticky="e", padx=8)
        self.fallback_var = tk.BooleanVar(value=settings.get("pdf_fallback", True))
        ttk.Checkbutton(
            naming,
            text="استخدام قارئ بديل عند تعذر قراءة الملف (قد يستغرق وقتًا أطول)",
            variable=self.fallback_var,
        ).grid(row=6, column=0, columnspan=2, sticky="e", padx=8)
        if settings.get("parts"):
            self.build_parts(settings["parts"])

        ttk.Label(
            procedure, text="أكواد الحالات ومعانيها: كود = المعنى", anchor="e"
        ).pack(fill="x")
        self.status_text = tk.Text(
            procedure, height=6, wrap="word", font=("Segoe UI", 11)
        )
        self.status_text.pack(fill="x", pady=(5, 16))
        self.status_text.insert(
            "1.0",
            "\n".join(
                f"{k} = {v}"
                for k, v in settings.get("statuses", DEFAULT_STATUSES).items()
            ),
        )
        ttk.Label(
            procedure, text="مرجع الردود والتسليمات وقواعد نطاق التقارير", anchor="e"
        ).pack(fill="x")
        self.procedure_text = tk.Text(
            procedure, height=10, wrap="word", font=("Segoe UI", 11)
        )
        self.procedure_text.pack(fill="both", expand=True, pady=5)
        self.procedure_text.insert("1.0", settings.get("procedure_notes", ""))
        buttons = ttk.Frame(self, padding=12)
        buttons.pack(fill="x")
        ttk.Button(
            buttons, text="حفظ المشروع", command=self.save, style="Accent.TButton"
        ).pack(side="right", padx=6)
        ttk.Button(buttons, text="إلغاء", command=self.destroy).pack(
            side="right", padx=6
        )

        apply_window_theme(self)
        place_window(self, (1000, 690), app, show=app.winfo_viewable(), modal=True)

    def build_parts(self, existing=None):
        if existing is not None and not isinstance(existing, list):
            existing = None
        for child in self.parts_frame.winfo_children():
            child.destroy()
        self.part_vars = []
        example = self.example_var.get().strip()
        if example.lower().endswith((".pdf", ".dwg")):
            example = example[:-4]
        samples = (
            [p["sample"] for p in existing]
            if existing
            else example.split(self.separator_var.get()) if example else []
        )
        for i, sample in enumerate(samples):
            role = existing[i]["role"] if existing else "literal"
            var = tk.StringVar(value=ROLE_LABELS[role])
            ttk.Label(
                self.parts_frame, text=f"{i+1}.  {sample}", width=42, anchor="e"
            ).grid(row=i, column=1, sticky="e", padx=10, pady=3)
            ttk.Combobox(
                self.parts_frame,
                textvariable=var,
                values=list(ROLE_LABELS.values()),
                state="readonly",
                width=24,
            ).grid(row=i, column=0, padx=10, pady=3)
            self.part_vars.append((sample, var))

    def save(self):
        try:
            reverse = {v: k for k, v in ROLE_LABELS.items()}
            parts = [
                {"sample": sample, "role": reverse[var.get()]}
                for sample, var in self.part_vars
            ]
            statuses = {}
            for line in self.status_text.get("1.0", "end").splitlines():
                if not line.strip():
                    continue
                if "=" not in line:
                    raise ValueError("اكتب كل حالة بالشكل: A = Approved")
                key, value = line.split("=", 1)
                if not key.strip() or not value.strip():
                    raise ValueError("كود الحالة ومعناها مطلوبان")
                if key.strip() in statuses:
                    raise ValueError(f"كود حالة مكرر: {key.strip()}")
                statuses[key.strip()] = value.strip()
            settings = {
                **(self.project["settings"] if self.project else {}),
                "example": self.example_var.get(),
                "parts": parts,
                "separator": self.separator_var.get(),
                "project_aliases": [
                    x.strip()
                    for x in self.alias_var.get().replace("،", ",").split(",")
                    if x.strip()
                ],
                "excluded_folders": [
                    x.strip()
                    for x in self.exclude_var.get().replace("،", ",").split(",")
                    if x.strip()
                ],
                "ignore_case": self.case_var.get(),
                "optional_revision": self.optional_var.get(),
                "pdf_fallback": self.fallback_var.get(),
                "statuses": statuses,
                "procedure_notes": self.procedure_text.get("1.0", "end").strip(),
            }
            if parts:
                rule = NamingRule(settings)
                if not rule.parse(settings["example"]):
                    raise ValueError(
                        "مثال الاسم لا يطابق تعريف الأجزاء. اضغط عرض أجزاء المثال بعد تغييره."
                    )
                sample = next(
                    (p["sample"] for p in parts if p["role"] == "project"), None
                )
                if sample and self.code_var.get() and sample != self.code_var.get():
                    raise ValueError(
                        "كود المشروع في المثال مختلف عن كود المشروع المكتوب"
                    )
            self.result = self.app.store.save_project(
                self.name_var.get(),
                self.code_var.get(),
                settings,
                self.project["id"] if self.project else None,
            )
            self.destroy()
        except Exception as exc:
            messagebox.showerror("راجع الإعدادات", str(exc), parent=self)


class RegisterDialog(tk.Toplevel):
    def __init__(self, app, path):
        sheets = excel_sheets(path)
        super().__init__(app)
        self.withdraw()
        try:
            self._build(app, path, sheets)
            apply_window_theme(self)
            place_window(self, (900, 650), app, show=app.winfo_viewable(), modal=True)
        except Exception:
            self.destroy()
            raise

    def _build(self, app, path, sheets):
        self.path, self.result = path, None
        self.title("تحديد شيت وأعمدة اللوج")
        self.transient(app)
        frame = ttk.Frame(self, padding=18)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        self.sheet_var = tk.StringVar(value=sheets[0])
        ttk.Label(frame, text="الشيت").grid(row=0, column=1, sticky="e", pady=5)
        ttk.Combobox(
            frame,
            textvariable=self.sheet_var,
            values=sheets,
            state="readonly",
            width=55,
        ).grid(row=0, column=0, sticky="ew", pady=5)
        self.header_var = field(frame, 1, "رقم صف العناوين", "1")
        self.start_var = field(frame, 2, "أول صف بيانات فعلي", "2")
        ttk.Button(frame, text="قراءة العناوين", command=self.load_columns).grid(
            row=3, column=0, sticky="e", pady=8
        )
        self.mapping_frame = ttk.Frame(frame)
        self.mapping_frame.grid(row=4, column=0, columnspan=2, sticky="ew")
        self.variables = {}
        self.column_options = {}
        self.loaded_sheet = None
        self.loaded_header = None
        ttk.Label(
            frame,
            text="الحالة تخص الإصدار المحدد. للتخصص والمنطقة، اختر أعمدة الأكواد المستخدمة في اسم الملف.",
            wraplength=780,
            anchor="e",
        ).grid(row=5, column=0, columnspan=2, sticky="e", pady=14)
        ttk.Button(frame, text="استيراد اللوج", command=self.accept).grid(
            row=6, column=0, sticky="e", pady=10
        )
        self.load_columns()

    def load_columns(self):
        self.loaded_sheet = None
        self.loaded_header = None
        try:
            header = int(self.header_var.get())
            if header < 1:
                raise ValueError("صف العناوين يبدأ من 1")
            cols = excel_columns(self.path, self.sheet_var.get(), header)
            for child in self.mapping_frame.winfo_children():
                child.destroy()
            self.column_options = {
                "غير محدد": None,
                **{f"{i+1}: {text or '(فارغ)'}": i for i, text in cols},
            }
            labels = {
                "number": "رقم المستند *",
                "title": "عنوان المستند",
                "revision": "الإصدار",
                "discipline": "كود التخصص",
                "area": "كود المنطقة / المبنى",
                "status": "حالة هذا الإصدار",
            }
            hints = {
                "number": {
                    "NAME",
                    "DRAWING NO.",
                    "DRAWING NO",
                    "SHEET NUMBER",
                    "رقم المستند",
                },
                "title": {"DESCRIPTION", "DRAWING TITLE", "SHEET NAME", "العنوان"},
                "revision": {"REV", "REV.", "CURRENT REVISION"},
                "discipline": {"DISCIPLINE"},
                "area": {"AREA"},
                "status": set(),
            }
            self.variables = {}
            for row, (key, label) in enumerate(labels.items()):
                match = next(
                    (
                        option
                        for option, i in self.column_options.items()
                        if i is not None
                        and " ".join(cols[i][1].upper().split()) in hints[key]
                    ),
                    "غير محدد",
                )
                var = tk.StringVar(value=match)
                self.variables[key] = var
                ttk.Combobox(
                    self.mapping_frame,
                    textvariable=var,
                    values=list(self.column_options),
                    state="readonly",
                    width=60,
                ).grid(row=row, column=0, pady=5, sticky="ew")
                ttk.Label(self.mapping_frame, text=label).grid(
                    row=row, column=1, padx=10, sticky="e"
                )
            self.loaded_sheet = self.sheet_var.get()
            self.loaded_header = header
        except Exception as exc:
            messagebox.showerror("تعذرت قراءة العناوين", str(exc), parent=self)

    def accept(self):
        try:
            if self.loaded_sheet is None:
                raise ValueError("اقرأ صف عناوين صالحًا قبل الاستيراد")
            if (
                self.sheet_var.get() != self.loaded_sheet
                or int(self.header_var.get()) != self.loaded_header
            ):
                raise ValueError("اضغط قراءة العناوين بعد تغيير الشيت أو صف العناوين")
            mapping = {
                k: self.column_options[v.get()] for k, v in self.variables.items()
            }
            if mapping.get("number") is None:
                raise ValueError("حدد عمود رقم المستند")
            first = int(self.start_var.get())
            if first <= self.loaded_header:
                raise ValueError("أول صف بيانات يجب أن يكون بعد صف العناوين")
            mapping.update(
                sheet=self.loaded_sheet,
                header_row=self.loaded_header,
                data_start_row=first,
            )
            self.result = mapping
            self.destroy()
        except Exception as exc:
            messagebox.showerror("راجع الاختيارات", str(exc), parent=self)
