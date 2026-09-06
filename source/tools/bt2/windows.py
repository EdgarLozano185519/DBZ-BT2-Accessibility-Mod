"""Shared process-owned render-window selection for capture and hotkeys."""
import os
import re


def render_candidates(rows, pid=0):
    rows = [r for r in rows if r["visible"] and r["width"]>=320 and r["height"]>=240
            and (r["pid"]==pid if pid else r.get("pcsx2",False))]
    def score(row):
        title = re.sub(r"[^a-z0-9]","",row["title"].casefold())
        if "budokaitenkaichi2" in title or "slus21441" in title: return 2
        if "pcsx2" in title and not row.get("owned",False): return 1
        return 0
    if not rows: return []
    best = max(map(score,rows))
    return [r["handle"] for r in rows if score(r)==best and best>0]


def game_windows():
    import win32con, win32gui, win32process
    from .pcsx2 import process_image_path
    pid = int(os.environ.get("BT2_EMULATOR_PID","0"))
    rows = []
    def collect(handle, _):
        _, owner = win32process.GetWindowThreadProcessId(handle)
        is_pcsx2 = False
        if not pid:
            path = process_image_path(owner)
            if not path:
                return
            is_pcsx2 = os.path.basename(path).casefold().startswith("pcsx2")
        if pid and owner != pid: return
        left,top,right,bottom = win32gui.GetWindowRect(handle)
        rows.append(dict(handle=handle,pid=owner,pcsx2=is_pcsx2,title=win32gui.GetWindowText(handle),
            width=right-left,height=bottom-top,visible=win32gui.IsWindowVisible(handle),
            owned=bool(win32gui.GetWindow(handle,win32con.GW_OWNER))))
    win32gui.EnumWindows(collect,None)
    return render_candidates(rows,pid)


def game_has_focus():
    import win32gui
    # Only the render window qualifies: emulator Settings and debugger dialogs do not.
    foreground = win32gui.GetForegroundWindow()
    return foreground in game_windows()
