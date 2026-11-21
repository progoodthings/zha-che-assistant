# -*- coding: utf-8 -*-
"""
提醒模块：Server酱微信推送 + 本地响铃。
"""
import time
import winsound
import requests

SERVERCHAN_URL = "https://sctapi.ftqq.com/{key}.send"


def push_serverchan(key, title, content=""):
    """通过 Server酱 推送到微信。返回 (是否成功, 返回文本)。"""
    if not key:
        return False, "未配置 Server酱 Key"
    try:
        from settings_store import validate_target
        target = validate_target(key)
        url = target if '://' in target else SERVERCHAN_URL.format(key=target)
    except ValueError as exc:
        return False, str(exc)
    try:
        # ServerChan is reachable directly; the inherited proxy times out.
        with requests.Session() as session:
            session.trust_env = False
            resp = session.post(
                url,
                data={"title": title, "desp": content},
                timeout=(5, 15),
            )
        data = resp.json()
        # Server酱成功返回 code=0
        if data.get("code") == 0:
            return True, data.get("message", "推送成功")
        return False, f"接口返回：{data.get('message') or data}"
    except requests.exceptions.ReadTimeout:
        return False, "Server酱直连读取超时，是否送达未知；为避免重复通知，未自动重发"
    except Exception as e:
        # Request exception strings can contain the SendKey in the URL.
        return False, f"Server酱直连请求失败：{type(e).__name__}"


def play_alert():
    """本地响铃三声（不依赖任何外部文件）。"""
    try:
        for _ in range(3):
            winsound.Beep(880, 250)
            time.sleep(0.08)
    except Exception:
        # 部分环境不支持蜂鸣，退化为系统提示音
        try:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass


def notification_target(category):
    import config
    route = getattr(config, 'NOTIFICATION_ROUTES', {}).get(category, {})
    if not route.get('enabled', True):
        return None
    return route.get('target') or config.SERVERCHAN_KEY


def notify(category, title, content='', log=print):
    """One routing, delivery-status and logging path for every event type."""
    import ui_status
    target = notification_target(category)
    if target is None:
        ui_status.section('deliveries', **{category: 'disabled'})
        log(f'[记录] {title}（此类微信推送已关闭）')
        return True, '推送关闭'
    ui_status.section('deliveries', **{category: 'sending'})
    log(f'[推送] {title}')
    ok, message = push_serverchan(target, title, content)
    ui_status.section('deliveries', **{category: 'sent' if ok else 'failed'})
    log('推送成功' if ok else f'推送失败：{message}')
    return ok, message
