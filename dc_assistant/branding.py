"""The user-approved connected DC identity."""

import ctypes
import os
from pathlib import Path
import tkinter as tk

ASSETS = Path(__file__).with_name("assets")
APP_ID = "MsStudio.DCAssistant"


def configure_process():
    if os.name != "nt":
        return
    try:
        shell = ctypes.windll.shell32
        shell.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
        shell.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass
    try:
        function = ctypes.windll.user32.SetProcessDpiAwarenessContext
        function.argtypes = [ctypes.c_void_p]
        function.restype = ctypes.c_bool
        function(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass


def apply_brand(root):
    images = [
        tk.PhotoImage(master=root, file=str(ASSETS / f"dc-{size}.png"))
        for size in (16, 32, 48, 128)
    ]
    root.iconphoto(True, *images)
    if os.name == "nt":
        root.iconbitmap(str(ASSETS / "dc-assistant.ico"))
        root.iconbitmap(default=str(ASSETS / "dc-assistant.ico"))
    root._brand_images = images
    root.brand_logo = tk.PhotoImage(master=root, file=str(ASSETS / "dc-logo.png"))
