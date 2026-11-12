"""Readable navy notices, matching the app rather than the old grey theme."""

import tkinter as tk
from tkinter import ttk

from .theme import BG, INPUT, TEXT, MUTED, apply_window_theme
from .windows import place_window


def _show(title, message, parent, question=False):
    previous_grab = parent.grab_current()
    dialog = tk.Toplevel(parent)
    dialog.withdraw()
    dialog.title(title)
    dialog.transient(parent)
    result = {"accepted": False}
    content = ttk.Frame(dialog, padding=22)
    content.pack(fill="both", expand=True)
    ttk.Label(content, text=title, font=("Segoe UI", 13, "bold"), anchor="e").pack(
        fill="x", pady=(0, 14)
    )
    text_area = ttk.Frame(content)
    text_area.pack(fill="both", expand=True)
    text = tk.Text(
        text_area,
        wrap="word",
        height=7,
        font=("Segoe UI", 10),
        background=INPUT,
        foreground=TEXT,
        borderwidth=0,
    )
    text.pack(side="right", fill="both", expand=True)
    text.tag_configure("arabic", justify="right")
    text.insert("1.0", str(message), "arabic")
    text.configure(state="disabled")
    scrollbar = ttk.Scrollbar(text_area, command=text.yview)
    scrollbar.pack(side="left", fill="y")
    text.configure(yscrollcommand=scrollbar.set)
    buttons = ttk.Frame(content)
    buttons.pack(fill="x", pady=(18, 0))

    def accept():
        result["accepted"] = True
        dialog.destroy()

    button = ttk.Button(
        buttons,
        text="متابعة" if question else "موافق",
        command=accept,
        style="Accent.TButton",
    )
    button.pack(side="right")
    if question:
        ttk.Button(buttons, text="إلغاء", command=dialog.destroy).pack(
            side="right", padx=10
        )
    dialog.bind("<Escape>", lambda event: dialog.destroy())
    dialog.bind("<Return>", lambda event: accept())
    apply_window_theme(dialog)
    place_window(dialog, (620, 330), parent, modal=True)
    button.focus_set()
    parent.wait_window(dialog)
    if previous_grab is not None:
        try:
            if previous_grab.winfo_exists():
                previous_grab.grab_set()
        except tk.TclError:
            pass
    return result["accepted"]


def showinfo(title, message, *, parent):
    _show(title, message, parent)


def showerror(title, message, *, parent):
    _show(title, message, parent)


def askyesno(title, message, *, parent):
    return _show(title, message, parent, question=True)
