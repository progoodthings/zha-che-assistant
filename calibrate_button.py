# -*- coding: utf-8 -*-
"""
框选 WeGame 右下角橙色“启动”按钮：全屏截图上拖一个小框包住按钮，
保存按钮中心点到 config.START_BTN_CENTER，并当场自动定位一次确认点在按钮上。
"""
import re
import time

import cv2

import config
from calibrate import capture_full_screen, _on_mouse_with_undo, draw_view
import wegame_launcher as wl


def save_center(cx, cy):
    import sys
    from settings_store import save_calibration
    save_calibration('START_BTN_CENTER', [cx, cy])
    if getattr(sys, 'frozen', False):
        config.START_BTN_CENTER = [cx, cy]
        return

    with open(config.__file__, "r", encoding="utf-8") as f:
        text = f.read()
    new = f"START_BTN_CENTER = [{cx}, {cy}]"
    text2, n = re.subn(r"START_BTN_CENTER\s*=\s*\[[^\]]*\]", new, text, count=1)
    if n == 0:
        text2 = text + "\n" + new + "\n"
    with open(config.__file__, "w", encoding="utf-8") as f:
        f.write(text2)
    # 同步到运行时配置，便于立刻验证
    config.START_BTN_CENTER = [cx, cy]


def main():
    print("=" * 60)
    print("框选 WeGame 的橙色“启动”按钮")
    print("请确认：WeGame 已打开【三角洲行动】页面，右下角橙色启动按钮清楚可见。")
    print("3 秒后自动截屏，请切到 WeGame 窗口……")
    print("=" * 60)
    for i in (3, 2, 1):
        print(f"  {i} …"); time.sleep(1)

    img, ml, mt = capture_full_screen(config.MONITOR_INDEX)
    h, w = img.shape[:2]
    print("已截屏。左键拖一个框【只包住橙色启动按钮本体】 | 右键撤销 | 回车保存 | Esc 放弃")

    state = {"start": None, "current": None, "drawing": False, "boxes": []}
    win = "Select START button (Enter=save, Esc=cancel)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    show_w = min(w, 1500)
    cv2.resizeWindow(win, show_w, int(h * show_w / w))
    cv2.setMouseCallback(win, _on_mouse_with_undo(state))
    while True:
        cv2.imshow(win, draw_view(img, state))
        k = cv2.waitKey(30) & 0xFF
        if k == 13:
            break
        if k == 27 or cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
            state["boxes"] = []
            break
    cv2.destroyAllWindows()

    if not state["boxes"]:
        print("未保存。")
        return

    l, t, r, b = state["boxes"][-1]
    sub = img[t:b, l:r]
    pos, _ = wl._find_in_image(sub, (ml + l, mt + t), config, min_area_ratio=0.001)
    if pos is None:
        print("框内没识别到橙色启动按钮，本次未修改原来的校准位置。")
        print("请重新运行，框住整个橙色按钮，不要只框文字，也不要框进大块背景。")
        return
    cx, cy = pos
    save_center(cx, cy)
    print(f"校准成功：已保存启动按钮中心点 ({cx}, {cy})。")
    print("已用刚才框选的截图验证，不会点击按钮或启动游戏。")
    print("之后请保持 WeGame 窗口位置不变；大幅移动、换屏或改变缩放后需重新校准。")


if __name__ == "__main__":
    main()
