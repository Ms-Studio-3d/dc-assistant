"""Backup and restore for the single local user."""

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from . import ui_messages as messagebox
from .data_safety import backup_database, inspect_backup
from .theme import apply_window_theme
from .windows import place_window


class DataDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.withdraw()
        self.app = app
        self.title("البيانات والنسخ الاحتياطي")
        self.transient(app)
        body = ttk.Frame(self, padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body,
            text="بياناتك محفوظة على جهازك",
            font=("Segoe UI", 15, "bold"),
            anchor="e",
        ).pack(fill="x")
        ttk.Label(
            body,
            text="تشمل النسخة المشاريع والإعدادات واللوجات ونتائج الدفعات المحفوظة.",
            anchor="e",
            wraplength=620,
        ).pack(fill="x", pady=(10, 20))
        ttk.Label(
            body, text="مكان قاعدة البيانات", anchor="e", style="Muted.TLabel"
        ).pack(fill="x")
        path = ttk.Entry(body, justify="left")
        path.insert(0, str(app.store.path))
        path.configure(state="readonly")
        path.pack(fill="x", pady=(6, 18))
        ttk.Label(
            body,
            text="تُنشأ نسخة تلقائية يومية. يمكنك حفظ نسخة إضافية في مكان تختاره.",
            anchor="e",
            wraplength=620,
            style="Muted.TLabel",
        ).pack(fill="x")
        row = ttk.Frame(body)
        row.pack(fill="x", pady=22)
        ttk.Button(
            row, text="حفظ نسخة احتياطية", command=self.backup, style="Accent.TButton"
        ).pack(side="right")
        ttk.Button(row, text="استرجاع نسخة", command=self.restore).pack(
            side="right", padx=12
        )
        ttk.Button(body, text="إغلاق", command=self.destroy).pack(
            anchor="w", pady=(12, 0)
        )
        apply_window_theme(self)
        place_window(self, (740, 480), app, modal=True)

    def backup(self):
        selected = filedialog.asksaveasfilename(
            parent=self,
            title="حفظ نسخة من بيانات البرنامج",
            defaultextension=".sqlite3",
            filetypes=[("DC Assistant backup", "*.sqlite3")],
            initialfile="DC-Assistant-Backup.sqlite3",
        )
        if not selected:
            return
        try:
            backup_database(self.app.store, selected)
            messagebox.showinfo("تم حفظ النسخة", selected, parent=self)
        except Exception as exc:
            messagebox.showerror("تعذر حفظ النسخة", str(exc), parent=self)

    def restore(self):
        selected = filedialog.askopenfilename(
            parent=self,
            title="اختيار نسخة احتياطية",
            filetypes=[("DC Assistant backup", "*.sqlite3 *.db")],
        )
        if not selected:
            return
        try:
            info = inspect_backup(selected)
            prompt = f"النسخة تحتوي {info['projects']} مشروع و{info['batches']} دفعة.\n\nالاسترجاع سيستبدل البيانات الحالية. ستُحفظ نسخة منها قبل الاسترجاع.\n\nهل تريد المتابعة؟"
            if not messagebox.askyesno("استرجاع البيانات", prompt, parent=self):
                return
            safety = self.app.restore_from_backup(selected)
            messagebox.showinfo(
                "تم الاسترجاع",
                f"تم استرجاع البيانات.\nنسخة البيانات السابقة:\n{safety}",
                parent=self,
            )
            self.destroy()
        except Exception as exc:
            messagebox.showerror("تعذر الاسترجاع", str(exc), parent=self)
