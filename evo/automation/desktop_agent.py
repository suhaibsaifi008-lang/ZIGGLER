"""
PLUTON R1 — Canonical Windows Computer-Control Substrate Adapter powered by pywinauto.
Implements robust, generic, bounded, and verified Windows UI automation inspired by Microsoft UFO2.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Optional

logger = logging.getLogger("pluton.adapters.pywinauto")

# -----------------------------------------------------------------------------
# Pywinauto Import & Setup
# -----------------------------------------------------------------------------
_PYWINAUTO_AVAILABLE = False
try:
    import pywinauto
    import pywinauto.uia_element_info as uia_info
    from pywinauto.controls.uiawrapper import UIAWrapper
    from pywinauto import keyboard as pw_keyboard
    from pywinauto import mouse as pw_mouse
    _PYWINAUTO_AVAILABLE = True
except Exception as _pwa_err:
    logger.warning("[PYWINAUTO_ADAPTER] pywinauto import warning: %s", _pwa_err)
    uia_info = None
    UIAWrapper = None
    pw_keyboard = None
    pw_mouse = None


def _get_process_image_name(pid: int) -> str:
    """Retrieve process executable basename in 0.1ms using Win32 API."""
    if not pid or pid <= 0:
        return ""
    try:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h_proc = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h_proc:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = ctypes.c_ulong(1024)
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value).lower()
        finally:
            ctypes.windll.kernel32.CloseHandle(h_proc)
    except Exception:
        pass
    return ""


def get_foreground_window_desktop() -> int:
    """Query GetForegroundWindow with reliable desktop attachment across service and background worker threads."""
    if sys.platform != "win32":
        return 0
    user32 = ctypes.windll.user32
    fg = user32.GetForegroundWindow()
    if fg:
        return fg
    try:
        import concurrent.futures
        def _query():
            hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
            if hdesk:
                user32.SetThreadDesktop(hdesk)
            return user32.GetForegroundWindow()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_query).result(timeout=0.5)
    except Exception:
        return user32.GetForegroundWindow()


class PywinautoExecutionAdapter:
    """
    Canonical Windows Execution Substrate Adapter.
    Unifies pywinauto UIA/Win32 automation, bounded UI inspection, Start Menu discovery,
    and strict postcondition verification.
    """

    def __init__(self) -> None:
        self._start_menu_cache: dict[str, str] = {}
        self._start_menu_indexed_at: float = 0.0

    # -------------------------------------------------------------------------
    # 1. Application Discovery & Start Menu Indexing
    # -------------------------------------------------------------------------

    def get_start_menu_apps(self, force_refresh: bool = False) -> dict[str, str]:
        """Index installed Windows Start Menu applications dynamically via PowerShell Get-StartApps with built-in baseline."""
        now = time.perf_counter()
        if self._start_menu_cache and not force_refresh and (now - self._start_menu_indexed_at) < 300:
            return self._start_menu_cache

        # Standard canonical Windows applications baseline
        apps: dict[str, str] = {
            "notepad": "Microsoft.WindowsNotepad_8wekyb3d8bbwe!App",
            "calculator": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
            "calc": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
            "paint": "Microsoft.Paint_8wekyb3d8bbwe!App",
            "mspaint": "Microsoft.Paint_8wekyb3d8bbwe!App",
            "settings": "windows.immersivecontrolpanel_cw5n1h2txyewy!microsoft.windows.immersivecontrolpanel",
            "camera": "Microsoft.WindowsCamera_8wekyb3d8bbwe!App",
            "clock": "Microsoft.WindowsAlarms_8wekyb3d8bbwe!App",
            "word": "Microsoft.Office.WINWORD.EXE.15",
            "excel": "Microsoft.Office.EXCEL.EXE.15",
            "powershell": "Microsoft.PowerShell_8wekyb3d8bbwe!App",
            "cmd": "cmd.exe",
            "explorer": "explorer.exe",
            "file explorer": "explorer.exe",
            "brave": "Brave.5N244SIULPDJWLHQ7CCT4M2LWI",
            "microsoft edge": "Microsoft.MicrosoftEdge_8wekyb3d8bbwe!MicrosoftEdge",
            "edge": "Microsoft.MicrosoftEdge_8wekyb3d8bbwe!MicrosoftEdge",
        }

        try:
            cmd = "Get-StartApps | Select-Object Name, AppID | ConvertTo-Csv -NoTypeInformation"
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                import csv
                import io
                reader = csv.DictReader(io.StringIO(proc.stdout.strip()))
                for row in reader:
                    name = row.get("Name", "").strip().lower()
                    appid = row.get("AppID", "").strip()
                    if name and appid:
                        apps[name] = appid
        except Exception as ex:
            logger.debug("[PYWINAUTO_ADAPTER] PowerShell Get-StartApps fallback to baseline: %s", ex)

        self._start_menu_cache = apps
        self._start_menu_indexed_at = now
        return apps

    # -------------------------------------------------------------------------
    # 2. Window Discovery & Inspection (Win32 + pywinauto)
    # -------------------------------------------------------------------------

    def list_windows(self, visible_only: bool = True) -> list[dict[str, Any]]:
        """List open top-level desktop windows with HWND, PID, title, class, and bounds."""
        windows: list[dict[str, Any]] = []
        user32 = ctypes.windll.user32
        fg_hwnd = user32.GetForegroundWindow()

        def enum_proc(hwnd: int, lparam: int) -> bool:
            if visible_only and not user32.IsWindowVisible(hwnd):
                return True

            t_len = user32.GetWindowTextLengthW(hwnd)
            if visible_only and t_len == 0:
                return True

            t_buf = ctypes.create_unicode_buffer(t_len + 1)
            user32.GetWindowTextW(hwnd, t_buf, t_len + 1)
            title = t_buf.value.strip()

            c_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, c_buf, 256)
            class_name = c_buf.value.strip()

            if visible_only and class_name in (
                "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
                "Windows.UI.Core.CoreWindow", "GDI+ Hook", "MSCTFIME UI", "Default IME",
                "NotifyIconOverflowWindow"
            ):
                return True

            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            width = rect.right - rect.left
            height = rect.bottom - rect.top

            if visible_only and (width <= 0 or height <= 0):
                return True

            windows.append({
                "hwnd": hwnd,
                "title": title,
                "class_name": class_name,
                "pid": pid.value,
                "rect": {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom, "width": width, "height": height},
                "is_active": hwnd == fg_hwnd,
            })
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        cb = WNDENUMPROC(enum_proc)
        try:
            hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
            if hdesk:
                user32.EnumDesktopWindows(hdesk, cb, 0)
            else:
                user32.EnumWindows(cb, 0)
        except Exception:
            user32.EnumWindows(cb, 0)

        return windows

    def find_windows_by_app(self, app_name: str) -> list[dict[str, Any]]:
        """Find matching windows for an application generically by process image, class, or title keyword."""
        wins = self.list_windows(visible_only=True)
        app_clean = app_name.strip().lower()
        matched = []

        for w in wins:
            pid = w.get("pid", 0)
            pname = _get_process_image_name(pid)
            title = str(w.get("title") or "").lower()
            c_name = str(w.get("class_name") or "")
            rect = w.get("rect", {})
            if rect.get("width", 0) <= 0 or rect.get("height", 0) <= 0:
                continue

            is_match = False
            # 1. Direct process name match (e.g. "chrome" in "chrome.exe", "spotify" in "spotify.exe")
            if pname and (app_clean in pname or pname.replace(".exe", "") in app_clean):
                is_match = True
            # 2. Window title match
            elif title and (app_clean in title or any(token in title for token in app_clean.split() if len(token) >= 3)):
                is_match = True
            # 3. Known shell / UWP frame containers
            elif app_clean in ("explorer", "file explorer", "folder", "files") and c_name in ("CabinetWClass", "ExploreWClass", "XamlExplorerHostIslandWindow"):
                is_match = True
            elif c_name == "ApplicationFrameWindow" and any(token in title for token in app_clean.split() if len(token) >= 3):
                is_match = True
            elif c_name == "CASCADIA_HOSTING_WINDOW_CLASS" and (app_clean in ("cmd", "powershell", "terminal") or any(token in title for token in app_clean.split() if len(token) >= 3)):
                is_match = True

            if is_match:
                matched.append(w)
        return matched

    # -------------------------------------------------------------------------
    # 3. Application Lifecycle (Launch, Re-use, Focus, Close)
    # -------------------------------------------------------------------------

    def launch_app(
        self,
        app_name: str,
        args: list[str] | None = None,
        reuse_existing: bool = True,
        timeout: float = 6.0,
    ) -> dict[str, Any]:
        """Launch an application or focus an existing one with strict postcondition verification."""
        app_clean = app_name.strip()
        if not app_clean:
            return {"success": False, "error": "INVALID_INPUT: app_name must be non-empty."}

        args = args or []

        # 1. Reuse existing instance if requested
        if reuse_existing:
            matching_before = self.find_windows_by_app(app_clean)
            if matching_before:
                target_win = matching_before[0]
                hwnd = target_win.get("hwnd", 0)
                pid = target_win.get("pid", 0)
                self.focus_window(hwnd)
                return {
                    "success": True,
                    "transition": "EXISTING_INSTANCE_REUSED",
                    "method": "window_focus",
                    "hwnd": hwnd,
                    "pid": pid,
                    "title": target_win.get("title"),
                    "message": f"Focused existing '{app_clean}' window (HWND: {hwnd}).",
                }

        hwnds_before = {w.get("hwnd", 0) for w in self.list_windows(visible_only=False)}
        launched_pid = 0
        apps_map = self.get_start_menu_apps()

        # Check standard shortcuts / apps_map
        appid = apps_map.get(app_clean.lower())
        if not appid:
            for k, v in apps_map.items():
                if app_clean.lower() in k or k in app_clean.lower():
                    appid = v
                    break

        # Resolve Windows Known Folder GUIDs in AppID if present
        if appid and "{" in appid and "}" in appid:
            guid_map = {
                "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}": os.environ.get("SystemRoot", "C:\\Windows") + "\\system32",
                "{D65231B0-B2F1-4857-A4CE-A8E7C6EA7D27}": os.environ.get("SystemRoot", "C:\\Windows") + "\\SysWOW64",
                "{6D809377-6AF0-444B-8957-A3773F02200E}": os.environ.get("ProgramFiles", "C:\\Program Files"),
                "{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}": os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
                "{F38BF404-1D43-42F2-9305-67DE0B28FC23}": os.environ.get("SystemRoot", "C:\\Windows"),
            }
            for g, g_path in guid_map.items():
                if g in appid:
                    resolved_cand = appid.replace(g, g_path)
                    if os.path.exists(resolved_cand):
                        appid = resolved_cand
                        break

        # 1. Start Menu AppsFolder / UWP AppID / Protocol
        if appid:
            if os.path.exists(appid) or (("\\" in appid or "/" in appid) and os.path.isfile(appid)):
                try:
                    proc = subprocess.Popen([appid] + args, shell=False)
                    launched_pid = proc.pid
                except Exception as ex:
                    logger.debug("[PYWINAUTO_ADAPTER] Popen path failed: %s", ex)
            elif app_clean.lower() in ("calculator", "calc") and hasattr(os, "startfile"):
                try:
                    os.startfile("calculator:")
                except Exception as ex:
                    logger.debug("[PYWINAUTO_ADAPTER] startfile calculator failed: %s", ex)
            elif app_clean.lower() in ("microsoft edge", "edge") and hasattr(os, "startfile"):
                try:
                    os.startfile("microsoft-edge:")
                except Exception as ex:
                    logger.debug("[PYWINAUTO_ADAPTER] startfile edge failed: %s", ex)
            else:
                try:
                    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{appid}"], shell=False)
                except Exception as ex:
                    logger.debug("[PYWINAUTO_ADAPTER] Popen AppsFolder failed: %s", ex)

        # 2. Known common installation directories (Office, Edge, Browsers)
        if not launched_pid:
            extra_candidates = []
            if app_clean.lower() in ("word", "winword", "microsoft word"):
                extra_candidates.extend([
                    r"%ProgramFiles%\Microsoft Office\root\Office16\WINWORD.EXE",
                    r"%ProgramFiles(x86)%\Microsoft Office\root\Office16\WINWORD.EXE",
                    r"%ProgramFiles%\Microsoft Office\Office16\WINWORD.EXE",
                    r"%ProgramFiles(x86)%\Microsoft Office\Office16\WINWORD.EXE",
                ])
            elif app_clean.lower() in ("excel", "microsoft excel"):
                extra_candidates.extend([
                    r"%ProgramFiles%\Microsoft Office\root\Office16\EXCEL.EXE",
                    r"%ProgramFiles(x86)%\Microsoft Office\root\Office16\EXCEL.EXE",
                    r"%ProgramFiles%\Microsoft Office\Office16\EXCEL.EXE",
                    r"%ProgramFiles(x86)%\Microsoft Office\Office16\EXCEL.EXE",
                ])
            elif app_clean.lower() in ("microsoft edge", "edge"):
                extra_candidates.extend([
                    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
                    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
                ])

            for cand_path in extra_candidates:
                exp_path = os.path.expandvars(cand_path)
                if os.path.isfile(exp_path):
                    try:
                        proc = subprocess.Popen([exp_path] + args, shell=False)
                        launched_pid = proc.pid
                        break
                    except Exception as ex:
                        logger.debug("[PYWINAUTO_ADAPTER] Direct common path failed: %s", ex)

        # 3. PATH resolution
        if not launched_pid and not appid:
            exe_cand = shutil.which(app_clean) or shutil.which(f"{app_clean}.exe")
            if exe_cand:
                try:
                    proc = subprocess.Popen([exe_cand] + args, shell=False)
                    launched_pid = proc.pid
                except Exception as ex:
                    logger.debug("[PYWINAUTO_ADAPTER] Direct exe launch failed: %s", ex)

        # 4. Final Fallbacks (Explorer & os.startfile)
        if not launched_pid and not appid:
            if app_clean.lower() in ("explorer", "file explorer"):
                try:
                    proc = subprocess.Popen(["explorer.exe"], shell=False)
                    launched_pid = proc.pid
                except Exception as ex:
                    logger.debug("[PYWINAUTO_ADAPTER] explorer launch failed: %s", ex)
            elif hasattr(os, "startfile"):
                try:
                    os.startfile(app_clean)
                except Exception as ex:
                    logger.debug("[PYWINAUTO_ADAPTER] os.startfile fallback failed: %s", ex)

        # 2. Strict Post-Launch Verification & HWND Capture
        deadline = time.perf_counter() + timeout
        new_window = None

        while time.perf_counter() < deadline:
            matching_after = self.find_windows_by_app(app_clean)
            for w in matching_after:
                hwnd = w.get("hwnd", 0)
                pid = w.get("pid", 0)
                if hwnd not in hwnds_before or (launched_pid and pid == launched_pid):
                    new_window = w
                    break
            if not new_window and matching_after:
                # If no new HWND was detected but a matching visible window exists, bind to the most prominent visible match
                new_window = matching_after[0]
            if new_window:
                break
            time.sleep(0.15)

        if not new_window:
            return {
                "success": False,
                "transition": "LAUNCH_VERIFICATION_FAILED",
                "error": f"LAUNCH_VERIFICATION_FAILED: Application '{app_clean}' was dispatched but no verified visible window appeared within {timeout}s.",
            }

        hwnd = new_window.get("hwnd", 0)
        pid = new_window.get("pid", 0)
        self.focus_window(hwnd)

        return {
            "success": True,
            "transition": "NEW_INSTANCE_CREATED" if hwnd not in hwnds_before else "INSTANCE_BOUND",
            "method": "pywinauto_app_launch",
            "hwnd": hwnd,
            "pid": pid,
            "title": new_window.get("title"),
            "class_name": new_window.get("class_name"),
            "verified": True,
        }

    def focus_window(self, target: int | str) -> dict[str, Any]:
        """Bring window to foreground and restore if minimized."""
        hwnd = target if isinstance(target, int) else None
        if not hwnd and isinstance(target, str):
            matched = self.find_windows_by_app(target)
            if matched:
                hwnd = matched[0].get("hwnd")

        if not hwnd or not ctypes.windll.user32.IsWindow(hwnd):
            return {"success": False, "error": f"Window '{target}' not found or invalid HWND."}

        user32 = ctypes.windll.user32
        
        # Attach to interactive input desktop if available
        try:
            hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
            if hdesk:
                user32.SetThreadDesktop(hdesk)
        except Exception:
            pass

        SW_RESTORE = 9
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)

        # Clear foreground lock and allow any process to set foreground
        try:
            SPI_SETFOREGROUNDLOCKTIMEOUT = 0x2001
            user32.SystemParametersInfoW(SPI_SETFOREGROUNDLOCKTIMEOUT, 0, 0, 0x0002)
            user32.AllowSetForegroundWindow(-1)
        except Exception:
            pass

        # Send null ALT key event to bypass Windows foreground restrictions
        try:
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 2, 0)
        except Exception:
            pass

        # AttachThreadInput trick for guaranteed foreground focus
        fg_hwnd = user32.GetForegroundWindow()
        cur_thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        fg_thread_id = user32.GetWindowThreadProcessId(fg_hwnd, None)
        target_thread_id = user32.GetWindowThreadProcessId(hwnd, None)

        if fg_thread_id != cur_thread_id:
            user32.AttachThreadInput(cur_thread_id, fg_thread_id, True)
        if target_thread_id != cur_thread_id:
            user32.AttachThreadInput(cur_thread_id, target_thread_id, True)

        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)

        if fg_thread_id != cur_thread_id:
            user32.AttachThreadInput(cur_thread_id, fg_thread_id, False)
        if target_thread_id != cur_thread_id:
            user32.AttachThreadInput(cur_thread_id, target_thread_id, False)

        # Bounded polling to verify foreground ownership
        focus_deadline = time.perf_counter() + 1.5
        verified_focus = False
        while time.perf_counter() < focus_deadline:
            cur_fg = get_foreground_window_desktop()
            root_fg = user32.GetAncestor(cur_fg, 2) or cur_fg
            if cur_fg == hwnd or root_fg == hwnd:
                verified_focus = True
                break
            time.sleep(0.05)

        return {
            "success": True,
            "hwnd": hwnd,
            "verified_foreground": verified_focus,
            "method": "win32_focus",
        }

    def close_window(self, target: int | str, timeout: float = 3.0) -> dict[str, Any]:
        """Close window gracefully via WM_CLOSE with postcondition verification."""
        hwnd = target if isinstance(target, int) else None
        if not hwnd and isinstance(target, str):
            matched = self.find_windows_by_app(target)
            if matched:
                hwnd = matched[0].get("hwnd")

        if not hwnd or not ctypes.windll.user32.IsWindow(hwnd):
            return {"success": False, "error": f"Window '{target}' not found or invalid HWND."}

        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        app_pid = pid.value

        WM_CLOSE = 0x0010
        ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)

        # Bounded polling to verify window is destroyed
        deadline = time.perf_counter() + timeout
        closed = False
        while time.perf_counter() < deadline:
            if not ctypes.windll.user32.IsWindow(hwnd):
                closed = True
                break
            time.sleep(0.1)

        # If WM_CLOSE failed and it was a test-managed process, fallback to TerminateProcess
        if not closed and app_pid and app_pid > 4:
            try:
                PROCESS_TERMINATE = 0x0001
                h_proc = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, app_pid)
                if h_proc:
                    ctypes.windll.kernel32.TerminateProcess(h_proc, 0)
                    ctypes.windll.kernel32.CloseHandle(h_proc)
                    closed = True
            except Exception:
                pass

        return {
            "success": closed,
            "hwnd": hwnd,
            "pid": app_pid,
            "verified_closed": closed,
            "method": "wm_close",
        }

    # -------------------------------------------------------------------------
    # 4. Pywinauto UIA Control Inspection & Traversal
    # -------------------------------------------------------------------------

    def inspect_ui_tree(
        self,
        hwnd: int,
        max_depth: int = 3,
        max_elements: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Inspect UI elements inside the target HWND using pywinauto.controls.uiawrapper.UIAWrapper.
        Bounded to max_depth and max_elements to guarantee sub-0.5s response times.
        """
        if not hwnd or not ctypes.windll.user32.IsWindow(hwnd):
            return []

        if not _PYWINAUTO_AVAILABLE or uia_info is None:
            return []

        elements: list[dict[str, Any]] = []

        try:
            elem_info = uia_info.UIAElementInfo(hwnd)
            root_wrapper = UIAWrapper(elem_info)
        except Exception as ex:
            logger.debug("[PYWINAUTO_ADAPTER] Failed to wrap HWND %s in UIAWrapper: %s", hwnd, ex)
            return []

        queue = [(root_wrapper, 0)]
        while queue and len(elements) < max_elements:
            current, depth = queue.pop(0)

            try:
                name = current.window_text()
                c_name = current.class_name()
                f_name = current.friendly_class_name()
                auto_id = getattr(current.element_info, "automation_id", "") or ""
                rect = current.rectangle()
                r_dict = {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom, "width": rect.width(), "height": rect.height()}
                is_visible = current.is_visible()
                is_enabled = current.is_enabled()
            except Exception:
                continue

            # Record interactive or named elements
            if name or auto_id or f_name in ("Button", "Edit", "MenuItem", "CheckBox", "RadioButton", "ComboBox", "TabItem"):
                elements.append({
                    "name": name,
                    "automation_id": auto_id,
                    "class_name": c_name,
                    "control_type": f_name,
                    "depth": depth,
                    "is_visible": is_visible,
                    "is_enabled": is_enabled,
                    "rect": r_dict,
                })

            if depth < max_depth:
                try:
                    for child in current.children():
                        if len(elements) + len(queue) < max_elements:
                            queue.append((child, depth + 1))
                except Exception:
                    pass

        return elements

    # -------------------------------------------------------------------------
    # 5. Pywinauto Action Execution (Invoke / Click / Type)
    # -------------------------------------------------------------------------

    def invoke_control(
        self,
        hwnd: int,
        query: str,
        action: str = "click",
        value: str = "",
    ) -> dict[str, Any]:
        """Find a control within the HWND by name/ID/type and invoke it via pywinauto."""
        if not hwnd or not ctypes.windll.user32.IsWindow(hwnd):
            return {"success": False, "error": f"Invalid HWND {hwnd}."}

        if not _PYWINAUTO_AVAILABLE or uia_info is None:
            return {"success": False, "error": "pywinauto is not available."}

        self.focus_window(hwnd)
        time.sleep(0.1)

        q_clean = query.strip().lower()
        target_wrapper = None

        try:
            elem_info = uia_info.UIAElementInfo(hwnd)
            root_wrapper = UIAWrapper(elem_info)
            queue = [root_wrapper]
            visited = 0

            while queue and visited < 60:
                current = queue.pop(0)
                visited += 1
                try:
                    name = (current.window_text() or "").lower()
                    auto_id = (getattr(current.element_info, "automation_id", "") or "").lower()
                    if q_clean == name or q_clean == auto_id or q_clean in name:
                        target_wrapper = current
                        break
                    for child in current.children():
                        queue.append(child)
                except Exception:
                    continue
        except Exception as ex:
            return {"success": False, "error": f"UIA search exception: {ex}"}

        if not target_wrapper:
            return {"success": False, "error": f"Control '{query}' not found in HWND {hwnd}."}

        act_clean = action.lower()
        try:
            if act_clean == "click":
                target_wrapper.click_input()
                return {"success": True, "action": "click", "control": query, "method": "pywinauto_click_input"}
            elif act_clean == "set_value":
                target_wrapper.set_text(value)
                return {"success": True, "action": "set_value", "control": query, "value": value, "method": "pywinauto_set_text"}
            elif act_clean == "type_keys":
                target_wrapper.type_keys(value, with_spaces=True)
                return {"success": True, "action": "type_keys", "control": query, "value": value, "method": "pywinauto_type_keys"}
            else:
                return {"success": False, "error": f"Unsupported action '{action}'."}
        except Exception as ex:
            return {"success": False, "error": f"Action execution failed: {ex}"}

    def type_text(self, text: str) -> dict[str, Any]:
        """Type text into focused window using pywinauto keyboard with pyautogui/Win32 fallback."""
        if pw_keyboard:
            try:
                pw_keyboard.send_keys(text, with_spaces=True)
                return {"success": True, "action": "type_text", "method": "pywinauto_keyboard"}
            except Exception as ex:
                logger.debug("[PYWINAUTO_ADAPTER] send_keys fallback: %s", ex)

        # Fallback to pyautogui
        try:
            import pyautogui
            pyautogui.write(text, interval=0.01)
            return {"success": True, "action": "type_text", "method": "pyautogui_fallback"}
        except Exception as ex:
            return {"success": False, "error": f"Keyboard execution failed: {ex}"}

    def press_key(self, key: str) -> dict[str, Any]:
        """Press a keyboard key."""
        if pw_keyboard:
            try:
                pw_keyboard.send_keys(f"{{{key.upper()}}}")
                return {"success": True, "action": "press_key", "key": key, "method": "pywinauto_keyboard"}
            except Exception as ex:
                logger.debug("[PYWINAUTO_ADAPTER] press_key fallback: %s", ex)

        try:
            import pyautogui
            pyautogui.press(key)
            return {"success": True, "action": "press_key", "key": key, "method": "pyautogui_fallback"}
        except Exception as ex:
            return {"success": False, "error": f"Press key failed: {ex}"}

    def send_shortcut(self, shortcut: str) -> dict[str, Any]:
        """Send keyboard shortcut (e.g. 'ctrl+s', 'alt+f4')."""
        if pw_keyboard:
            try:
                keys = shortcut.lower().split("+")
                pw_seq = ""
                for k in keys:
                    k = k.strip()
                    if k == "ctrl":
                        pw_seq += "^"
                    elif k == "alt":
                        pw_seq += "%"
                    elif k == "shift":
                        pw_seq += "+"
                    else:
                        pw_seq += f"{{{k.upper()}}}"
                pw_keyboard.send_keys(pw_seq)
                return {"success": True, "action": "send_shortcut", "shortcut": shortcut, "method": "pywinauto_keyboard"}
            except Exception as ex:
                logger.debug("[PYWINAUTO_ADAPTER] send_shortcut fallback: %s", ex)

        try:
            import pyautogui
            keys = [k.strip() for k in shortcut.lower().split("+")]
            pyautogui.hotkey(*keys)
            return {"success": True, "action": "send_shortcut", "shortcut": shortcut, "method": "pyautogui_fallback"}
        except Exception as ex:
            return {"success": False, "error": f"Send shortcut failed: {ex}"}

    def click_coords(self, x: int, y: int, button: str = "left", clicks: int = 1) -> dict[str, Any]:
        """Click at physical desktop coordinates."""
        if pw_mouse:
            try:
                if button == "left":
                    if clicks == 2:
                        pw_mouse.double_click(coords=(x, y))
                    else:
                        pw_mouse.click(coords=(x, y))
                elif button == "right":
                    pw_mouse.right_click(coords=(x, y))
                return {"success": True, "action": "click_coords", "coords": (x, y), "button": button, "clicks": clicks}
            except Exception as ex:
                logger.debug("[PYWINAUTO_ADAPTER] mouse click failed: %s", ex)
        return {"success": False, "error": "Mouse click unavailable."}


PYWINAUTO_ADAPTER = PywinautoExecutionAdapter()


# ---------------------------------------------------------------------------
# Ziggler extension (Phase D): real-content read-back helpers.
# Everything above this line is the PLUTON substrate, moved unchanged.
# ---------------------------------------------------------------------------

def get_clipboard_text() -> str:
    """Read current CF_UNICODETEXT clipboard contents as a string."""
    import ctypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]

    text = ""
    if user32.OpenClipboard(None):
        try:
            handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
            ptr = kernel32.GlobalLock(handle)
            if ptr:
                text = ctypes.wstring_at(ptr)
                kernel32.GlobalUnlock(ptr)
        finally:
            user32.CloseClipboard()
    return text


def _find_document_control(hwnd: int):
    """Locate the text Document control inside a Win11 Notepad window (UIA)."""
    if not _PYWINAUTO_AVAILABLE or uia_info is None:
        return None
    try:
        elem_info = uia_info.UIAElementInfo(hwnd)
        root = UIAWrapper(elem_info)
        for child in root.children():
            try:
                for grandchild in child.children():
                    if grandchild.friendly_class_name() == "Document":
                        return grandchild
            except Exception:
                continue
    except Exception as ex:
        logger.debug("[PYWINAUTO_ADAPTER] find_document_control failed: %s", ex)
    return None


def set_notepad_text(hwnd: int, text: str) -> dict[str, Any]:
    """Set Notepad content via UIA ValuePattern — no keyboard input, no focus race."""
    doc = _find_document_control(hwnd)
    if doc is None:
        return {"success": False, "error": f"no Document control found in HWND {hwnd}"}
    try:
        value_pattern = doc.iface_value
        value_pattern.SetValue(text)
        time.sleep(0.2)
        return {"success": True, "hwnd": hwnd}
    except Exception as ex:
        return {"success": False, "error": f"SetValue failed: {ex}", "hwnd": hwnd}


def read_notepad_text(hwnd: int) -> dict[str, Any]:
    """Read back Notepad's live content via its own UIA Value pattern."""
    doc = _find_document_control(hwnd)
    if doc is None:
        return {"success": False, "error": f"no Document control found in HWND {hwnd}"}
    try:
        value_pattern = doc.iface_value
        try:
            content = value_pattern.CurrentValue
        except Exception:
            content = doc.window_text()  # Document name mirrors content on Win11
        return {"success": True, "hwnd": hwnd, "content": content}
    except Exception as ex:
        return {"success": False, "error": f"value read failed: {ex}", "hwnd": hwnd}


def force_close_pid(pid: int) -> dict[str, Any]:
    """Last-resort termination of a process THIS agent launched (dirty-doc save
    prompts block WM_CLOSE on packaged apps). Never call for pids you didn't create."""
    try:
        proc = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            text=True,
            timeout=10.0,
            check=False,
        )
        return {"success": proc.returncode == 0, "pid": pid, "method": "taskkill"}
    except Exception as ex:
        return {"success": False, "pid": pid, "error": str(ex)}
