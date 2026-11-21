# -*- coding: utf-8 -*-
"""
进程与 WeGame 自动化：
  - 检测三角洲 / WeGame 进程是否在运行
  - 激活 WeGame 窗口（必要时先拉起）
  - 在屏幕右下角定位橙色“启动”按钮并点击
"""
import os
import re
import time
import ctypes
import subprocess

import numpy as np
import cv2
import mss
import psutil


# ---------------------------------------------------------------
#  进程检测
# ---------------------------------------------------------------
def list_matching_processes(keywords):
    """返回所有进程名命中关键词(子串,不区分大小写)的进程名列表（去重小写）。"""
    kws = [k.lower() for k in keywords if k]
    hits = set()
    for p in psutil.process_iter(["name"]):
        try:
            name = (p.info["name"] or "").lower()
        except Exception:
            continue
        if any(k in name for k in kws):
            hits.add(name)
    return sorted(hits)


def is_process_running(keywords):
    return len(list_matching_processes(keywords)) > 0


def is_game_running(cfg):
    return is_process_running(cfg.GAME_PROCESS_KEYWORDS)


def is_wegame_running(cfg):
    return is_process_running(cfg.WEGAME_PROCESS_KEYWORDS)


def learn_game_process(cfg, extra_ignore=None):
    """
    游戏正在运行时调用：枚举当前所有可见窗口/进程，挑出最可能是三角洲的进程名，
    写回 config.GAME_PROCESS_KEYWORDS。这里用简单策略：取候选里“名字最像游戏”的。
    返回 (是否学到, 进程名)。
    """
    ignore = {
        "explorer.exe", "dwm.exe", "shellexperiencehost.exe", "searchhost.exe",
        "startmenuexperiencehost.exe", "textinputhost.exe", "applicationframehost.exe",
        "systemsettings.exe", "cmd.exe", "pwsh.exe", "powershell.exe",
        "python.exe", "pythonw.exe", "conhost.exe", "wegame.exe", "tgp_daemon.exe",
        "tenio.exe", "qq.exe", "wechat.exe", "chrome.exe", "msedge.exe",
    }
    if extra_ignore:
        ignore |= {x.lower() for x in extra_ignore}

    cand = []
    for p in psutil.process_iter(["name", "exe"]):
        try:
            name = (p.info["name"] or "").lower()
            exe = (p.info["exe"] or "").lower()
        except Exception:
            continue
        if not name or name in ignore:
            continue
        score = 0
        if "delta" in name or "三角洲" in name:
            score += 10
        if any(folder in exe for folder in ("delta", "三角洲")):
            score += 6
        # 必须和三角洲相关；启动器(launcher)不是游戏本体，排除
        if score == 0 or "launcher" in name:
            continue
        # 带游戏本体常见字样加权
        if any(x in name for x in ("shipping", "client", "cilent", "win64")):
            score += 3
        # WeGame/系统目录降权
        if "wegame" in exe or "\\windows\\" in exe or "system32" in exe:
            score -= 5
        if score > 0:
            cand.append((score, name))

    if not cand:
        return False, ""
    cand.sort(reverse=True)
    learned = cand[0][1]
    base = learned[:-4] if learned.endswith(".exe") else learned
    if base not in [k.lower().replace(".exe", "") for k in cfg.GAME_PROCESS_KEYWORDS]:
        cfg.GAME_PROCESS_KEYWORDS = [base] + list(cfg.GAME_PROCESS_KEYWORDS)
        _patch_config_list("GAME_PROCESS_KEYWORDS", cfg.GAME_PROCESS_KEYWORDS)
    return True, learned


def _patch_config_list(var_name, values):
    """把一个 list 常量写回 config.py。"""
    import config
    path = config.__file__
    import sys
    from settings_store import save_calibration
    save_calibration(var_name, list(values))
    if getattr(sys, 'frozen', False):
        setattr(config, var_name, list(values))
        return

    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    block = var_name + " = [\n" + "".join(f'    "{v}",\n' for v in values) + "]"
    pattern = re.compile(re.escape(var_name) + r"\s*=\s*\[.*?\]", re.DOTALL)
    if pattern.search(text):
        text = pattern.sub(block, text, count=1)
    else:
        text += "\n\n" + block + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ---------------------------------------------------------------
#  WeGame 窗口激活
# ---------------------------------------------------------------
def _all_windows():
    import pygetwindow as gw
    wins = []
    for w in gw.getAllWindows():
        try:
            if w.title and w.width > 200 and w.height > 150:
                wins.append(w)
        except Exception:
            continue
    return wins


def wegame_windows(cfg):
    """只读枚举窗口：依据标题/所属进程识别，保留最小化主窗口，排除隐藏辅助窗口。"""
    import win32gui
    import win32process
    kws = [k.lower() for k in cfg.WEGAME_WINDOW_KEYWORDS if k]
    rows = []
    def visit(hwnd, _):
        try:
            title = win32gui.GetWindowText(hwnd)
            if not title.strip() or title.strip().lower() in ("no_active_wnd", "dummy", "default ime", "msctfime ui"):
                return
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                name = psutil.Process(pid).name().lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                name = ""
            if not (any(k in title.lower() for k in kws) or name == "wegame.exe"):
                return
            visible = bool(win32gui.IsWindowVisible(hwnd))
            iconic = bool(win32gui.IsIconic(hwnd))
            # Tray-hidden main windows must remain discoverable; reject helpers.
            if not visible and title.strip().casefold() != "wegame":
                return
            # WeGame's browser-rendered main page can have an owner window.
            # Candidate content is verified before accepting it as the launcher.
            l, t, r, b = win32gui.GetWindowRect(hwnd)
            normal_rect = win32gui.GetWindowPlacement(hwnd)[4] if iconic else (l, t, r, b)
            # The 420x270 black helper is also titled WeGame; it is not the launcher.
            if not _main_window_size(normal_rect):
                return
            exact = title.strip().casefold() == "wegame"
            score = (100000000 if exact else 0) + (10000000 if name == "browser.exe" else 0)
            score += min(max(0, r - l) * max(0, b - t), 5000000)
            rows.append({"hwnd": hwnd, "title": title, "pid": pid, "process": name,
                         "visible": visible, "minimized": iconic, "rect": (l,t,r,b), "score": score})
        except Exception:
            return
    win32gui.EnumWindows(visit, None)
    return sorted(rows, key=lambda row: row["score"], reverse=True)


def _main_window_size(rect):
    l, t, r, b = rect
    return r-l >= 600 and b-t >= 400


def process_elevated(pid):
    """只查询进程TokenElevation；无法读取时返回None，不尝试提升权限。"""
    import win32api
    import win32security
    proc = token = None
    try:
        proc = win32api.OpenProcess(0x1000, False, pid)
        token = win32security.OpenProcessToken(proc, win32security.TOKEN_QUERY)
        return bool(win32security.GetTokenInformation(token, win32security.TokenElevation))
    except Exception:
        return None
    finally:
        if token is not None:
            token.Close()
        if proc is not None:
            proc.Close()


def permission_report(target_pid=None):
    """核对当前监控、WeGame主进程及目标窗口进程的权限。不包含账号或密钥。"""
    current = process_elevated(os.getpid())
    states = []
    seen = set()
    if target_pid:
        seen.add(target_pid)
        states.append({"role": "WeGame窗口进程", "elevated": process_elevated(target_pid)})
    for p in psutil.process_iter(["name"]):
        if (p.info["name"] or "").lower() == "wegame.exe" and p.pid not in seen:
            states.append({"role": "WeGame主进程", "elevated": process_elevated(p.pid)})
    return {"monitor_elevated": current, "wegame": states,
            "mismatch": current is False and any(s["elevated"] is True for s in states)}


def _activation_permission_error(target):
    report = permission_report(target["pid"])
    if report["mismatch"]:
        return ("权限不一致：WeGame以管理员权限运行，监控是普通权限，Windows会阻止窗口操作和点击。"
                "请关闭旧监控，右键【9.以管理员权限开始监控.bat】选择【以管理员身份运行】，"
                "并亲自确认Windows授权；或者之后将WeGame也以普通权限运行。未执行点击。")
    return ""


LAST_ACTIVATION_ERROR = ""


def _bring_to_foreground(hwnd):
    """还原最小化窗口并请求前台；API抛错不代表失败，以实际前台窗口为准。"""
    import win32gui
    import win32con
    import win32process
    import win32api
    errors = []
    try:
        if win32gui.IsIconic(hwnd) or not win32gui.IsWindowVisible(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
    except Exception as exc:
        errors.append(str(exc))
    for _ in range(5):
        if win32gui.GetForegroundWindow() == hwnd and not win32gui.IsIconic(hwnd):
            return True, ""
        time.sleep(0.1)

    # Windows可能限制后台进程抢前台；短暂关联输入线程后重试，始终解除关联。
    attached = []
    user32 = ctypes.windll.user32
    try:
        current = win32api.GetCurrentThreadId()
        foreground = win32gui.GetForegroundWindow()
        target_thread, _ = win32process.GetWindowThreadProcessId(hwnd)
        fg_thread = win32process.GetWindowThreadProcessId(foreground)[0] if foreground else current
        for thread in set((fg_thread, target_thread)):
            if thread != current and user32.AttachThreadInput(current, thread, True):
                attached.append((current, thread))
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
    except Exception as exc:
        errors.append(str(exc))
    finally:
        for current, thread in reversed(attached):
            user32.AttachThreadInput(current, thread, False)
    for _ in range(5):
        if win32gui.GetForegroundWindow() == hwnd and not win32gui.IsIconic(hwnd):
            return True, ""
        time.sleep(0.1)
    fg = win32gui.GetForegroundWindow()
    fg_title = win32gui.GetWindowText(fg) if fg else "无前台窗口"
    return False, f"Windows未将WeGame切到前台（当前前台：{fg_title}）。" + (
        "系统返回：" + "; ".join(errors) if errors else "可能被锁屏、权限或其他窗口阻止。")


def activate_wegame(cfg):
    """成功必须满足：找到可见主窗口、还原完成、确认为实际前台窗口。"""
    global LAST_ACTIVATION_ERROR
    LAST_ACTIVATION_ERROR = ""
    try:
        if not is_wegame_running(cfg):
            exe = getattr(cfg, "WEGAME_EXE_PATH", "") or _guess_wegame_path()
            if not exe or not os.path.isfile(exe):
                LAST_ACTIVATION_ERROR = "WeGame未运行，也未找到可执行文件。请保持WeGame已打开。"
                return False
            try:
                subprocess.Popen([exe], cwd=os.path.dirname(os.path.abspath(exe)))
            except Exception as exc:
                LAST_ACTIVATION_ERROR = f"WeGame启动请求失败：{exc}"
                return False
        targets = []
        for _ in range(10):
            targets = wegame_windows(cfg)
            if targets:
                break
            time.sleep(1)
        if not targets:
            # Reopen the running client's actual executable to restore its tray UI.
            exe = getattr(cfg, "WEGAME_EXE_PATH", "") or _guess_wegame_path()
            for process in psutil.process_iter(["name", "exe"]):
                if (process.info.get("name") or "").lower() == "wegame.exe" and process.info.get("exe"):
                    exe = process.info["exe"]
                    break
            if exe and os.path.isfile(exe):
                subprocess.Popen([exe], cwd=os.path.dirname(os.path.abspath(exe)))
                for _ in range(15):
                    time.sleep(1)
                    targets = wegame_windows(cfg)
                    if targets:
                        break
            if not targets:
                LAST_ACTIVATION_ERROR = "已尝试恢复WeGame主界面，但未找到可用窗口；请检查是否需要登录或更新。"
                return False
        errors = []
        for target in targets:
            permission_error = _activation_permission_error(target)
            if permission_error:
                errors.append(permission_error)
                continue
            ok, error = _bring_to_foreground(target["hwnd"])
            if not ok:
                errors.append(error)
                continue
            # Foreground is not proof of a launcher: reject blank shells and
            # try the next same-titled window instead of staying on the shell.
            for _ in range(3):
                time.sleep(0.5)
                if locate_start_button(cfg):
                    print(f"已核实WeGame启动页面：进程={target['process']}，窗口={target['hwnd']}，范围={target['rect']}")
                    LAST_ACTIVATION_ERROR = ""
                    return True
            errors.append(f"窗口{target['hwnd']}（{target['process']}）未通过页面内容核验：{LAST_BUTTON_ERROR}")
        LAST_ACTIVATION_ERROR = "；".join(errors) or "没有可用的WeGame启动页面"
        return False
    except Exception as exc:
        LAST_ACTIVATION_ERROR = f"WeGame窗口激活异常：{exc}"
        return False


def diagnose_wegame(cfg):
    """只查询，不激活窗口、不点击。"""
    import win32gui
    fg = win32gui.GetForegroundWindow()
    rows = wegame_windows(cfg)
    for row in rows:
        row["foreground"] = row["hwnd"] == fg
    target_pid = rows[0]["pid"] if rows else None
    return {"process_running": is_wegame_running(cfg), "foreground_title": win32gui.GetWindowText(fg),
            "candidate_windows": rows, "last_error": LAST_ACTIVATION_ERROR,
            "permissions": permission_report(target_pid)}



def click_game_tab(cfg):
    """点击 WeGame 左侧“三角洲行动”页签（可选，按屏幕比例点击）。"""
    with mss.mss() as sct:
        mon = sct.monitors[1]
        ml, mt, mw, mh = mon["left"], mon["top"], mon["width"], mon["height"]
    px, py = cfg.WEGAME_GAME_TAB_POINT
    _click(int(ml + mw * px), int(mt + mh * py))
    time.sleep(2.0)


def _guess_wegame_path():
    candidates = [
        r"C:\Program Files (x86)\Tencent\WeGame\wegame.exe",
        r"C:\Program Files\Tencent\WeGame\wegame.exe",
        r"D:\Program Files (x86)\Tencent\WeGame\wegame.exe",
        r"D:\Tencent\WeGame\wegame.exe",
        r"E:\Program Files (x86)\Tencent\WeGame\wegame.exe",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return ""


# ---------------------------------------------------------------
#  屏幕定位橙色“启动”按钮
# ---------------------------------------------------------------
def _ratio_box(box_ratio, monitor_index=1):
    """把屏幕比例矩形 (lx,ty,rx,by) 换算成主显示器绝对像素矩形。"""
    with mss.mss() as sct:
        mon = sct.monitors[monitor_index]
        ml, mt, mw, mh = mon["left"], mon["top"], mon["width"], mon["height"]
    lx, ty, rx, by = box_ratio
    return (int(ml + mw * lx), int(mt + mh * ty),
            int(ml + mw * rx), int(mt + mh * by))


def _virtual_box(cfg):
    """右下角搜索区（兼容旧配置）。"""
    return _ratio_box(cfg.BTN_SEARCH_BOX)


def _find_in_box(abs_box, cfg, min_area_ratio=None):
    """
    在给定绝对像素矩形内找橙色启动按钮，返回 (中心坐标, 外接矩形相对该框的坐标) 或 (None, None)。
    """
    left, top, right, bottom = abs_box
    w, h = right - left, bottom - top
    if w <= 20 or h <= 20:
        return None, None
    with mss.mss() as sct:
        shot = sct.grab({"left": left, "top": top, "width": w, "height": h})
    bgr = cv2.cvtColor(np.asarray(shot), cv2.COLOR_BGRA2BGR)

    return _find_in_image(bgr, (left, top), cfg, min_area_ratio)


def _find_in_image(bgr, origin, cfg, min_area_ratio=None):
    """只分析传入截图，不截屏、不点击；用于检测和校准共用同一算法。"""
    left, top = origin
    if bgr is None or bgr.size == 0:
        return None, None
    h, w = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hh, ss, vv = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    mask = ((hh >= cfg.BTN_H_LOW) & (hh <= cfg.BTN_H_HIGH)
            & (ss >= cfg.BTN_S_LOW) & (vv >= cfg.BTN_V_LOW)).astype(np.uint8) * 255

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    min_area = int(w * h * (min_area_ratio or cfg.BTN_MIN_AREA_RATIO))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best = None
    for c in cnts:
        x, y, cw, ch = cv2.boundingRect(c)
        area = cv2.contourArea(c)
        if area < min_area or cw < cfg.BTN_MIN_WIDTH:
            continue
        ratio = cw / max(ch, 1)
        if not (2.0 <= ratio <= 12.0):
            continue
        # 越靠右、越靠下、越宽越可能是启动按钮
        score = x + y * 0.5 + cw
        if best is None or score > best[0]:
            best = (score, x, y, cw, ch)
    if best is None:
        return None, None
    _, x, y, cw, ch = best
    return (left + x + cw // 2, top + y + ch // 2), (x, y, cw, ch)


LAST_BUTTON_ERROR = ""


def _start_text_boxes(bgr):
    """Read explicit start labels with Chinese OCR; return local word bounds."""
    import asyncio
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat, BitmapAlphaMode
    from winrt.windows.storage.streams import DataWriter
    engine = OcrEngine.try_create_from_language(Language("zh-Hans"))
    if engine is None:
        raise RuntimeError("缺少中文OCR，无法核实启动按钮文字")
    factor = min(2.0, 2400 / max(bgr.shape[:2]))
    image = cv2.resize(bgr, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
    async def recognize():
        h, w = image.shape[:2]
        writer = DataWriter()
        writer.write_bytes(cv2.cvtColor(image, cv2.COLOR_BGR2BGRA).tobytes())
        bmp = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.BGRA8,
                                                     w, h, BitmapAlphaMode.PREMULTIPLIED)
        result = await engine.recognize_async(bmp)
        boxes = []
        for line in result.lines:
            label = ''.join(word.text for word in line.words).replace(' ', '')
            # The lightning icon is often OCR'd as leading punctuation.
            label = re.sub(r'^[^\u4e00-\u9fffA-Za-z0-9]+', '', label)
            if label not in ('启动', '启动游戏'):
                continue
            rects = [word.bounding_rect for word in line.words]
            left = min(r.x for r in rects)
            top = min(r.y for r in rects)
            right = max(r.x+r.width for r in rects)
            bottom = max(r.y+r.height for r in rects)
            boxes.append((int(left/factor), int(top/factor), int(right/factor), int(bottom/factor)))
        return boxes
    return asyncio.run(recognize())


def _start_in_image(bgr, origin):
    """Require the actual start label plus an orange/yellow button background."""
    if _blank_launcher_image(bgr):
        return None
    for l, t, r, b in reversed(_start_text_boxes(bgr)):
        h, w = bgr.shape[:2]
        crop = bgr[max(0,t-12):min(h,b+12), max(0,l-20):min(w,r+20)]
        if not crop.size:
            continue
        mask = cv2.inRange(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV), (5, 85, 110), (38, 255, 255))
        if cv2.countNonZero(mask) / mask.size >= 0.20:
            return origin[0]+(l+r)//2, origin[1]+(t+b)//2
    return None


def _blank_launcher_image(bgr):
    if bgr is None or bgr.size == 0:
        return True
    h, w = bgr.shape[:2]
    # Ignore the outer border and rounded corners of an otherwise black client.
    inner = bgr[h//10:9*h//10, w//10:9*w//10]
    return not inner.size or float(inner.std()) < 5


def locate_start_button(cfg):
    """Search the foreground WeGame window, independent of old desktop coordinates."""
    global LAST_BUTTON_ERROR
    import win32gui
    LAST_BUTTON_ERROR = ""
    foreground = win32gui.GetForegroundWindow()
    targets = [row for row in wegame_windows(cfg) if row['hwnd'] == foreground]
    if not targets:
        LAST_BUTTON_ERROR = "前台不是可用的WeGame主窗口，未识别/点击"
        return None
    l, t, r, b = targets[0]['rect']
    # Only the bottom half of this window, never desktop advertisements or other apps.
    t = t + (b-t)//2
    try:
        with mss.mss() as sct:
            desktop = sct.monitors[0]
            l, t = max(l, desktop['left']), max(t, desktop['top'])
            r = min(r, desktop['left']+desktop['width'])
            b = min(b, desktop['top']+desktop['height'])
            if r <= l or b <= t:
                LAST_BUTTON_ERROR = "WeGame窗口位于可见桌面之外"
                return None
            shot = sct.grab({'left': l, 'top': t, 'width': r-l, 'height': b-t})
        image = cv2.cvtColor(np.asarray(shot), cv2.COLOR_BGRA2BGR)
        if _blank_launcher_image(image):
            LAST_BUTTON_ERROR = "WeGame主界面仍为黑屏/尚未加载，继续等待；未点击"
            return None
        pos = _start_in_image(image, (l,t))
        if pos is None:
            LAST_BUTTON_ERROR = "WeGame窗口下半部未找到带橙黄色背景的“启动/启动游戏”文字；请确认在三角洲页面且未在更新或运行中"
        return pos
    except Exception as exc:
        LAST_BUTTON_ERROR = f"启动按钮识别失败：{type(exc).__name__}：{exc}"
        return None


# ---------------------------------------------------------------
#  鼠标点击（ctypes，无需额外依赖）
# ---------------------------------------------------------------
def _click(x, y):
    """检查权限、光标位置及SendInput返回值；发送输入不等于游戏已经启动。"""
    import win32gui
    import win32process
    from ctypes import wintypes
    foreground = win32gui.GetForegroundWindow()
    if not foreground:
        raise RuntimeError("没有前台窗口，未点击")
    import config
    if not any(row['hwnd'] == foreground for row in wegame_windows(config)):
        raise RuntimeError("点击前已切出WeGame主窗口，已取消点击")
    _, pid = win32process.GetWindowThreadProcessId(foreground)
    if process_elevated(os.getpid()) is False and process_elevated(pid) is True:
        raise PermissionError("前台窗口是管理员权限，监控是普通权限。未执行点击，请以管理员身份运行监控。")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    if not user32.SetCursorPos(int(x), int(y)):
        raise OSError(ctypes.get_last_error(), "SetCursorPos失败，未点击")
    time.sleep(0.15)
    if win32gui.GetForegroundWindow() != foreground:
        raise RuntimeError("点击前前台窗口发生变化，已取消点击")
    actual = win32gui.GetCursorPos()
    if abs(actual[0] - x) > 3 or abs(actual[1] - y) > 3:
        raise RuntimeError(f"鼠标未移动到目标点：实际{actual}，目标{(x,y)}，未点击")
    class MouseInput(ctypes.Structure):
        _fields_ = [("dx",wintypes.LONG),("dy",wintypes.LONG),("mouseData",wintypes.DWORD),
                    ("dwFlags",wintypes.DWORD),("time",wintypes.DWORD),("dwExtraInfo",ctypes.c_size_t)]
    class InputUnion(ctypes.Union):
        _fields_ = [("mi",MouseInput)]
    class Input(ctypes.Structure):
        _fields_ = [("type",wintypes.DWORD),("u",InputUnion)]
    user32.SendInput.argtypes = [wintypes.UINT,ctypes.POINTER(Input),ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    inputs = (Input * 2)(Input(0,InputUnion(mi=MouseInput(0,0,0,0x0002,0,0))),
                         Input(0,InputUnion(mi=MouseInput(0,0,0,0x0004,0,0))))
    count = user32.SendInput(2,inputs,ctypes.sizeof(Input))
    if count != 2:
        error = ctypes.get_last_error()
        if count == 1:
            # 第一条按下已接受时，尽力补发松开，防止鼠标保持按下。
            release = (Input * 1)(inputs[1])
            user32.SendInput(1,release,ctypes.sizeof(Input))
        raise OSError(error,f"Windows仅接受{count}/2条点击输入，可能受权限限制")
    return True


def click_start_button(cfg):
    """定位并点击启动按钮，返回是否成功点击。"""
    pos = locate_start_button(cfg)
    if pos is None:
        return False
    _click(*pos)
    return True


def debug_locate(cfg):
    """只定位不点击，返回 (坐标 or None, 搜索框绝对矩形)，供 --find-btn 用。"""
    return locate_start_button(cfg), _virtual_box(cfg)
