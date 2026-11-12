"""Navy dark appearance using the approved cyan accent."""

import ctypes
import os
import tkinter as tk
from tkinter import ttk

BG = "#0B1426"
SURFACE = "#101F38"
INPUT = "#152A47"
TEXT = "#F3F7FC"
MUTED = "#B9C8DE"
ACCENT = "#60CFE6"
SELECT = "#24486E"
BORDER = "#35506E"


def apply_theme(root):
    root.configure(background=BG)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(
        ".",
        background=BG,
        foreground=TEXT,
        font=("Segoe UI", 10),
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        troughcolor=SURFACE,
        selectbackground=SELECT,
        selectforeground=TEXT,
    )
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure(
        "TButton",
        background=INPUT,
        foreground=TEXT,
        padding=(16, 10),
        borderwidth=1,
        focusthickness=2,
        focuscolor=ACCENT,
    )
    style.map(
        "TButton",
        background=[("disabled", SURFACE), ("pressed", SELECT), ("active", SELECT)],
        foreground=[("disabled", "#8395AD")],
    )
    style.configure(
        "Accent.TButton",
        background=ACCENT,
        foreground=BG,
        font=("Segoe UI", 10, "bold"),
    )
    style.map(
        "Accent.TButton",
        background=[("disabled", SURFACE), ("active", "#8ADFF0")],
        foreground=[("disabled", MUTED), ("active", BG)],
    )
    style.configure(
        "TEntry", fieldbackground=INPUT, foreground=TEXT, insertcolor=ACCENT, padding=7
    )
    style.configure(
        "TCombobox",
        fieldbackground=INPUT,
        background=INPUT,
        foreground=TEXT,
        arrowcolor=ACCENT,
        padding=6,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", INPUT)],
        foreground=[("readonly", TEXT)],
        selectbackground=[("readonly", SELECT)],
        selectforeground=[("readonly", TEXT)],
    )
    style.configure(
        "TCheckbutton",
        background=BG,
        foreground=TEXT,
        indicatorbackground=INPUT,
        indicatorforeground=ACCENT,
        padding=4,
    )
    style.map(
        "TCheckbutton",
        background=[("active", BG)],
        indicatorbackground=[("selected", ACCENT)],
        indicatorforeground=[("selected", BG), ("!selected", TEXT)],
    )
    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure(
        "TNotebook.Tab", background=SURFACE, foreground=MUTED, padding=(18, 10)
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", INPUT), ("active", SELECT)],
        foreground=[("selected", ACCENT), ("active", TEXT)],
        padding=[("selected", (18, 10)), ("!selected", (18, 10))],
    )
    style.configure(
        "Treeview",
        background=SURFACE,
        fieldbackground=SURFACE,
        foreground=TEXT,
        rowheight=34,
        borderwidth=0,
    )
    style.map(
        "Treeview", background=[("selected", SELECT)], foreground=[("selected", TEXT)]
    )
    style.configure(
        "Treeview.Heading",
        background=INPUT,
        foreground=TEXT,
        padding=(10, 10),
        font=("Segoe UI", 10, "bold"),
    )
    style.map("Treeview.Heading", background=[("active", SELECT)])
    style.configure(
        "TProgressbar", background=ACCENT, troughcolor=SURFACE, borderwidth=0
    )
    style.configure(
        "TScrollbar", background=INPUT, arrowcolor=MUTED, troughcolor=BG, borderwidth=0
    )
    style.map("TScrollbar", background=[("active", SELECT)])
    root.option_add("*TCombobox*Listbox.background", INPUT)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", SELECT)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)


def apply_window_theme(window):
    window.configure(background=BG)
    for child in window.winfo_children():
        if isinstance(child, (tk.Text, tk.Listbox)):
            child.configure(
                background=INPUT,
                foreground=TEXT,
                selectbackground=SELECT,
                selectforeground=TEXT,
                highlightbackground=BORDER,
                highlightcolor=ACCENT,
                relief="flat",
            )
            if isinstance(child, tk.Text):
                child.configure(insertbackground=ACCENT, padx=10, pady=8)
        elif isinstance(child, tk.Canvas):
            child.configure(background=BG, highlightthickness=0)
        elif isinstance(child, tk.Frame):
            child.configure(background=BG)
        apply_children(child)
    dark_titlebar(window)


def apply_children(parent):
    for child in parent.winfo_children():
        if isinstance(child, (tk.Text, tk.Listbox)):
            child.configure(
                background=INPUT,
                foreground=TEXT,
                selectbackground=SELECT,
                selectforeground=TEXT,
                highlightbackground=BORDER,
                highlightcolor=ACCENT,
                relief="flat",
            )
            if isinstance(child, tk.Text):
                child.configure(insertbackground=ACCENT)
        elif isinstance(child, tk.Canvas):
            child.configure(background=BG, highlightthickness=0)
        apply_children(child)


def dark_titlebar(window):
    if os.name != "nt":
        return
    try:
        user = ctypes.windll.user32
        user.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user.GetAncestor.restype = ctypes.c_void_p
        hwnd = user.GetAncestor(window.winfo_id(), 2) or window.winfo_id()
        enabled = ctypes.c_int(1)
        dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
        dwm.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        dwm(hwnd, 20, ctypes.byref(enabled), ctypes.sizeof(enabled))
    except (AttributeError, OSError):
        pass
