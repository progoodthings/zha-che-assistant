# -*- coding: utf-8 -*-
"""
框选标定工具：
  1. 先全屏截一张当前画面（请提前在游戏里打开“大地图”，让撤离点灰色图标露出来）；
  2. 在弹出的截图上用鼠标左键拖拽，圈出撤离点图标（尽量只包住图标本体，别圈太大）；
  3. 可以连续圈多个撤离点；右键撤销最后一个；
  4. 按回车保存、按 Esc 放弃。结果自动写回 config.py 的 MONITOR_REGIONS。
"""
import re
import mss
import mss.tools
import numpy as np
import cv2

import config


def capture_full_screen(monitor_index=1):
    """截取指定显示器整屏，返回 (BGR图像, 显示器left, 显示器top)。"""
    with mss.mss() as sct:
        idx = max(1, min(monitor_index, len(sct.monitors) - 1))
        mon = sct.monitors[idx]
        shot = sct.grab(mon)
        img = np.asarray(shot)
        bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        return bgr, mon["left"], mon["top"]


def _on_mouse_factory(state):
    """生成鼠标回调，state 保存拖动起点与已选框。"""
    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            state["start"] = (x, y)
            state["drawing"] = True
        elif event == cv2.EVENT_MOUSEMOVE and state.get("drawing"):
            state["current"] = (x, y)
        elif event == cv2.EVENT_LBUTTONUP:
            state["drawing"] = False
            if state.get("start"):
                x0, y0 = state["start"]
                x1, y1 = x, y
                left, right = sorted((x0, x1))
                top, bottom = sorted((y0, y1))
                # 过滤误触产生的极小框
                if right - left >= 6 and bottom - top >= 6:
                    state["boxes"].append([int(left), int(top), int(right), int(bottom)])
            state["start"] = None
            state["current"] = None
    return on_mouse


def draw_view(base_img, state):
    """在截图上画出已选框和正在拖的框。"""
    view = base_img.copy()
    colors = [(0, 255, 255), (0, 255, 0), (255, 0, 0), (0, 0, 255)]
    for i, (l, t, r, b) in enumerate(state["boxes"]):
        color = colors[i % len(colors)]
        cv2.rectangle(view, (l, t), (r, b), color, 3)
        cv2.putText(view, f"#{i+1}", (l, max(20, t - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
    if state.get("drawing") and state.get("start") and state.get("current"):
        cv2.rectangle(view, state["start"], state["current"], (0, 255, 255), 2)
    return view


def save_to_config(abs_boxes):
    """把绝对坐标框写回 config.py 的 MONITOR_REGIONS。"""
    names = []
    default_names = ["撤离点1", "撤离点2", "撤离点3", "撤离点4"]
    for i in range(len(abs_boxes)):
        names.append(default_names[i] if i < len(default_names) else f"撤离点{i+1}")

    lines = ["MONITOR_REGIONS = {"]
    for name, box in zip(names, abs_boxes):
        lines.append(f'    "{name}": [{box[0]}, {box[1]}, {box[2]}, {box[3]}],')
    lines.append("}")
    new_block = "\n".join(lines)

    with open(config.__file__, "r", encoding="utf-8") as f:
        text = f.read()

    # 替换从 MONITOR_REGIONS = { 到与之配对的第一个 } 的整块
    pattern = re.compile(r"MONITOR_REGIONS\s*=\s*\{.*?\}", re.DOTALL)
    if pattern.search(text):
        text = pattern.sub(new_block, text, count=1)
    else:
        text += "\n\n" + new_block + "\n"

    with open(config.__file__, "w", encoding="utf-8") as f:
        f.write(text)
    return names


def main():
    print("=" * 56)
    print("撤离点框选标定")
    print("请确认游戏里【大地图已打开】，撤离点灰色图标可见。")
    print("3 秒后自动截屏，请切回游戏画面……")
    print("=" * 56)

    import time
    for i in (3, 2, 1):
        print(f"  {i} …")
        time.sleep(1)

    img, mon_left, mon_top = capture_full_screen(config.MONITOR_INDEX)
    h, w = img.shape[:2]
    print(f"已截屏（{w}x{h}）。在窗口中圈选撤离点图标。")
    print("左键拖拽=圈选（可圈多个） | 右键=撤销最后一个 | 回车=保存 | Esc=放弃")

    state = {"start": None, "current": None, "drawing": False, "boxes": []}

    win = "Select extraction points (Enter=save, Esc=cancel, RightClick=undo)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    # 超大屏时缩放到合适尺寸，保证能操作
    show_w = min(w, 1280)
    show_h = int(h * show_w / w)
    cv2.resizeWindow(win, show_w, show_h)
    cv2.setMouseCallback(win, _on_mouse_with_undo(state))

    saved = False
    while True:
        cv2.imshow(win, draw_view(img, state))
        key = cv2.waitKey(30) & 0xFF
        if key in (13,):  # 回车
            break
        if key == 27:     # Esc
            state["boxes"] = []
            break
        # 窗口被关闭
        if cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
            state["boxes"] = []
            break

    cv2.destroyAllWindows()

    if not state["boxes"]:
        print("未保存任何区域（已放弃）。")
        return

    # 截图窗口坐标 -> 整屏绝对坐标（处理多显示器偏移）
    abs_boxes = []
    for l, t, r, b in state["boxes"]:
        abs_boxes.append([l + mon_left, t + mon_top, r + mon_left, b + mon_top])

    names = save_to_config(abs_boxes)
    print("-" * 56)
    print(f"已保存 {len(names)} 个监控区域到 config.py：")
    for name, box in zip(names, abs_boxes):
        print(f"  {name}: {box}")
    print("现在可以运行【2.开始监控.bat】了。")


def _on_mouse_with_undo(state):
    base = _on_mouse_factory(state)
    def cb(event, x, y, flags, param):
        if event == cv2.EVENT_RBUTTONDOWN and state["boxes"]:
            state["boxes"].pop()
            return
        base(event, x, y, flags, param)
    return cb


if __name__ == "__main__":
    main()
