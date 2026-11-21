# -*- coding: utf-8 -*-
"""
飞升者行动·第二步“滴滴”警报声检测。

特征（从 B 站素材 BV1VJ3F6SE3T 实测，存于 beep_template.json）：
  - 谐波音：一组等间距（约 210Hz）的频率横线，1039/1453/2078Hz 等最强；
  - 每声约 1.3 秒，每 2.8 秒响一次，非常规律。

检测思路：
  1) 每 50ms 计算一次“谐波梳得分”= 各模板谐波处峰值 / 邻近背景 的对数均值；
  2) 得分高于阈值的连续片段，时长在 0.5~2.2 秒之间，视为“一声滴”；
  3) 最近连续 BEEP_CONFIRM_COUNT 声的间隔都 ≈ 2.8 秒(±容差)，确认警报开始；
  4) 返回“第一声滴”的发生时刻，供换算游戏倒计时。
"""
import json
import os
import time
import threading
from collections import deque

import numpy as np

SR = 16000
WIN = 2048
HOP = 800            # 50ms
# 滴声间隔允许范围（秒）：素材 2.8s、真实对局约 2.0s
PERIOD_MIN, PERIOD_MAX = 1.5, 3.5
# 读不到声卡原生采样率时的备用值
AUDIO_SAMPLE_RATE_FALLBACK = 48000

_HERE = os.path.dirname(os.path.abspath(__file__))


def load_template(path=None):
    path = path or os.path.join(_HERE, "beep_template.json")
    with open(path, "r", encoding="utf-8") as f:
        tpl = json.load(f)
    hs = [h for h, g in zip(tpl["harmonics_hz"], tpl["harmonics_gain_db"])
          if g >= 12 and h < SR / 2 - 200]
    return {
        "period": float(tpl["period_sec"]),
        "on_dur": float(tpl["on_duration_sec"]),
        "harmonics": hs,
    }


class BeepDetector:
    """流式检测器：不断 feed(音频块)，检测到警报时 on_alarm 被调用。"""

    def __init__(self, score_threshold=0.9, confirm_count=3, period_tol=0.35, template=None,
                 rearm_sec=360):
        self.tpl = template or load_template()
        self.thr = score_threshold
        self.confirm = confirm_count
        self.tol = period_tol
        # 一次触发后锁定多久不再触发：驻守 4分30秒 + 火箭开舱/发射阶段也会滴，默认 6 分钟
        self.rearm_sec = rearm_sec
        self.last_alarm_t = -1e9
        self.window = np.hanning(WIN).astype(np.float32)
        self.freqs = np.fft.rfftfreq(WIN, 1 / SR)
        # 预计算每个谐波的“中心”和“背景”频点
        self.bins = []
        for h in self.tpl["harmonics"]:
            c = np.where(np.abs(self.freqs - h) <= 14)[0]
            bg = np.where((np.abs(self.freqs - h) > 30) & (np.abs(self.freqs - h) <= 90))[0]
            if len(c) and len(bg):
                self.bins.append((c, bg))
        self.buf = np.zeros(0, dtype=np.float32)
        self.t_samples = 0               # 已处理样本数（流时间）
        self.on = False
        self.on_start = 0.0
        self.beeps = deque(maxlen=12)    # 最近每声滴的起点(流时间秒)
        self.last_score = 0.0
        self.alarm_active = False
        self.period_seen = None

    # ---------------- 打分 ----------------
    def score_frame(self, frame):
        sp = np.abs(np.fft.rfft(frame * self.window)) + 1e-9
        vals = []
        for c, bg in self.bins:
            vals.append(np.log(sp[c].max() / np.median(sp[bg])))
        vals.sort()
        # 去掉最高的 2 个（防偶发单频噪声）后取均值，更稳
        core = vals[:-2] if len(vals) > 4 else vals
        return float(np.mean(core))

    # ---------------- 流式输入 ----------------
    def feed(self, samples):
        """samples: 16kHz 单声道 float32。返回本次新确认的警报列表 [(第一声起点流时间)]。"""
        alarms = []
        self.buf = np.concatenate([self.buf, samples.astype(np.float32)])
        while len(self.buf) >= WIN:
            frame = self.buf[:WIN]
            self.buf = self.buf[HOP:]
            t = self.t_samples / SR
            self.t_samples += HOP
            s = self.score_frame(frame)
            self.last_score = s
            if s >= self.thr and not self.on:
                self.on = True
                self.on_start = t
            elif s < self.thr * 0.7 and self.on:
                self.on = False
                dur = t - self.on_start
                if 0.5 <= dur <= 2.2:
                    self.beeps.append(self.on_start)
                    a = self._check_periodic()
                    if a is not None:
                        alarms.append(a)
            # 长时间没有新滴声：认为警报结束，允许下一次触发
            if self.alarm_active and self.beeps and t - self.beeps[-1] > PERIOD_MAX * 3:
                self.alarm_active = False
        return alarms

    def _check_periodic(self):
        """
        不写死周期：素材视频里约 2.8 秒一声，真实对局实测约 2.0 秒一声。
        只要最近 confirm 声的间隔彼此一致（相对中位数 ±tol 秒，允许漏一声≈2倍），
        且中位间隔落在 [PERIOD_MIN, PERIOD_MAX] 内，就确认警报。
        """
        if self.alarm_active or len(self.beeps) < self.confirm:
            return None
        last = list(self.beeps)[-self.confirm:]
        if last[0] - self.last_alarm_t < self.rearm_sec:
            return None
        gaps = np.diff(last)
        base = float(np.min(gaps))
        if not (PERIOD_MIN <= base <= PERIOD_MAX):
            return None
        ok = all(abs(g - base) <= self.tol or abs(g - 2 * base) <= self.tol * 1.5 for g in gaps)
        if ok:
            self.alarm_active = True
            self.period_seen = base
            self.last_alarm_t = last[0]
            return last[0]
        return None

    def stream_time(self):
        return self.t_samples / SR


# =====================================================================
#  后台线程：从“系统正在播放的声音”(WASAPI 回环)实时采集并检测
# =====================================================================
class LoopbackListener(threading.Thread):
    def __init__(self, on_alarm, device_keyword="", score_threshold=0.9,
                 confirm_count=3, period_tol=0.35, rearm_sec=360, log=print):
        super().__init__(daemon=True)
        self.on_alarm = on_alarm
        self.device_keyword = device_keyword
        self.det = BeepDetector(score_threshold, confirm_count, period_tol, rearm_sec=rearm_sec)
        self.log = log
        self.stop_flag = threading.Event()
        self.error = None
        self.wall_at_stream0 = None    # 流时间 0 对应的电脑时间

    def _pick_speaker(self):
        import soundcard as sc
        if self.device_keyword:
            for spk in sc.all_speakers():
                if self.device_keyword.lower() in spk.name.lower():
                    return spk
        return sc.default_speaker()

    @staticmethod
    def native_rate(mic):
        """
        读取设备在 Windows 混音器里的原生采样率。
        必须按原生采样率录音：若用别的采样率录，部分声卡（如本机耳机 44100Hz）会把音高整体拉偏，
        谐波对不上模板就识别不出来。读取失败时依次试 48000/44100 并取能正常工作的。
        """
        try:
            from soundcard import mediafoundation as mf
            ptr = mic._audio_client()
            try:
                pp = mf._ffi.new("WAVEFORMATEXTENSIBLE**")
                hr = ptr[0][0].lpVtbl.GetMixFormat(ptr[0], pp)
                if hr == 0:
                    rate = int(pp[0][0].Format.nSamplesPerSec)
                    mf._ole32.CoTaskMemFree(pp[0])
                    return rate
            finally:
                mf._com.release(ptr)
        except Exception:
            pass
        return None

    def run(self):
        try:
            import soundcard as sc
            import warnings
            from scipy.signal import resample_poly
            warnings.filterwarnings("ignore", category=Warning, module="soundcard")
            spk = self._pick_speaker()
            mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
            rate = self.native_rate(mic) or AUDIO_SAMPLE_RATE_FALLBACK
            from math import gcd
            g = gcd(rate, SR)
            up, down = SR // g, rate // g
            self.log(f"声音监听设备：{spk.name}（{rate}Hz）")
            with mic.recorder(samplerate=rate, channels=2) as rec:
                self.wall_at_stream0 = time.time()
                while not self.stop_flag.is_set():
                    data = rec.record(numframes=rate // 2)        # 0.5 秒
                    if data is None or len(data) == 0:
                        continue
                    mono = data.mean(axis=1).astype(np.float32)
                    mono16 = resample_poly(mono, up, down).astype(np.float32)
                    for first_beep_t in self.det.feed(mono16):
                        wall = self.wall_at_stream0 + first_beep_t
                        try:
                            self.on_alarm(wall)
                        except Exception as e:
                            self.log(f"警报回调异常：{e}")
        except Exception as e:
            self.error = e
            self.log(f"声音监听启动失败：{e}")

    def stop(self):
        self.stop_flag.set()
