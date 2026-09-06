"""Discover local installations/dumps and use the selected PCSX2 configuration.

No dependency on an executable's exact basename, install directory, or a
particular player's save. Searches and disc reads are bounded and read-only.
"""
from __future__ import annotations

from collections import deque
import ctypes
import os
from pathlib import Path
import re
import shutil
import struct
import time

DISC_EXTENSIONS = {".iso", ".chd", ".cso", ".gz"}
SKIP_DIRS = {"windows", "appdata", "$recycle.bin", "system volume information",
             "node_modules", "venv", "__pycache__", "bios", "memcards", "sstates",
             "research", "build-release", ".git"}


def same_path(a, b):
    return bool(a and b) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def running_emulators():
    """Enumerate process images without assuming the Qt executable basename."""
    if os.name != "nt":
        return []
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot in (0, ctypes.c_void_p(-1).value):
        return []
    class Entry(ctypes.Structure):
        _fields_ = [("dwSize",ctypes.c_ulong),("cntUsage",ctypes.c_ulong),
                    ("th32ProcessID",ctypes.c_ulong),("th32DefaultHeapID",ctypes.c_void_p),
                    ("th32ModuleID",ctypes.c_ulong),("cntThreads",ctypes.c_ulong),
                    ("th32ParentProcessID",ctypes.c_ulong),("pcPriClassBase",ctypes.c_long),
                    ("dwFlags",ctypes.c_ulong),("szExeFile",ctypes.c_wchar*260)]
    kernel32.Process32FirstW.argtypes = (ctypes.c_void_p,ctypes.POINTER(Entry))
    kernel32.Process32NextW.argtypes = (ctypes.c_void_p,ctypes.POINTER(Entry))
    entry = Entry(); entry.dwSize = ctypes.sizeof(entry)
    result = []
    try:
        more = kernel32.Process32FirstW(snapshot,ctypes.byref(entry))
        while more:
            process_name = entry.szExeFile.casefold()
            if (process_name.startswith("pcsx2")
                    and not any(word in process_name for word in ("installer","updater","uninstall","crash"))):
                path = process_image_path(entry.th32ProcessID)
                if path:
                    directory = Path(path).parent
                    result.append(dict(pid=int(entry.th32ProcessID),path=path,
                        portable=any((directory/name).is_file() for name in ("portable.ini","portable.txt"))))
            more = kernel32.Process32NextW(snapshot,ctypes.byref(entry))
        portable_pids = command_line_portable_pids([row["pid"] for row in result])
        for row in result:
            row["portable"] = row["portable"] or row["pid"] in portable_pids
        return result
    finally:
        kernel32.CloseHandle(snapshot)


def command_line_portable_pids(pids):
    """Detect explicit -portable launches; release COM objects before uninitializing."""
    if not pids:
        return set()
    try:
        import pythoncom
        import win32com.client
    except Exception:
        return set()
    pythoncom.CoInitialize()
    service = rows = row = None
    try:
        service = win32com.client.GetObject("winmgmts:")
        clause = " OR ".join(f"ProcessId={int(pid)}" for pid in pids)
        rows = service.ExecQuery("SELECT ProcessId, CommandLine FROM Win32_Process WHERE " + clause)
        return {int(row.ProcessId) for row in rows
                if re.search(r"(?:^|\s)-portable(?:\s|$)",str(row.CommandLine or ""),re.I)}
    except Exception:
        return set()
    finally:
        row = None; rows = None; service = None
        pythoncom.CoUninitialize()


def process_image_path(pid):
    if os.name != "nt":
        return ""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.QueryFullProcessImageNameW.argtypes = (
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong))
    kernel32.QueryFullProcessImageNameW.restype = ctypes.c_bool
    process = kernel32.OpenProcess(0x1000, False, int(pid))
    if not process:
        return ""
    try:
        size = ctypes.c_ulong(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(process,0,buffer,ctypes.byref(size)):
            return buffer.value
        return ""
    finally:
        kernel32.CloseHandle(process)


def user_documents():
    if os.name == "nt":
        try:
            from win32com.shell import shell, shellcon
            return Path(shell.SHGetFolderPath(0, shellcon.CSIDL_PERSONAL, None, 0))
        except Exception:
            pass
    return Path.home() / "Documents"


def config_path(executable, portable=False, documents=None):
    directory = Path(executable).resolve().parent
    if portable or any((directory / name).is_file() for name in ("portable.ini", "portable.txt")):
        return directory / "inis/PCSX2.ini", True
    return Path(documents or user_documents()) / "PCSX2/inis/PCSX2.ini", False


def ini_values(path):
    """PCSX2 repeats GameList keys; keep every value instead of ConfigParser's last."""
    section = ""
    result = {}
    try:
        text = Path(path).read_text("utf-8-sig")
    except (OSError, UnicodeError):
        return result
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].casefold()
        elif "=" in line and not line.startswith(("#", ";")):
            key, value = line.split("=", 1)
            result.setdefault((section, key.strip().casefold()), []).append(value.strip())
    return result


def connection_settings(executable, portable=False, documents=None):
    path, portable = config_path(executable, portable, documents)
    values = ini_values(path)
    enabled = values.get(("emucore", "enablepine"), ["false"])[-1].casefold() in ("true", "1", "yes")
    try:
        port = int(values.get(("emucore", "pineslot"), ["28011"])[-1])
        if not 1 <= port <= 65535:
            raise ValueError()
    except ValueError:
        raise ValueError(f"Invalid PINE slot in {path}. Choose a port from 1 to 65535 in PCSX2.")
    return dict(config=str(path), portable=portable, port=port, enabled=enabled)


def prepare_connection(executable, portable=False, processes=None):
    """Enable only PINE in the chosen closed installation, retaining all other settings."""
    if not Path(executable).is_file():
        raise ValueError("Find or choose your PCSX2 executable in Settings first.")
    processes = running_emulators() if processes is None else processes
    selected = next((p for p in processes if same_path(p["path"], executable)), None)
    settings = connection_settings(executable, portable or bool(selected and selected["portable"]))
    path = Path(settings["config"])
    if settings["enabled"]:
        return dict(settings, message=f"PINE connection ready on port {settings['port']}.", running=bool(selected))
    # Installed copies can share Documents configuration. Never edit a running instance's INI.
    if any(same_path(config_path(p["path"], p["portable"])[0], path) for p in processes):
        return dict(settings, running=True, message="PINE is disabled in this PCSX2 configuration. Close PCSX2 normally, then choose Open game to enable the guide connection automatically.")
    if not path.is_file():
        return dict(settings, running=False, message="Complete PCSX2's first-time setup, then close PCSX2 and choose Open game again to enable the guide connection.")
    original = path.read_bytes()
    text = original.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    section, inserted, found = "", False, False
    output = []
    for line in lines:
        if line.strip().startswith("[") and line.strip().endswith("]"):
            if section == "emucore" and not inserted:
                output.append("EnablePINE = true"); inserted = True
            section = line.strip()[1:-1].casefold()
            found |= section == "emucore"
        if section == "emucore" and re.match(r"\s*EnablePINE\s*=", line, re.I):
            output.append("EnablePINE = true"); inserted = True
        else:
            output.append(line)
    if not inserted:
        if not found:
            output.extend(["", "[EmuCore]"])
        output.append("EnablePINE = true")
    backup = path.with_name(path.name + f".bt2-backup-{time.time_ns()}")
    with backup.open("xb") as handle:
        handle.write(original)
    # Detect a settings save/start racing this operation before modifying anything.
    if path.read_bytes() != original:
        raise OSError("PCSX2 settings changed during setup. Close PCSX2 and try again.")
    temporary = path.with_name(path.name + f".bt2-{time.time_ns()}.tmp")
    try:
        temporary.write_bytes((b"\xef\xbb\xbf" if original.startswith(b"\xef\xbb\xbf") else b"") + (newline.join(output)+newline).encode("utf-8"))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return dict(settings, enabled=True, running=False, message=f"Enabled the guide connection on port {settings['port']}. A PCSX2 settings backup was saved beside its INI.")


def active_connection(executable="", portable=False):
    processes = running_emulators()
    matches = [p for p in processes if same_path(p["path"], executable)]
    if len(matches) > 1 or (not matches and len(processes) > 1):
        raise OSError("Multiple PCSX2 instances are open. Close the extra instances so the guide can identify the game window and connection.")
    selected = matches[0] if matches else (processes[0] if len(processes) == 1 else None)
    if selected:
        executable = selected["path"]
        portable = selected["portable"] or (portable and bool(matches))
    settings = connection_settings(executable, portable) if executable else dict(port=28011, enabled=True, portable=False)
    settings["pid"] = selected["pid"] if selected else 0
    if selected and not settings["enabled"]:
        raise OSError("PINE is disabled. Close PCSX2 normally, then use Open game in the guide to enable its connection.")
    return settings


def iso_serial(path):
    """Read the ISO9660 root SYSTEM.CNF, not a multi-gigabyte image scan."""
    try:
        with Path(path).open("rb") as stream:
            stream.seek(16*2048)
            descriptor = stream.read(2048)
            if descriptor[:7] != b"\x01CD001\x01":
                return None
            record = descriptor[156:190]
            sector, length = struct.unpack_from("<I", record, 2)[0], struct.unpack_from("<I", record, 10)[0]
            if length > 2*1024*1024:
                return None
            stream.seek(sector*2048)
            directory = stream.read(length)
            offset = 0
            while offset < len(directory):
                size = directory[offset]
                if not size:
                    offset = (offset//2048+1)*2048
                    continue
                entry = directory[offset:offset+size]
                if len(entry) < 34:
                    return None
                if entry[33:33+entry[32]].split(b";")[0].upper() == b"SYSTEM.CNF":
                    stream.seek(struct.unpack_from("<I",entry,2)[0]*2048)
                    data = stream.read(min(struct.unpack_from("<I",entry,10)[0], 8192))
                    match = re.search(rb"BOOT2\s*=.*?([A-Z]{4})[_-](\d{3})[.](\d{2})", data, re.I)
                    return (match[1]+b"-"+match[2]+match[3]).decode().upper() if match else None
                offset += size
    except (OSError, ValueError, struct.error):
        pass
    return None


def cached_games(config):
    """Recognize supported PCSX2 cache v34 records, including renamed CHD dumps."""
    values = ini_values(config)
    base = Path(config).parent.parent
    cache = Path(values.get(("folders", "cache"), ["cache"])[-1])
    cache = cache if cache.is_absolute() else base/cache
    path = cache/"gamelist.cache"
    try:
        if path.stat().st_size > 32*1024*1024:
            return []
        with path.open("rb") as stream:
            if stream.read(8) != struct.pack("<II",0x45434C47,34):
                return []
            result = []
            def string():
                size = struct.unpack("<I",stream.read(4))[0]
                if size > 32768:
                    raise ValueError()
                return stream.read(size).decode("utf-8")
            while stream.tell() < path.stat().st_size:
                filename, serial = string(), string()
                for _ in range(3): string()
                tail = stream.read(23)
                if len(tail) != 23:
                    raise ValueError()
                _,_,size,modified,crc,_ = struct.unpack("<BBQQIB",tail)
                candidate = Path(filename)
                if serial == "SLUS-21441" and crc == 0xFE961D28 and candidate.is_file() and int(candidate.stat().st_mtime) == modified:
                    result.append(dict(path=str(candidate), label=f"USA BT2 (PCSX2 library): {candidate}", verified=True))
            return result
    except (OSError, ValueError, UnicodeError, struct.error):
        return []


def search_roots():
    home = Path.home()
    roots = [user_documents(), home/"Downloads", home/"Desktop"]
    for key in ("ProgramFiles", "ProgramFiles(x86)"):
        if os.environ.get(key): roots.append(Path(os.environ[key]))
    if os.environ.get("OneDrive"):
        roots.extend([Path(os.environ["OneDrive"])/"Documents", Path(os.environ["OneDrive"])/"Desktop"])
    # All local/removable drives: breadth-first scan also finds portable copies on other disks.
    if os.name == "nt":
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            path = f"{letter}:\\"
            if ctypes.windll.kernel32.GetDriveTypeW(path) in (2,3):
                roots.extend([Path(path)/"Games",Path(path)/"Emulators",Path(path)/"PCSX2"])
    return roots


def discover(executable="", game="", roots=None, seconds=20, processes=None):
    processes = running_emulators() if processes is None else processes
    deadline = time.monotonic()+seconds
    emulators, games, seen, inspected = {}, {}, set(), set()
    queue = deque()
    entries = 0
    def add_root(path, depth=0):
        if path: queue.append((Path(path),depth))
    def add_emulator(path, portable=False):
        path = Path(path)
        if (not path.is_file() or path.suffix.casefold() != ".exe"
                or any(word in path.stem.casefold() for word in ("installer","updater","uninstall","crash"))): return
        if str(path.resolve()) in emulators: return
        config, mode = config_path(path, portable)
        key = str(path.resolve())
        emulators[key] = dict(path=key, portable=mode, config=str(config),
            label=f"PCSX2 ({'portable' if mode else 'installed/shared settings'}): {path}")
        for row in cached_games(config): games[row["path"]] = row
        values = ini_values(config)
        for name in ("paths", "recursivepaths"):
            for folder in values.get(("gamelist", name), []):
                folder = Path(folder)
                add_root(folder if folder.is_absolute() else config.parent.parent/folder)
        add_root(path.parent)
    for process in processes:
        add_emulator(process["path"], process["portable"])
    if executable and executable not in emulators: add_emulator(executable)
    def inspect_game(path):
        key = str(path.resolve())
        if key in inspected or key in games: return
        inspected.add(key)
        name = re.sub(r"[^a-z0-9]", "", path.stem.casefold())
        likely = "budokaitenkaichi2" in name or "slus21441" in name
        # PCSX2's cache verifies arbitrarily renamed/compressed files. Outside
        # its library, avoid opening every multi-gigabyte disc on the computer.
        if path.suffix.casefold() == ".iso" and (likely or same_path(path,game)):
            serial = iso_serial(path)
            if serial == "SLUS-21441":
                games[key] = dict(path=key,label=f"USA BT2 (disc verified): {path}",verified=True)
                return
            if serial: return  # Never suggest a known different game/region based on its name.
        if likely and not any(x in name for x in ("europe", "japan", "pal")):
            games[key] = dict(path=key,label=f"BT2 candidate (filename only): {path}",verified=False)
    if game and Path(game).is_file(): inspect_game(Path(game))
    for root in (search_roots() if roots is None else roots): add_root(root)
    while queue and time.monotonic() < deadline and entries < 150000:
        directory, depth = queue.popleft()
        key = str(directory).casefold()
        if key in seen or depth > 9: continue
        seen.add(key)
        try:
            with os.scandir(directory) as listing:
                for entry in listing:
                    entries += 1
                    if entries >= 150000 or time.monotonic() >= deadline: break
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name.casefold() not in SKIP_DIRS and not entry.name.startswith("."):
                            add_root(entry.path,depth+1)
                    elif entry.is_file(follow_symlinks=False):
                        path = Path(entry.path)
                        if path.suffix.casefold() == ".exe" and re.match(r"pcsx2(?:[-_.]|$)",path.stem,re.I) and not any(x in path.stem.casefold() for x in ("installer", "updater", "uninstall", "crash")):
                            add_emulator(path)
                        elif path.suffix.casefold() in DISC_EXTENSIONS:
                            inspect_game(path)
        except OSError:
            continue
    return dict(emulators=list(emulators.values()), games=sorted(games.values(),key=lambda row:not row["verified"]),
                partial=bool(queue), message=f"Found {len(emulators)} PCSX2 installation(s) and {len(games)} BT2 dump candidate(s)." + (" Search limit reached; you can search again or browse another location." if queue else ""))
