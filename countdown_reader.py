# -*- coding: utf-8 -*-
"""
读取游戏左上角“剩余时间”倒计时（MM:SS）。

识别方式：Windows 自带 OCR（Windows.Media.Ocr，离线、免费、无需额外安装语言包以外的东西）。
为了抗跳字/误读，加了“锚定外推”：
  - 每次识别成功，记录 (识别到的剩余秒数, 当时的电脑时间)；
  - 需要时间时，用最近一次可信锚点按真实流逝秒数往下推算；
  - 新读数和推算值偏差 >3 秒且只出现一次，视为误读丢弃。
"""
import re
import time
import asyncio

import numpy as np
import cv2
import mss

_TIME_RE = re.compile(r"(\d{1,2})\s*[:：.]\s*(\d{2})")


# ---------------------------------------------------------------
#  截图 + 预处理
# ---------------------------------------------------------------
def grab(region):
    l, t, r, b = [int(v) for v in region]
    with mss.mss() as sct:
        shot = sct.grab({"left": l, "top": t, "width": r - l, "height": b - t})
    return cv2.cvtColor(np.asarray(shot), cv2.COLOR_BGRA2BGR)


def preprocess(bgr):
    """放大 + 灰度 + 二值化，白字黑底 -> 黑字白底，提升 OCR 准确率。"""
    h, w = bgr.shape[:2]
    scale = max(2, int(round(140 / max(h, 1))))    # 放大到约 140px 高（小字更准）
    big = cv2.resize(bgr, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # 让文字为黑色：若白色像素占少数，说明是白字，反色
    if np.mean(th) < 127:
        th = 255 - th
    th = cv2.copyMakeBorder(th, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    return cv2.cvtColor(th, cv2.COLOR_GRAY2BGR)


# ---------------------------------------------------------------
#  Windows OCR
# ---------------------------------------------------------------
_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.globalization import Language
        # 倒计时只有数字和冒号：优先英文引擎，避免中文引擎把“1”认成“飞”等汉字
        eng = None
        for tag in ("en-US", "en-GB", "en"):
            try:
                if OcrEngine.is_language_supported(Language(tag)):
                    eng = OcrEngine.try_create_from_language(Language(tag))
                    if eng is not None:
                        break
            except Exception:
                continue
        if eng is None:
            eng = OcrEngine.try_create_from_user_profile_languages()
        if eng is None:
            raise RuntimeError("Windows OCR 不可用（系统未安装任何 OCR 语言）")
        _engine = eng
    return _engine


async def _ocr_async(bgr):
    from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat, BitmapAlphaMode
    from winrt.windows.storage.streams import DataWriter
    bgra = cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA)
    h, w = bgra.shape[:2]
    writer = DataWriter()
    writer.write_bytes(bgra.tobytes())
    buf = writer.detach_buffer()
    bmp = SoftwareBitmap.create_copy_from_buffer(buf, BitmapPixelFormat.BGRA8, w, h, BitmapAlphaMode.PREMULTIPLIED)
    res = await _get_engine().recognize_async(bmp)
    return res.text or ""


def ocr_text(bgr):
    return asyncio.run(_ocr_async(bgr))


def parse_seconds(text):
    """从 OCR 文本里找 MM:SS，返回总秒数；找不到返回 None。"""
    t = (text or "")
    for a, b in (("O", "0"), ("o", "0"), ("D", "0"), ("ø", "0"), ("Ø", "0"), ("θ", "0"),
                 ("l", "1"), ("I", "1"), ("|", "1"), ("飞", "1"),
                 ("S", "5"), ("s", "5"), ("B", "8"), ("Z", "2"), ("z", "2")):
        t = t.replace(a, b)
    t = t.replace(" ", "")
    m = _TIME_RE.search(t)
    if not m:
        # 有时冒号丢失，读成 4 位数字，如 "1235"
        m2 = re.search(r"(\d{2})(\d{2})", t)
        if not m2:
            return None
        mm, ss = int(m2.group(1)), int(m2.group(2))
    else:
        mm, ss = int(m.group(1)), int(m.group(2))
    if ss >= 60 or mm > 59:
        return None
    return mm * 60 + ss


def read_countdown_once(region):
    """截一次图识别一次，返回 (秒数 or None, 原始文本)。"""
    img = preprocess(grab(region))
    txt = ocr_text(img)
    return parse_seconds(txt), txt


# ---------------------------------------------------------------
#  锚定外推，抗误读
# ---------------------------------------------------------------
class CountdownTracker:
    def __init__(self, region, max_seconds=30 * 60):
        self.region = region
        self.max_seconds = max_seconds
        self.anchor = None          # (剩余秒, 电脑时间)
        self.pending = None         # 一次偏差较大的读数，等待第二次印证
        self.last_text = ""

    def predicted(self, now=None):
        if self.anchor is None:
            return None
        now = time.time() if now is None else now
        sec, t0 = self.anchor
        return max(0.0, sec - (now - t0))

    def update(self):
        """读一次屏幕并更新锚点。返回当前可信剩余秒数(float) 或 None。"""
        try:
            sec, txt = read_countdown_once(self.region)
        except Exception as e:
            self.last_text = f"OCR异常: {e}"
            return self.predicted()
        self.last_text = txt
        now = time.time()
        if sec is None or sec > self.max_seconds:
            return self.predicted(now)

        pred = self.predicted(now)
        if pred is None or abs(sec - pred) <= 3:
            self.anchor = (sec + 0.5, now)       # 读到的是整秒，取中间值
            self.pending = None
        else:
            # 偏差大：需要连续两次一致才接受（换局/误读都可能）
            if self.pending is not None and abs((self.pending[0] - (now - self.pending[1])) - sec) <= 3:
                self.anchor = (sec + 0.5, now)
                self.pending = None
            else:
                self.pending = (sec, now)
        return self.predicted(now)

    def fresh(self, max_age=20):
        """锚点是否足够新（太久没读到说明不在对局画面里）。"""
        return self.anchor is not None and time.time() - self.anchor[1] <= max_age


def configured_regions(cfg):
    """兼容旧配置：COUNTDOWN_REGION 始终为战斗页，地图页另外保存。"""
    result = {}
    for name, field in (("战斗页", "COUNTDOWN_REGION"), ("地图页", "MAP_COUNTDOWN_REGION")):
        box = getattr(cfg, field, [])
        if len(box) == 4:
            l, t, r, b = box
            if r > l and b > t:
                result[name] = list(box)
    return result


class MultiCountdownTracker:
    """两页分别识别，但只保留一份时间锚点。不平均、不拼接两页的OCR。

    新页面读数需连续两次符合递减规律才采用。若两个有效页面冲突，优先与
    最近可信锚点连续的来源；不能判定时本轮不给时间。两页都未读到时最多
    外推8秒，超过后不再当成有效倒计时。所有访问受锁保护。
    """
    def __init__(self, regions, max_seconds=1800, cache_seconds=8):
        import threading
        self.regions = dict(regions)
        self.max_seconds = max_seconds
        self.cache_seconds = cache_seconds
        self.anchor = None
        self.source = None
        self.observations = {}
        self.last_text = ""
        self.status = "尚未读到"
        self.blocked = False
        self._lock = threading.RLock()

    def _predict(self, now):
        if self.anchor is None:
            return None
        sec, timestamp = self.anchor
        return max(0.0, sec - (now - timestamp))

    def predicted(self, now=None):
        with self._lock:
            if self.blocked or not self.fresh():
                return None
            return self._predict(time.time() if now is None else now)

    def fresh(self, max_age=20):
        with self._lock:
            return (not self.blocked and self.anchor is not None
                    and 0 <= time.time() - self.anchor[1] <= min(max_age, self.cache_seconds))

    def update(self):
        with self._lock:
            samples = []
            details = []
            for name, region in self.regions.items():
                start = time.time()
                try:
                    sec, txt = read_countdown_once(region)
                except Exception as exc:
                    sec, txt = None, f"读取异常：{exc}"
                observed_at = (start + time.time()) / 2
                details.append(f"{name}='{txt}'")
                if sec is None or not 0 <= sec <= self.max_seconds:
                    self.observations.pop(name, None)
                    continue
                previous = self.observations.get(name)
                count = 1
                if previous is not None:
                    old_sec, old_time, old_count = previous
                    elapsed = observed_at - old_time
                    if 0 <= elapsed <= 8 and abs(sec - (old_sec - elapsed)) <= 2:
                        count = old_count + 1 if elapsed >= 0.3 else old_count
                self.observations[name] = (sec, observed_at, count)
                if count >= 2:
                    samples.append((name, sec + 0.5, observed_at))
            self.last_text = "; ".join(details)
            now = time.time()
            pred = self._predict(now)
            normalized = [(name, sec - (now - ts), ts, sec) for name, sec, ts in samples]
            chosen = None
            self.blocked = False
            if normalized:
                values = [item[1] for item in normalized]
                conflict = max(values) - min(values) > 3
                matching = [item for item in normalized if pred is not None and abs(item[1] - pred) <= 3]
                if conflict:
                    if len(matching) == 1 and self.anchor and now - self.anchor[1] <= self.cache_seconds:
                        chosen = matching[0]
                    else:
                        self.blocked = True
                        self.status = "两页读数冲突，暂不采用"
                elif matching:
                    chosen = next((item for item in matching if item[0] == self.source), matching[0])
                else:
                    # 读数连续两次一致：允许切页及新一局重新锚定。
                    chosen = next((item for item in normalized if item[0] == self.source), normalized[0])
            if chosen:
                name, _, timestamp, sec = chosen
                self.anchor = (sec, timestamp)
                self.source = name
                self.status = f"已采用{name}"
            elif not self.blocked:
                self.status = (f"暂未读到，使用{self.source}短时缓存" if self.fresh()
                               else "两页均未取得可信时间（或等待连续读数确认）")
            return self.predicted(now)


def fmt(sec):
    sec = int(max(0, sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"
