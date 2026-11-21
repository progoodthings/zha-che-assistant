"""Locate the two requested icons, read their own timers, and deduplicate events."""
from pathlib import Path
import time
import re
import cv2
import numpy as np
import mss
import countdown_reader as cr
from color_detector import green_ratio

ASSETS = Path(__file__).parent / 'assets'
POINTS = {
    '拉闸撤离点': ('switch', (1318, 710, 1360, 752), 300),
    '飞升撤离点': ('ascend', (1060, 1194, 1100, 1234), 720),
}


def edges(img):
    return cv2.Canny(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 40, 100)


def parse_exit_timer(text, maximum):
    # Four/five digit OCR strings can be a lost colon plus a misread digit.
    match = re.fullmatch(r'(\d{1,2})[:：](\d{2})', re.sub(r'\s+', '', text or ''))
    if not match:
        return None
    minutes, seconds = map(int, match.groups())
    total = minutes * 60 + seconds
    return total if seconds < 60 and 0 < total <= maximum else None


def read_exit_timer(timer, maximum):
    if timer is None or not timer.size:
        return None, '数字区域为空'
    mask = cv2.inRange(cv2.cvtColor(timer, cv2.COLOR_BGR2HSV), (35,60,60), (90,255,255))
    if cv2.countNonZero(mask) < 12:
        return None, '未检测到足够的绿色数字'
    blue, green, red = cv2.split(timer.astype(np.float32))
    # Preserve antialiased green strokes before enlargement; a binary mask loses
    # the small colon/digit strokes and prevents an otherwise open exit alert.
    signal = np.maximum(0, green - np.maximum(blue, red))
    signal = cv2.normalize(signal, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    texts, readings = [], []
    for factor in (5, 8, 10):
        big = cv2.resize(signal, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
        _, big = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        big = cv2.copyMakeBorder(255-big,20,20,20,20,cv2.BORDER_CONSTANT,value=255)
        text = cr.ocr_text(cv2.cvtColor(big, cv2.COLOR_GRAY2BGR))
        texts.append(text)
        value = parse_exit_timer(text, maximum)
        if value is not None:
            readings.append(value)
    detail = ' / '.join(repr(text) for text in texts)
    # Fail closed: do not choose a plausible result when valid readings conflict.
    if len(readings) >= 2 and len(set(readings)) == 1:
        return readings[0], detail
    return None, '读数未一致确认：' + detail


class ExtractionVision:
    def __init__(self, monitor_index=1, names=None):
        self.names = set(POINTS if names is None else names)
        self.monitor_index = monitor_index
        self.templates = {name: cv2.imread(str(ASSETS / (spec[0] + '.png')))
                          for name, spec in POINTS.items()}
        self.active_templates = {name: (cv2.imread(str(ASSETS / (spec[0] + '_active.png')))
                                       if (ASSETS / (spec[0] + '_active.png')).exists() else None)
                                 for name, spec in POINTS.items()}
        if any(img is None for img in self.templates.values()):
            raise RuntimeError('缺少撤离点参考图，请保留 assets 文件夹')

    def scan(self):
        with mss.mss() as sct:
            frame = cv2.cvtColor(np.asarray(sct.grab(sct.monitors[self.monitor_index])),
                                 cv2.COLOR_BGRA2BGR)
        return self.analyze(frame)

    def analyze(self, frame, read_ocr=True):
        # Reference screenshots are 2560x1440. Search locally after resolution scaling;
        # excluded exits and the legend are outside both search windows.
        h, w = frame.shape[:2]
        sx, sy = w / 2560, h / 1440
        found = {}
        for name, (_, box, maximum) in POINTS.items():
            if name not in self.names:
                continue
            x, y, r, b = box
            left, top = max(0, int((x-150)*sx)), max(0, int((y-180)*sy))
            right, bottom = min(w, int((r+150)*sx)), min(h, int((b+180)*sy))
            size = (max(1, round((r-x)*sx)), max(1, round((b-y)*sy)))
            roi = frame[top:bottom, left:right]
            if roi.shape[0] < size[1] or roi.shape[1] < size[0]:
                continue
            roi_edges = edges(roi)
            best = (-1, (0, 0))
            # An active icon includes a clock badge; its outline differs from gray.
            for reference in (self.templates[name], self.active_templates[name]):
                if reference is None:
                    continue
                template = cv2.resize(reference, size)
                scores = cv2.matchTemplate(roi_edges, edges(template), cv2.TM_CCOEFF_NORMED)
                _, candidate_score, _, candidate_pos = cv2.minMaxLoc(scores)
                if candidate_score > best[0]:
                    best = (candidate_score, candidate_pos)
            score, pos = best
            if score < 0.48:
                found[name] = {'active': False, 'seconds': None, 'score': score,
                               'position': None, 'timer_text': '未定位到目标图标'}
                continue
            px, py = left+pos[0], top+pos[1]
            tw, th = size
            icon = frame[py:py+th, px:px+tw]
            active = green_ratio(icon) >= 0.18
            seconds = None
            timer_text = ''
            if active and read_ocr:
                # Only green digits to the right of this icon; never use match time.
                timer = frame[max(0, py+int(8*sy)):min(h, py+th-int(3*sy)),
                              px+tw+int(10*sx):min(w, px+tw+int(85*sx))]
                seconds, timer_text = read_exit_timer(timer, maximum)
            found[name] = {'active': active, 'seconds': seconds, 'score': score,
                           'position': (px, py), 'timer_text': timer_text}
        return found


class ExtractionEvents:
    def __init__(self, confirm=2):
        self.confirm = confirm
        self.states = {}

    def update(self, observations, now=None):
        now = time.monotonic() if now is None else now
        messages = []
        for name, (_, _, duration) in POINTS.items():
            s = self.states.setdefault(name, {'streak': 0, 'last': -1e9,
                                             'anchor': None, 'candidate': None,
                                             'announced': False})
            obs = observations.get(name, {})
            if not obs.get('active'):
                s['streak'] = 0
                s['candidate'] = None
                s['announced'] = False
                continue
            s['streak'] += 1
            remaining = obs.get('seconds')
            if (type(remaining) not in (int, float) or not 0 < remaining <= duration):
                remaining = None
            previous = s['candidate']
            trusted = (remaining is not None and previous is not None
                       and 0.3 <= now-previous[1] <= 8
                       and remaining <= previous[0]
                       and abs(remaining - (previous[0] - (now-previous[1]))) <= 3)
            s['candidate'] = (remaining, now) if remaining is not None else None
            # Keep waiting if OCR lags behind the green icon; both are mandatory.
            opened = (s['streak'] >= self.confirm and trusted and not s['announced']
                      and now-s['last'] >= duration)
            if opened:
                s['last'] = now
                s['announced'] = True
                s['anchor'] = (remaining, now)
                detail = f'图标旁实际剩余倒计时：{cr.fmt(remaining)}。'
                messages.append((f'{name}已开启', detail))
            elif trusted and s['streak'] >= self.confirm and s['anchor'] is not None:
                anchor = s['anchor']
                predicted = None if anchor is None else anchor[0]-(now-anchor[1])
                if predicted is None or abs(remaining-predicted) >= 10:
                    messages.append((f'{name}倒计时更新', f'图标旁实际剩余倒计时：{cr.fmt(remaining)}。'))
                s['anchor'] = (remaining, now)
        return messages

    def status(self):
        now = time.monotonic()
        return '；'.join(f'{name} {cr.fmt(round(s["anchor"][0]-(now-s["anchor"][1])))}'
                        for name, s in self.states.items()
                        if s['streak'] >= self.confirm and s['candidate']
                        and s['anchor'] and s['candidate'][1] == s['anchor'][1]
                        and 0 <= now-s['anchor'][1] <= 8)
