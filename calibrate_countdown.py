# -*- coding: utf-8 -*-
"""
框选左上角“剩余时间”倒计时区域，并当场用 OCR 试读一次，确认能读出 MM:SS。
用法：对局中（能看到左上角倒计时）切出来，双击【5.框选倒计时.bat】。
"""
import re
import time

import cv2

import config
from calibrate import capture_full_screen, _on_mouse_with_undo, draw_view
import countdown_reader as cr


def save_region(box, page="battle"):
    if page not in ("battle", "map"):
        raise ValueError("page必须为battle或map")
    field = "MAP_COUNTDOWN_REGION" if page == "map" else "COUNTDOWN_REGION"
    import sys
    from settings_store import save_calibration
    save_calibration(field, list(box))
    if getattr(sys, 'frozen', False):
        setattr(config, field, list(box))
        return

    with open(config.__file__, "r", encoding="utf-8") as f:
        text = f.read()
    new = f"{field} = [{box[0]}, {box[1]}, {box[2]}, {box[3]}]"
    # 只匹配完整字段名：地图页不会覆盖战斗页。
    text, n = re.subn(r"(?m)^" + field + r"\s*=\s*\[[^\]]*\]", new, text, count=1)
    if n == 0:
        text += "\n" + new + "\n"
    with open(config.__file__, "w", encoding="utf-8") as f:
        f.write(text)
    setattr(config, field, list(box))


def main(page="battle"):
    name = "地图页" if page == "map" else "战斗页"
    print("=" * 60)
    print(f"框选游戏{name}的倒计时（剩余时间 MM:SS）")
    print(f"请确认：游戏在对局{name}中、倒计时清楚可见（无边框/窗口化）。")
    print("3 秒后自动截屏，请切回游戏画面……")
    print("=" * 60)
    for i in (3, 2, 1):
        print(f"  {i} …"); time.sleep(1)

    img, ml, mt = capture_full_screen(config.MONITOR_INDEX)
    h, w = img.shape[:2]
    # 战斗页保留原来的左上角放大窗口；地图页允许在整屏任意位置框选。
    scale = 1 if page == "map" else 2
    crop_w, crop_h = (w, h) if page == "map" else (w // 3, h // 3)
    view_img = cv2.resize(img[:crop_h, :crop_w], (crop_w * scale, crop_h * scale), interpolation=cv2.INTER_CUBIC)
    print("已截屏。地图页显示整屏，可框选任意位置。" if page == "map" else "已截屏。窗口显示屏幕左上角（放大2倍）。")
    print("左键拖框只包住倒计时数字（如 12:35） | 右键撤销 | 回车保存 | Esc 放弃")

    state = {"start": None, "current": None, "drawing": False, "boxes": []}
    win = "Select countdown (Enter=save, Esc=cancel)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, min(view_img.shape[1], 1400), min(view_img.shape[0], 800))
    cv2.setMouseCallback(win, _on_mouse_with_undo(state))
    while True:
        cv2.imshow(win, draw_view(view_img, state))
        k = cv2.waitKey(30) & 0xFF
        if k == 13:
            break
        if k == 27 or cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
            state["boxes"] = []
            break
    cv2.destroyAllWindows()

    if not state["boxes"]:
        print("未保存。"); return
    l, t, r, b = state["boxes"][-1]
    # 截图显示坐标 -> 原图物理坐标；边缘留4px且限制在显示器内。
    box = [max(0, l // scale - 4) + ml, max(0, t // scale - 4) + mt,
           min(w, r // scale + 4) + ml, min(h, b // scale + 4) + mt]

    # 先试读刚才截图，只有MM:SS有效才保存，避免错误框选覆盖既有位置。
    sub = img[box[1] - mt:box[3] - mt, box[0] - ml:box[2] - ml]
    try:
        txt = cr.ocr_text(cr.preprocess(sub))
        sec = cr.parse_seconds(txt)
    except Exception as exc:
        print(f"试读失败：{exc}；未修改原配置。")
        return
    if sec is not None and sec <= 1800:
        save_region(box, page)
        print(f"已保存{name}倒计时区域：{box}，不会覆盖另一页。")
        print(f"试读成功：识别为 {cr.fmt(sec)}（OCR 原文 '{txt}'）。请核对是否与截图时游戏显示一致。")
    else:
        print(f"试读失败：OCR 原文 '{txt}'。未修改原配置，请重新框选，只包住数字和冒号。")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--page", choices=["battle", "map"], default="battle")
    main(parser.parse_args().page)
