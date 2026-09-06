"""NVDA controller client first, with lazy SAPI fallback and failover."""
from __future__ import annotations
import ctypes
from pathlib import Path
import struct


class NvdaClient:
    def __init__(self):
        arch = "x64" if struct.calcsize("P")==8 else "x86"
        path = Path(__file__).resolve().parents[1]/"vendor/nvda"/arch/"nvdaControllerClient.dll"
        self.library = ctypes.WinDLL(str(path))
        for name,arguments in (("testIfRunning",[]),("speakText",[ctypes.c_wchar_p]),("cancelSpeech",[])):
            function = getattr(self.library,"nvdaController_"+name)
            function.argtypes = arguments
            function.restype = ctypes.c_long

    def running(self):
        return self.library.nvdaController_testIfRunning()==0

    def speak(self,text,interrupt):
        if interrupt:
            self.library.nvdaController_cancelSpeech()
        return self.library.nvdaController_speakText(text)==0

    def cancel(self):
        self.library.nvdaController_cancelSpeech()


class SapiClient:
    def __init__(self):
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        self.voice = win32com.client.Dispatch("SAPI.SpVoice")

    def speak(self,text,interrupt):
        self.voice.Speak(text,1 | (2 if interrupt else 0))
        return True

    def cancel(self):
        self.voice.Speak("",3)


class SpeechRouter:
    def __init__(self,nvda=None,sapi_factory=SapiClient):
        self.nvda=nvda
        self.sapi_factory=sapi_factory
        self.sapi=None
        self.backend="Text"

    def speak(self,text,interrupt=True):
        if self.nvda is not None:
            try:
                if self.nvda.running():
                    if self.backend=="SAPI" and self.sapi is not None:
                        self.sapi.cancel()
                    if self.nvda.speak(text,interrupt):
                        self.backend="NVDA"
                        return self.backend
            except Exception:
                pass  # A reader restart must not stop gameplay guidance.
        try:
            if self.sapi is None:
                self.sapi=self.sapi_factory()
            self.sapi.speak(text,interrupt)
            self.backend="SAPI"
        except Exception:
            self.backend="Text"
        return self.backend

    def cancel(self):
        try:
            if self.backend=="NVDA" and self.nvda is not None:
                self.nvda.cancel()
            elif self.sapi is not None:
                self.sapi.cancel()
        except Exception:
            pass
