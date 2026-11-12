from __future__ import annotations

import argparse
import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from . import __version__, ui_messages as messagebox
from .branding import configure_process, apply_brand
from .data_safety import InstanceLock, daily_backup, restore_database
from .data_dialog import DataDialog
from .theme import BG, apply_theme, apply_window_theme
from .windows import place_window

from .core import NamingRule, Store, export_results, read_register, scan_batch
from .dialogs import ProjectDialog, RegisterDialog
from .issues import format_status, pdf_check_label
from .scanning import ScanCancelled


class StartupError(RuntimeError):
    pass


class App(tk.Tk):
    def __init__(self, data_dir, *, show=True):
        configure_process()
        super().__init__()
        self.withdraw()
        self.store = None
        self.instance = None
        self.poll_id = None
        self._closed = False
        try:
            self._initialize(data_dir, show)
        except Exception as exc:
            if self.store is not None:
                self.store.close()
            if self.instance is not None:
                self.instance.close()
            if show:
                messagebox.showerror("تعذر فتح البرنامج", str(exc), parent=self)
            self.destroy()
            raise StartupError(str(exc)) from exc

    def _initialize(self, data_dir, show):
        self.title(f"DC Assistant {__version__} — مساعد ضبط المستندات")
        self.minsize(1000, 650)
        apply_theme(self)
        apply_brand(self)
        self.instance = InstanceLock(data_dir)
        self.store = Store(Path(data_dir) / "dc-assistant.sqlite3")
        self.project = None
        self.results = None
        self.results_settings = None
        self.busy = False
        self.events = queue.Queue()
        self.cancel_event = threading.Event()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.container = ttk.Frame(self, padding=24)
        self.container.pack(fill="both", expand=True)
        self.show_home()
        place_window(self, (1260, 780), show=show)
        apply_window_theme(self)
        self.poll_id = self.after(100, self.poll)
        try:
            daily_backup(self.store)
        except Exception as exc:
            if show:
                messagebox.showerror(
                    "تعذرت النسخة التلقائية",
                    f"قاعدة البيانات متاحة، لكن لم تحفظ النسخة الاحتياطية:\n{exc}",
                    parent=self,
                )

    def clear(self):
        for child in self.container.winfo_children():
            child.destroy()

    def show_home(self):
        if self.busy:
            return
        self.clear()
        header = ttk.Frame(self.container)
        header.pack(fill="x", pady=(4, 32))
        tk.Label(header, image=self.brand_logo, background=BG).pack(side="left")
        ttk.Button(
            header, text="البيانات والنسخ الاحتياطي", command=self.manage_data
        ).pack(side="right")
        ttk.Label(
            self.container,
            text="هتشتغل على أنهي مشروع؟",
            font=("Segoe UI", 23),
            anchor="e",
        ).pack(fill="x", pady=(20, 12))
        ttk.Label(
            self.container,
            text="اختر مشروعًا محفوظًا أو سجّل مشروعًا جديدًا بقواعده الخاصة.",
            style="Muted.TLabel",
            anchor="e",
        ).pack(fill="x")
        choices = ttk.Frame(self.container)
        choices.pack(pady=34)
        ttk.Button(
            choices,
            text="مشروع مسجل",
            width=28,
            command=self.choose_existing,
            style="Accent.TButton",
        ).grid(row=0, column=1, padx=10, ipady=18)
        ttk.Button(choices, text="مشروع جديد", width=28, command=self.new_project).grid(
            row=0, column=0, padx=10, ipady=18
        )
        ttk.Label(
            self.container,
            text=f"DC Assistant {__version__}  •  بيانات محلية محفوظة",
            style="Muted.TLabel",
            anchor="e",
        ).pack(side="bottom", fill="x", pady=6)

    def manage_data(self):
        if self.busy:
            return
        dialog = DataDialog(self)
        self.wait_window(dialog)

    def restore_from_backup(self, path):
        if self.busy:
            raise ValueError("أوقف الفحص قبل استرجاع البيانات")
        safety = restore_database(self.store, path)
        self.project = None
        self.results = None
        self.results_settings = None
        self.show_home()
        return safety

    def new_project(self):
        dlg = ProjectDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            self.open_project(dlg.result)

    def choose_existing(self):
        projects = self.store.projects()
        if not projects:
            messagebox.showinfo(
                "المشاريع", "لا توجد مشاريع مسجلة. أضف مشروعًا جديدًا.", parent=self
            )
            return
        dlg = tk.Toplevel(self)
        dlg.withdraw()
        dlg.title("المشاريع المسجلة")
        dlg.transient(self)
        labels = [
            p["name"] + (" — " + p["code"] if p["code"] else "") for p in projects
        ]
        value = tk.StringVar(value=labels[0])
        ttk.Label(dlg, text="اختار المشروع").pack(pady=15)
        combo = ttk.Combobox(
            dlg, textvariable=value, values=labels, state="readonly", width=65
        )
        combo.pack(padx=20, pady=5)

        def choose():
            i = combo.current()
            dlg.destroy()
            self.open_project(projects[i]["id"])

        ttk.Button(
            dlg, text="فتح المشروع", command=choose, style="Accent.TButton"
        ).pack(pady=18)
        apply_window_theme(dlg)
        place_window(dlg, (650, 250), self, modal=True)

    def open_project(self, project_id):
        self.project = self.store.get_project(project_id)
        self.results = None
        self.results_settings = None
        self.show_workspace()

    def show_workspace(self):
        self.clear()
        header = ttk.Frame(self.container)
        header.pack(fill="x")
        ttk.Button(header, text="تغيير المشروع", command=self.show_home).pack(
            side="left"
        )
        ttk.Label(
            header,
            text=self.project["name"] + "  |  " + self.project["code"],
            font=("Segoe UI", 18),
            anchor="e",
        ).pack(side="right")
        tools = ttk.Frame(self.container)
        tools.pack(fill="x", pady=16)
        self.action_buttons = []
        actions = [
            ("إعدادات المشروع", self.edit_project),
            ("استيراد لوج Excel", self.import_register),
            ("فحص دفعة ملفات", self.start_scan),
            ("دفعات سابقة", self.history),
            ("تصدير Excel", self.export),
            ("فتح الملف المحدد", self.open_selected),
        ]
        for index, (text, command) in enumerate(actions):
            button = ttk.Button(tools, text=text, command=command)
            button.grid(
                row=index // 3, column=2 - index % 3, sticky="ew", padx=4, pady=4
            )
            self.action_buttons.append(button)
        for column in range(3):
            tools.columnconfigure(column, weight=1)
        self.pdf_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            self.container,
            text="البحث عن نص رقم المستند في أول صفحة PDF؛ لا يتحقق من خانة اللوحة",
            variable=self.pdf_var,
        ).pack(anchor="e")
        reg = self.store.get_register(self.project["id"])
        self.info_var = tk.StringVar(
            value=(
                f"اللوج المستورد: {len(reg['records'])} سجل — {reg['mapping']['sheet']}"
                if reg
                else "لم يُستورد لوج لهذا المشروع بعد"
            )
        )
        ttk.Label(self.container, textvariable=self.info_var, anchor="e").pack(
            fill="x", pady=8
        )
        columns = ("issues", "status", "revision", "number", "file")
        grid = ttk.Frame(self.container)
        grid.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            grid, columns=columns, show="headings", selectmode="browse"
        )
        for key, title, width in [
            ("issues", "الملاحظات", 330),
            ("status", "الحالة من اللوج", 100),
            ("revision", "الإصدار", 70),
            ("number", "رقم المستند", 330),
            ("file", "اسم الملف", 350),
        ]:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=60, anchor="e")
        vs = ttk.Scrollbar(grid, orient="vertical", command=self.tree.yview)
        hs = ttk.Scrollbar(grid, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        grid.rowconfigure(0, weight=1)
        grid.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(self.container, mode="determinate")
        self.progress.pack(fill="x", pady=(10, 4))
        self.cancel_button = ttk.Button(
            self.container,
            text="إلغاء الفحص",
            command=self.cancel_scan,
            state="disabled",
        )
        self.cancel_button.pack(anchor="e", pady=4)
        self.status_var = tk.StringVar(value="اختار اللوج أو دفعة الملفات للبدء")
        ttk.Label(self.container, textvariable=self.status_var, anchor="e").pack(
            fill="x"
        )
        self.tree.bind("<Double-1>", lambda e: self.show_detail())

    def edit_project(self):
        dlg = ProjectDialog(self, self.project)
        self.wait_window(dlg)
        if dlg.result:
            self.open_project(dlg.result)

    def import_register(self):
        path = filedialog.askopenfilename(
            parent=self, title="اختار ملف اللوج", filetypes=[("Excel", "*.xlsx")]
        )
        if not path:
            return
        try:
            dlg = RegisterDialog(self, path)
            self.wait_window(dlg)
            if not dlg.result:
                return
            records, warnings = read_register(path, dlg.result)
            if warnings:
                detail = "\n".join(warnings[:30])
                if len(warnings) > 30:
                    detail += f"\nو{len(warnings) - 30} ملاحظة أخرى؛ راجع الملف بعد إصلاح الصفوف المذكورة"
                raise ValueError("لم يتغير اللوج المحفوظ.\n" + detail)
            self.store.save_register(self.project["id"], path, dlg.result, records)
            self.results = None
            self.results_settings = None
            self.tree.delete(*self.tree.get_children())
            self.progress.configure(value=0)
            self.info_var.set(
                f"اللوج المستورد: {len(records)} سجل — {dlg.result['sheet']}"
            )
            self.status_var.set(
                "تم استيراد اللوج. افحص الدفعة مجددًا لعرض نتائج مرتبطة بهذه النسخة."
            )
        except Exception as exc:
            messagebox.showerror("تعذر الاستيراد", str(exc), parent=self)

    def start_scan(self):
        try:
            NamingRule(self.project["settings"])
        except ValueError as exc:
            messagebox.showinfo("قواعد التسمية", str(exc), parent=self)
            self.edit_project()
            return
        folder = filedialog.askdirectory(parent=self, title="فولدر الدفعة المراد فحصها")
        if not folder:
            return
        reg = self.store.get_register(self.project["id"])
        records = reg["records"] if reg else []
        settings = json.loads(json.dumps(self.project["settings"]))
        project_id = self.project["id"]
        context = {
            "project_name": self.project["name"],
            "project_code": self.project["code"],
            "folder": folder,
            "register_source": reg["source"] if reg else "",
        }
        check_pdf = self.pdf_var.get()
        self.cancel_event.clear()
        self.set_busy(True)
        self.status_var.set("جارٍ حصر الملفات...")

        def worker():
            try:

                def progress(n, total, name):
                    self.events.put(("progress", (n, total, name)))

                results = scan_batch(
                    folder, settings, records, check_pdf, progress, self.cancel_event
                )
                results["context"] = context
                self.events.put(("done", (project_id, folder, settings, results)))
            except ScanCancelled:
                self.events.put(("cancelled", None))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            for _ in range(100):
                kind, data = self.events.get_nowait()
                if kind == "progress":
                    n, total, name = data
                    self.progress.configure(maximum=max(total, 1), value=n)
                    self.status_var.set(f"{n}/{total} — {name}")
                elif kind == "done":
                    if self.cancel_event.is_set():
                        self.set_busy(False)
                        self.status_var.set("أُلغي الفحص؛ لم تحفظ نتيجة جزئية")
                        continue
                    project_id, folder, settings, results = data
                    self.set_busy(False)
                    self.display(results, settings)
                    try:
                        self.store.save_batch(project_id, folder, settings, results)
                    except Exception as exc:
                        messagebox.showerror(
                            "لم يُحفظ سجل الدفعة",
                            f"النتيجة متاحة للتصدير الآن. تعذر حفظها في قاعدة البيانات:\n{exc}",
                            parent=self,
                        )
                elif kind == "error":
                    self.set_busy(False)
                    messagebox.showerror("تعذر الفحص", data, parent=self)
                elif kind == "cancelled":
                    self.set_busy(False)
                    self.status_var.set("أُلغي الفحص؛ لم تحفظ نتيجة جزئية")
        except queue.Empty:
            pass
        self.poll_id = self.after(100, self.poll)

    def set_busy(self, value):
        self.busy = value
        for button in self.action_buttons:
            button.configure(state="disabled" if value else "normal")
        self.cancel_button.configure(state="normal" if value else "disabled")

    def cancel_scan(self):
        if self.busy:
            self.cancel_event.set()
            self.cancel_button.configure(state="disabled")
            self.status_var.set("جارٍ إلغاء الفحص...")

    def display(self, results, settings=None):
        self.results = results
        self.results_settings = (
            settings if settings is not None else self.project["settings"]
        )
        if "register_source" in results.get("context", {}):
            source = results["context"]["register_source"]
            self.info_var.set(
                "اللوج وقت هذه النتيجة: " + source
                if source
                else "هذه النتيجة أُنشئت دون لوج مستورد"
            )
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(results["items"]):
            self.tree.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    "؛ ".join(r["issues"]),
                    format_status(r, self.results_settings),
                    r["revision"],
                    r["number"],
                    r["file"],
                ),
            )
        s = results["summary"]
        self.status_var.set(
            f"{s['files']} ملف | PDF: {s['pdf']} | DWG: {s['dwg']} | إضافية: {s.get('attachments',0)} | لها ملاحظات: {s['with_observations']} | سجلات دون PDF مطابق: {len(results['register_not_in_batch'])}"
        )

    def selected(self):
        selection = self.tree.selection()
        return (
            self.results["items"][int(selection[0])]
            if selection and self.results
            else None
        )

    def open_selected(self):
        item = self.selected()
        if not item:
            return
        path = Path(item["path"])
        if not path.is_file():
            messagebox.showerror("الملف غير موجود", str(path), parent=self)
            return
        try:
            os.startfile(str(path))
        except OSError as exc:
            messagebox.showerror("تعذر فتح الملف", str(exc), parent=self)

    def show_detail(self):
        item = self.selected()
        if item:
            message = f"{item['path']}\n\nالحالة: {format_status(item, self.results_settings)}\n\nفحص PDF: {pdf_check_label(item)}\n\n"
            messagebox.showinfo(
                "تفاصيل الملف", message + "\n".join(item["issues"]), parent=self
            )

    def history(self):
        batches = self.store.batches(self.project["id"])
        if not batches:
            messagebox.showinfo(
                "الدفعات", "لم تُفحص دفعات لهذا المشروع بعد.", parent=self
            )
            return
        dlg = tk.Toplevel(self)
        dlg.withdraw()
        dlg.title("دفعات المشروع السابقة")
        dlg.transient(self)
        items = tk.Listbox(dlg, font=("Segoe UI", 11))
        items.pack(fill="both", expand=True, padx=14, pady=14)
        for batch in batches:
            items.insert("end", batch["created"][:19] + " — " + batch["folder"])

        def choose():
            selected = items.curselection()
            if selected:
                batch = self.store.get_batch(
                    self.project["id"], batches[selected[0]]["id"]
                )
                dlg.destroy()
                self.display(batch["results"], batch["settings"])

        ttk.Button(dlg, text="عرض النتائج", command=choose).pack(pady=10)
        apply_window_theme(dlg)
        place_window(dlg, (950, 430), self, modal=True)

    def export(self):
        if not self.results:
            messagebox.showinfo(
                "التصدير", "افحص دفعة أو افتح نتائج دفعة سابقة أولًا.", parent=self
            )
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="حفظ تقرير المطابقة",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile="DC-Matching-Report.xlsx",
        )
        if not path:
            return
        try:
            export_results(
                path, {**self.project, "settings": self.results_settings}, self.results
            )
            messagebox.showinfo("تم التصدير", path, parent=self)
        except Exception as exc:
            messagebox.showerror("تعذر التصدير", str(exc), parent=self)

    def close(self):
        if self._closed:
            return
        if self.busy and not messagebox.askyesno(
            "الفحص مستمر", "إغلاق البرنامج وإلغاء حفظ نتيجة الفحص الحالي؟", parent=self
        ):
            return
        self._closed = True
        self.cancel_event.set()
        if self.poll_id is not None:
            self.after_cancel(self.poll_id)
        try:
            daily_backup(self.store)
        except Exception as exc:
            if self.winfo_viewable():
                messagebox.showerror(
                    "تعذرت النسخة التلقائية",
                    f"البيانات الرئيسية محفوظة؛ تعذر حفظ النسخة الاحتياطية:\n{exc}",
                    parent=self,
                )
        finally:
            self.store.close()
            self.instance.close()
            self.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir",
        default=str(
            Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "DCAssistant"
        ),
    )
    parser.add_argument("--self-test-report", default=None)
    parser.add_argument("--self-test-inputs", default=None)
    args = parser.parse_args()
    if args.self_test_report:
        from .diagnostics import self_test

        raise SystemExit(
            self_test(args.self_test_report, args.data_dir, args.self_test_inputs)
        )
    try:
        App(args.data_dir).mainloop()
    except StartupError:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
