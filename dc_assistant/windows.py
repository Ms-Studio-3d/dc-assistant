"""Center windows on their owner, bounded by that monitor's usable area."""

import ctypes
from ctypes import wintypes
import os


def fitted_geometry(size, work, anchor=None, margin=16, decoration=(16, 40)):
    left, top, right, bottom = work
    max_width = max(1, right - left - margin * 2)
    max_height = max(1, bottom - top - margin * 2)
    outer_width = min(size[0] + decoration[0], max_width)
    outer_height = min(size[1] + decoration[1], max_height)
    reference = anchor or work
    x = (reference[0] + reference[2] - outer_width) // 2
    y = (reference[1] + reference[3] - outer_height) // 2
    x = max(left + margin, min(x, right - margin - outer_width))
    y = max(top + margin, min(y, bottom - margin - outer_height))
    return (
        max(1, outer_width - decoration[0]),
        max(1, outer_height - decoration[1]),
        x,
        y,
    )


def native_bounds(window):
    if os.name != "nt":
        return None
    user = ctypes.windll.user32
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user.MonitorFromWindow.restype = wintypes.HANDLE
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetWindowRect.restype = wintypes.BOOL

    class MonitorInfo(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD),
            ("monitor", wintypes.RECT),
            ("work", wintypes.RECT),
            ("flags", wintypes.DWORD),
        ]

    user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    user.GetMonitorInfoW.restype = wintypes.BOOL
    hwnd = user.GetAncestor(window.winfo_id(), 2) or window.winfo_id()
    info = MonitorInfo()
    info.size = ctypes.sizeof(info)
    monitor = user.MonitorFromWindow(hwnd, 2)
    rect = wintypes.RECT()
    if not monitor or not user.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    user.GetWindowRect(hwnd, ctypes.byref(rect))
    work = (info.work.left, info.work.top, info.work.right, info.work.bottom)
    bounds = (rect.left, rect.top, rect.right, rect.bottom)
    return work, bounds


def place_window(window, size, parent=None, *, show=True, modal=False):
    window.update_idletasks()
    target = parent or window
    native = native_bounds(target)
    if native:
        work, owner = native
    else:
        x, y = target.winfo_vrootx(), target.winfo_vrooty()
        work = (x, y, x + target.winfo_vrootwidth(), y + target.winfo_vrootheight())
        owner = (
            target.winfo_rootx(),
            target.winfo_rooty(),
            target.winfo_rootx() + target.winfo_width(),
            target.winfo_rooty() + target.winfo_height(),
        )
    anchor = owner if parent is not None and parent.winfo_viewable() else None
    decoration = (16, 40)
    if os.name == "nt":
        try:
            user = ctypes.windll.user32
            user.GetDpiForWindow.argtypes = [wintypes.HWND]
            user.GetDpiForWindow.restype = wintypes.UINT
            metrics = user.GetSystemMetricsForDpi
            metrics.argtypes = [ctypes.c_int, wintypes.UINT]
            metrics.restype = ctypes.c_int
            dpi = user.GetDpiForWindow(target.winfo_id()) or 96
            padding = metrics(92, dpi)
            decoration = (
                2 * (metrics(32, dpi) + padding),
                2 * (metrics(33, dpi) + padding) + metrics(4, dpi),
            )
        except (AttributeError, OSError):
            pass
    preferred = (size[0], max(size[1], window.winfo_reqheight()))
    width, height, x, y = fitted_geometry(
        preferred, work, anchor, decoration=decoration
    )
    old_min = window.minsize()
    window.minsize(min(old_min[0], width), min(old_min[1], height))
    window.geometry(f"{width}x{height}+{x}+{y}")
    if show:
        window.deiconify()
        window.update_idletasks()
        from .theme import dark_titlebar

        dark_titlebar(window)
        if parent is not None and parent.winfo_viewable():
            window.lift(parent)
        if modal:
            window.grab_set()
        window.focus_set()
