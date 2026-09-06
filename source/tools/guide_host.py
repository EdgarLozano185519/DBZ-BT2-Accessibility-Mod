"""Hidden desktop worker and JSON requests for the native Windows interface."""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import traceback

from bt2.profiles import default_store

WORKER_VERSION = "2026.09.05-r4"


def request(payload):
    action = payload.get("action")
    if action == "discover":
        from bt2.pcsx2 import discover
        return discover(payload.get("emulator", ""),payload.get("game", ""))
    if action == "prepare":
        from bt2.pcsx2 import prepare_connection
        return prepare_connection(payload.get("emulator", ""),bool(payload.get("portable",False)))
    store = default_store()
    if action == "status":
        maps = [dict(fingerprint=p.fingerprint, number=p.number, label=p.display_name,
                     name=p.name or "") for p in sorted(store.maps.values(),key=lambda p:p.number)]
        return dict(save="Uses your memory card configured in PCSX2", maps=maps)
    if action == "rename":
        name = str(payload.get("name", "")).strip()
        if not name or len(name)>100 or any(ord(c)<32 for c in name):
            raise ValueError("Enter a map name between 1 and 100 characters.")
        profile = store.maps.get(payload.get("fingerprint"))
        if profile is None:
            raise ValueError("This map is no longer in the atlas. Refresh the map list.")
        profile.name = name
        store.save_map(profile)
        return dict(message=f"Map {profile.number} is now called {name}.")
    raise ValueError("Unknown desktop request")


def watch_commands(stream, stop):
    # Closing the UI's input pipe is also a shutdown request, so an orphaned
    # worker cannot keep speaking or responding to controller buttons.
    for line in stream:
        if line.strip() == "stop":
            break
    stop.set()


def request_response(payload):
    """Every desktop request returns JSON, including unforeseen platform errors."""
    try:
        return dict(ok=True,data=request(payload))
    except Exception as error:
        return dict(ok=False,error=f"{type(error).__name__}: {error}")


def report_fatal(error):
    """Preserve the cause instead of letting the bootloader replace it."""
    message = f"Guide startup error ({type(error).__name__}): {error}"
    print(message,file=sys.stderr,flush=True)
    traceback.print_exc(file=sys.stderr)
    try:
        directory = os.path.join(os.environ.get("BT2_DATA_DIR",os.getcwd()),"logs")
        os.makedirs(directory,exist_ok=True)
        with open(os.path.join(directory,"last-worker-error.txt"),"w",encoding="utf-8") as handle:
            handle.write(f"DBZ BT2 Accessibility Guide {WORKER_VERSION}\n{message}\n\n")
            traceback.print_exc(file=handle)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request",action="store_true")
    parser.add_argument("--silent",action="store_true")
    parser.add_argument("--check-runtime",action="store_true")
    args = parser.parse_args()
    if args.check_runtime:
        # Exercise bundled native dependencies without launching or modifying a game.
        import numpy
        import scipy.ndimage
        import win32gui, win32ui
        from PIL import Image, ImageGrab
        from pine_client import PineClient
        from bt2.guide import waiting_guide
        from bt2.menus import MenuReader
        from bt2.speech_output import NvdaClient, SapiClient
        reader = NvdaClient()
        sapi = SapiClient()
        sapi.cancel()
        print(json.dumps(dict(ok=True, nvda_running=reader.running(),
                              numpy=numpy.__version__)),flush=True)
        return
    if args.request:
        response = request_response(json.load(sys.stdin))
        print(json.dumps(response,ensure_ascii=False),flush=True)
        # The UI must be able to parse and display an error response. Reserve
        # nonzero exit codes for failures that happen outside request handling.
        return 0
    from bt2.guide import waiting_guide
    from bt2.speech import Speaker
    os.environ["BT2_DESKTOP_UI"] = "1"
    stop = threading.Event()
    threading.Thread(target=watch_commands,args=(sys.stdin,stop),daemon=True).start()
    try:
        print(f"DBZ BT2 Accessibility Guide {WORKER_VERSION}.",flush=True)
        waiting_guide("objective",stop_event=stop,speaker=Speaker(enabled=not args.silent))
    finally:
        print("Guide stopped.",flush=True)
    return 0


def entry():
    try:
        return main() or 0
    except Exception as error:
        report_fatal(error)
        return 1


if __name__ == "__main__":
    raise SystemExit(entry())
