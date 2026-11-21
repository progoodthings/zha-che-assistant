# -*- coding: utf-8 -*-
"""
飞升者行动·第二步联动：
  听到滴滴（后台线程）-> 换算成“第一声滴”时刻的游戏剩余时间 -> 校验处于最后15分钟
  -> 微信推送 start / end(=start-4:30) -> 等待用户按 F8 -> 局内聊天框发送文案
"""
import time
import threading

import config
import countdown_reader as cr
import chat_sender as cs
from notifier import notify, play_alert
import ui_status


class AscendController:
    def __init__(self, log=print):
        self.log = log
        regions = cr.configured_regions(config)
        self.tracker = cr.MultiCountdownTracker(regions) if regions else None
        self.pending_msg = None        # (文案, 生成时间)
        self.lock = threading.Lock()
        self.listener = None
        self.hotkey = None
        self.last_ocr = 0.0

    # ---------- 生命周期 ----------
    def start(self):
        if not config.ASCEND_ALERT:
            return
        if not self.tracker:
            self.log("提示：还没框选倒计时。战斗页用【5.框选倒计时.bat】，地图页用【7.框选地图页倒计时.bat】。")
        else:
            self.log("倒计时读取区域：" + "、".join(self.tracker.regions) + "；每次仅采用一处有效时间。")
        from beep_detector import LoopbackListener
        self.listener = LoopbackListener(
            on_alarm=self.on_alarm,
            device_keyword=config.AUDIO_DEVICE_KEYWORD,
            score_threshold=config.BEEP_SCORE_THRESHOLD,
            confirm_count=config.BEEP_CONFIRM_COUNT,
            period_tol=config.BEEP_PERIOD_TOL,
            rearm_sec=config.BEEP_REARM_SECONDS,
            log=self.log,
        )
        self.listener.start()
        if getattr(config, 'CHAT_ENABLED', True):
            self.hotkey = cs.HotkeyWatcher(config.SEND_HOTKEY, self.on_hotkey, log=self.log)
            self.hotkey.start()
        self.log(f"飞升第二步监听已开启：听到滴滴声即推送；按 {config.SEND_HOTKEY} 发送到局内聊天框。")

    def tick(self):
        """主循环每轮调用：刷新倒计时锚点（每 2 秒读一次即可）。"""
        if self.tracker and time.time() - self.last_ocr >= 2.0:
            self.last_ocr = time.time()
            self.tracker.update()

    # ---------- 事件 ----------
    def on_alarm(self, first_beep_wall):
        """first_beep_wall：第一声滴对应的电脑时间。"""
        if not cs.is_game_foreground(config):
            return
        now = time.time()
        with self.lock:
            self.pending_msg = None
        ui_status.publish(audio={})
        remain = None
        if self.tracker:
            self.tracker.update()
            if self.tracker.fresh(max_age=30):
                remain = self.tracker.predicted(first_beep_wall)

        if remain is None:
            self.log("听到飞升第二步滴滴声，但战斗页和地图页均未取得可信倒计时。")
            self.push( config.ASCEND_PUSH_TITLE + "（未读到倒计时）",
                            "检测到疑似飞升第二步滴滴声，但两页倒计时均不可用或读数冲突。\n\n"
                            "未使用现实时间代替游戏时间，也不会生成局内聊天文案；请自行核对任务状态。")
            return

        if remain > config.ALERT_WINDOW_SECONDS + 5:
            self.log(f"听到疑似滴滴声，但此时剩余 {cr.fmt(remain)}，不在最后15分钟内，忽略。")
            return

        start_s = int(remain)                          # 去尾取整到秒，和游戏显示一致
        end_s = max(0, start_s - config.HOLD_SECONDS)
        start_txt, end_txt = cr.fmt(start_s), cr.fmt(end_s)
        msg = config.CHAT_TEMPLATE.format(start=start_txt, end=end_txt)
        with self.lock:
            self.pending_msg = (msg, now)
        ui_status.publish(audio={'message': msg, 'detected_at': now,
                                 'expires_at': now+config.HOTKEY_VALID_SECONDS, 'sent': False})
        delay = now - first_beep_wall
        self.log(f">>> 飞升第二步开始！剩余 {start_txt}，驻守至剩余 {end_txt} 完成（识别耗时 {delay:.0f}s）")
        self.push(
                        f"{config.ASCEND_PUSH_TITLE} 剩余{start_txt}",
                        f"检测到飞升者行动**第二步滴滴声**（对方已上传信息，开始驻守）。\n\n"
                        f"- 开始时游戏剩余：**{start_txt}**\n"
                        f"- 驻守 4分30秒，完成于剩余：**{end_txt}**\n\n"
                        f"按 **{config.SEND_HOTKEY}** 可把这条信息发到局内队伍聊天：\n\n> {msg}")
        if config.PLAY_SOUND:
            play_alert()

    def on_hotkey(self):
        if not getattr(config, 'CHAT_ENABLED', True):
            return
        if not cs.is_game_foreground(config):
            self.log("F8：请先切回三角洲游戏，消息仍保留。")
            return
        with self.lock:
            item = self.pending_msg
        if not item:
            self.log(f"按下 {config.SEND_HOTKEY}：当前没有待发送的飞升信息。")
            return
        msg, t0 = item
        if time.time() - t0 > config.HOTKEY_VALID_SECONDS:
            self.log(f"按下 {config.SEND_HOTKEY}：信息已超过 {config.HOTKEY_VALID_SECONDS}s，已过期不发送。")
            with self.lock:
                self.pending_msg = None
            return
        time.sleep(0.15)        # 等热键松开，避免干扰
        try:
            cs.send_chat(msg, method=config.CHAT_INPUT_METHOD)
            self.log(f"已发送到局内聊天：{msg}")
            ui_status.section('audio', sent=True)
            with self.lock:
                if self.pending_msg == item:
                    self.pending_msg = None
        except Exception as e:
            self.log(f"局内聊天发送失败：{e}")

    def push(self, title, content):
        return notify('audio', title, content, log=self.log)

    def stop(self):
        for th in (self.listener, self.hotkey):
            if th:
                th.stop()
