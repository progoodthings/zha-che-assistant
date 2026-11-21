# -*- coding: utf-8 -*-
"""
局内聊天发送 + 全局热键。

发送流程（模拟真人按键）：回车(打开聊天框) -> 输入文字 -> 回车(发送)
  - 回车用“扫描码”发送，兼容 DirectInput/虚幻引擎游戏；
  - 中文文字两种输入方式（config.CHAT_INPUT_METHOD）：
      "unicode"：逐字发送 Unicode 字符（默认）
      "paste"  ：写入剪贴板后 Ctrl+V 粘贴（若游戏不吃 unicode 输入就改用这个）
热键：后台线程轮询按键状态（全局有效，游戏在前台也能响应），不需要管理员权限。
"""
import time
import ctypes
import threading
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _INPUTunion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]


def _send(inputs):
    arr = (INPUT * len(inputs))(*inputs)
    n = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if n != len(inputs):
        raise OSError(f"SendInput 失败，错误码 {ctypes.get_last_error()}")


def _key_scan(scan, up=False, extended=False):
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0) | (0x0001 if extended else 0)
    return INPUT(INPUT_KEYBOARD, _INPUTunion(ki=KEYBDINPUT(0, scan, flags, 0, 0)))


def _key_vk(vk, up=False):
    return INPUT(INPUT_KEYBOARD, _INPUTunion(ki=KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, 0)))


def press_enter():
    _send([_key_scan(0x1C)]); time.sleep(0.04); _send([_key_scan(0x1C, up=True)])


def type_unicode(text, delay=0.012):
    for ch in text:
        code = ord(ch)
        down = INPUT(INPUT_KEYBOARD, _INPUTunion(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, 0)))
        up = INPUT(INPUT_KEYBOARD, _INPUTunion(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0)))
        _send([down, up])
        time.sleep(delay)


def _set_clipboard(text):
    import win32clipboard, win32con
    for _ in range(5):
        opened = False
        try:
            win32clipboard.OpenClipboard()
            opened = True
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            return
        except Exception:
            time.sleep(0.05)
        finally:
            if opened:
                win32clipboard.CloseClipboard()
    raise OSError("写入剪贴板失败")


def paste_text(text):
    _set_clipboard(text)
    time.sleep(0.05)
    VK_CONTROL, VK_V = 0x11, 0x56
    _send([_key_vk(VK_CONTROL)]); _send([_key_vk(VK_V)])
    time.sleep(0.04)
    _send([_key_vk(VK_V, True)]); _send([_key_vk(VK_CONTROL, True)])


def send_chat(text, method="paste", open_wait=0.35, before_send_wait=0.25):
    """回车打开聊天框 -> 输入 -> 回车发送。"""
    import config
    if not is_game_foreground(config):
        raise RuntimeError("游戏不在前台，保留消息等待再次按F8")
    press_enter()
    time.sleep(open_wait)
    if not is_game_foreground(config):
        raise RuntimeError("聊天期间已切出游戏，停止输入")
    if method == "paste":
        paste_text(text)
    else:
        type_unicode(text)
    time.sleep(before_send_wait)
    if not is_game_foreground(config):
        raise RuntimeError("发送前已切出游戏，停止发送")
    press_enter()


# ---------------------------------------------------------------
#  全局热键（轮询）
# ---------------------------------------------------------------
VK_NAMES = {f"F{i}": 0x6F + i for i in range(1, 13)}   # F1=0x70 ... F12=0x7B


class HotkeyWatcher(threading.Thread):
    def __init__(self, key_name, callback, log=print):
        super().__init__(daemon=True)
        self.vk = VK_NAMES.get(key_name.upper())
        if self.vk is None:
            raise ValueError(f"不支持的热键：{key_name}（请用 F1~F12）")
        self.key_name = key_name.upper()
        self.cb = callback
        self.log = log
        self.stop_flag = threading.Event()

    def run(self):
        # Queue WM_HOTKEY so short taps are not lost between polling intervals.
        if user32.RegisterHotKey(None, self.vk, 0x4000, self.vk):
            message = wintypes.MSG()
            try:
                while not self.stop_flag.is_set():
                    while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                        if message.message == 0x0312 and message.wParam == self.vk:
                            try:
                                self.cb()
                            except Exception as exc:
                                self.log(f"热键处理异常：{exc}")
                    self.stop_flag.wait(0.03)
            finally:
                user32.UnregisterHotKey(None, self.vk)
            return
        self.log(f"{self.key_name}系统热键已被占用，使用按键检测兼容方式。")
        was_down = False
        user32.GetAsyncKeyState(self.vk)  # discard old presses from before monitoring
        while not self.stop_flag.is_set():
            state = user32.GetAsyncKeyState(self.vk)
            down = bool(state & 0x8000)
            if (down and not was_down) or bool(state & 1):
                try:
                    self.cb()
                except Exception as e:
                    self.log(f"热键处理异常：{e}")
            was_down = down
            time.sleep(0.03)

    def stop(self):
        self.stop_flag.set()


def is_game_foreground(cfg):
    import win32gui, win32process, psutil
    try:
        hwnd = win32gui.GetForegroundWindow()
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        name = psutil.Process(pid).name().lower()
        return any(word.lower() in name for word in cfg.GAME_PROCESS_KEYWORDS)
    except (OSError, psutil.Error):
        return False
