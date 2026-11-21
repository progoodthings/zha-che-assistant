# -*- coding: utf-8 -*-
"""
颜色检测模块：截取指定矩形区域，统计其中“绿色像素”占比。
"""
import numpy as np
import cv2
import mss


def grab_region(region, monitor_index=1):
    """截取屏幕指定区域。region=[left, top, right, bottom]，返回 BGR ndarray。"""
    left, top, right, bottom = [int(v) for v in region]
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        raise ValueError(f"区域坐标非法（宽或高<=0）：{region}")

    # mss 显示器编号：1=主屏整体；多显示器时序号顺延
    mon = {"left": left, "top": top, "width": width, "height": height}
    with mss.mss() as sct:
        # monitors[0] 是所有屏幕合并，[1] 是第一块屏幕
        idx = max(1, min(monitor_index, len(sct.monitors) - 1))
        base = sct.monitors[idx]
        # 若区域位于该显示器坐标系外，mss 仍按虚拟桌面坐标抓取；这里直接用绝对坐标抓
        shot = sct.grab(mon)
    img = np.asarray(shot)            # BGRA
    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


def green_ratio(bgr_img, h_low=35, h_high=90, s_low=60, v_low=60):
    """返回图中符合绿色条件的像素占比（0~1）。"""
    if bgr_img is None or bgr_img.size == 0:
        return 0.0
    hsv = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    mask = (h >= h_low) & (h <= h_high) & (s >= s_low) & (v >= v_low)
    return float(np.count_nonzero(mask)) / float(mask.size)


def analyze_region(region, cfg, save_path=None):
    """抓一块区域并计算绿色占比。save_path 不为空时把该区域截图存盘，便于核对。"""
    img = grab_region(region, getattr(cfg, "MONITOR_INDEX", 1))
    ratio = green_ratio(
        img,
        h_low=cfg.H_LOW, h_high=cfg.H_HIGH,
        s_low=cfg.S_LOW, v_low=cfg.V_LOW,
    )
    if save_path:
        cv2.imwrite(save_path, img)
    return ratio
