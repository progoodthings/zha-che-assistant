# -*- coding: utf-8 -*-
"""
撤离点监控 + 强退自动重启 主程序。

用法：
  python monitor.py              开始监控（撤离点变绿推送；游戏退出14分钟后自动从WeGame重启）
  python monitor.py --test       只发一条测试推送，验证 Server酱
  python monitor.py --once       抓一次并打印各撤离点区域绿色占比
  python monitor.py --find-btn   只定位 WeGame“启动”按钮并打印坐标（不点击，用于校准）
  python monitor.py --learn-game 游戏运行时执行：自动识别游戏进程名并写回 config
  python monitor.py --restart-now 立即演练一次“激活WeGame并点启动”（不等14分钟，慎用）
  python monitor.py --read-countdown  连续读10次左上角倒计时，检查OCR
  python monitor.py --test-chat       5秒后在游戏里发一条测试聊天
  python monitor.py --listen-test     只开声音监听3分钟，测试能否听到滴滴声
"""
import sys
import time
import datetime as dt
import threading
import _thread

STOP_REQUESTED = threading.Event()

def request_stop():
    STOP_REQUESTED.set()
    _thread.interrupt_main()


import config
from notifier import notify, push_serverchan, play_alert
import wegame_launcher as wl
import ui_status


def now_str():
    return dt.datetime.now().strftime("%H:%M:%S")


def push(title, content, category="restart"):
    return notify(category, title, content,
                  log=lambda message: print(f"[{now_str()}] {message}"))[0]



def cmd_test():
    print("正在发送测试推送……")
    ok, msg = push_serverchan(
        config.SERVERCHAN_KEY, "撤离点监控已就绪",
        f"如果在微信收到这条消息，说明推送配置正常。\n\n时间：{now_str()}",
    )
    print(("成功：" if ok else "失败：") + str(msg))
    return ok


def cmd_once():
    from extraction_events import ExtractionVision
    from countdown_reader import fmt
    results = ExtractionVision(config.MONITOR_INDEX).scan()
    for name, item in results.items():
        state = '绿色' if item['active'] else '未开启/未定位'
        timer = fmt(item['seconds']) if item['seconds'] is not None else '未读到'
        print(f"{name}：{state}，倒计时={timer}，位置={item['position']}")
    if not any(item['position'] is not None for item in results.values()):
        print('未定位到两个目标图标，请保持地图页可见并恢复正常缩放。')


def cmd_find_btn():
    pos, _box = wl.debug_locate(config)
    if pos:
        print(f"已定位到橙色“启动”按钮中心：{pos}")
        print("（只定位未点击。若坐标落在按钮上，说明识别正常。）")
    else:
        print("未找到“启动”按钮。请确认 WeGame 已打开三角洲页面、橙色按钮可见；")
        print("也可双击【3.校准启动按钮.bat】在截图上直接框选按钮，或调 config.py 里的 BTN_* 搜索范围。")


def cmd_learn_game():
    ok, name = wl.learn_game_process(config)
    if ok:
        print(f"已识别游戏进程：{name}，并写回 config.GAME_PROCESS_KEYWORDS。")
    else:
        print("没能自动识别。请先进入游戏（在对局/大厅中），保持游戏运行后再执行本命令；")
        print("或直接在 config.py 的 GAME_PROCESS_KEYWORDS 里手动填写游戏的 .exe 名。")


def do_restart(reason_time=None):
    """激活 WeGame 并点击启动。返回 (是否成功启动, 说明)。"""
    if STOP_REQUESTED.is_set():
        raise KeyboardInterrupt
    print(f"[{now_str()}] 开始执行自动重启：激活 WeGame ……")
    if not wl.activate_wegame(config):
        reason = wl.LAST_ACTIVATION_ERROR or "没能激活/找到 WeGame 窗口"
        print(f"[{now_str()}] 激活失败：{reason}")
        return False, reason
    print(f"[{now_str()}] 已确认 WeGame 主窗口处于前台，继续识别启动按钮。")

    # 可选：先点左侧“三角洲行动”页签，确保右下角“启动”对应的是三角洲
    if getattr(config, "CLICK_GAME_TAB_FIRST", False):
        try:
            wl.click_game_tab(config)
        except Exception:
            pass

    # 多次尝试定位并点击按钮（WeGame 页面可能需要一点时间刷新）
    clicked = False
    for i in range(20):
        if STOP_REQUESTED.is_set():
            raise KeyboardInterrupt
        pos = wl.locate_start_button(config)
        if pos:
            print(f"[{now_str()}] 定位到启动按钮 {pos}，准备发送点击输入。")
            if STOP_REQUESTED.is_set():
                raise KeyboardInterrupt
            wl._click(*pos)
            print(f"[{now_str()}] Windows已接受点击输入，继续确认游戏进程是否启动。")
            clicked = True
            break
        print(f"[{now_str()}] 第 {i+1}/20 次：{wl.LAST_BUTTON_ERROR or '未找到按钮'}，1.5 秒后重试……")
        time.sleep(1.5)

    if not clicked:
        return False, wl.LAST_BUTTON_ERROR or "激活了WeGame但未识别到启动按钮"

    # 等待并确认游戏进程起来
    deadline = time.time() + config.GAME_LAUNCH_WAIT
    while time.time() < deadline:
        if wl.is_game_running(config):
            return True, "游戏进程已启动"
        time.sleep(3)
    return False, "已点击启动，但 %d 秒内未检测到游戏进程" % config.GAME_LAUNCH_WAIT


def cmd_restart_now():
    ok, msg = do_restart()
    print(("成功：" if ok else "失败：") + msg)


def cmd_loop():
    print("=" * 64)
    print("炸撤小助手 · 撤离点监控 / 飞升音效 / 自动重启")
    print("版本：2026-11-15（核心精简版）")
    print(f"扫描间隔：{config.SCAN_INTERVAL}s；开启判定：绿色图标 + 可信倒计时")
    print(f"自动重启：{'开' if config.AUTO_RESTART else '关'} | "
          f"退出后等待：{getattr(config, 'RESTART_DELAY', 840)}s "
          f"(约 {getattr(config, 'RESTART_DELAY', 840)/60:.0f} 分钟)")
    game_kws = config.GAME_PROCESS_KEYWORDS
    print(f"游戏进程匹配词：{game_kws}")
    perms = wl.permission_report()
    if perms["mismatch"]:
        print("重要：WeGame为管理员权限、监控为普通权限，自动激活/点击会被Windows拦截。")
        print("请关闭此窗口，右键【9.以管理员权限开始监控.bat】选择【以管理员身份运行】。")
    print("按 F10 停止全部监控及待执行重启。")
    print("=" * 64)

    vision = events = None
    if getattr(config, 'EXITS_ENABLED', True):
        from extraction_events import ExtractionVision, ExtractionEvents
        vision = ExtractionVision(config.MONITOR_INDEX, names=getattr(config, 'ENABLED_EXIT_NAMES', None))
        events = ExtractionEvents(config.CONFIRM_TIMES)
    last_status_log = 0.0

    # 重启状态机
    quit_at = None                 # 检测到退出的时间戳；None=无待执行重启
    game_was_running = wl.is_game_running(config)   # 启动时是否已在游戏中
    run_start = time.time() if game_was_running else None
    restart_times = []             # 最近的自动重启时间戳
    stable_reset_done = game_was_running

    print(f"[{now_str()}] 初始状态：游戏" + ("正在运行" if game_was_running else "未运行（不会因此触发重启）"))
    ui_status.publish(game_running=game_was_running, foreground=False, restart_at=None, exits={}, audio={}, deliveries={})

    # 飞升者行动·第二步滴滴声监听（后台线程）
    ascend = None
    if getattr(config, "ASCEND_ALERT", False):
        try:
            from ascend_alert import AscendController
            ascend = AscendController(log=lambda m: print(f"[{now_str()}] {m}"))
            ascend.start()
        except Exception as e:
            print(f"[{now_str()}] 飞升第二步监听启动失败：{e}")
            if ascend:
                ascend.stop()
            ascend = None

    import chat_sender as cs
    STOP_REQUESTED.clear()
    stop_hotkey = cs.HotkeyWatcher("F10", request_stop)
    stop_hotkey.start()
    try:
        while not STOP_REQUESTED.is_set():
            # ---------- 1) 游戏进程 / 重启调度 ----------
            try:
                running = wl.is_game_running(config)
            except Exception as e:
                print(f"[{now_str()}] 进程检测异常：{e}")
                running = game_was_running

            if running:
                if not game_was_running:
                    # 从无到有：玩家手动启动 或 自动重启成功
                    if quit_at is not None:
                        print(f"[{now_str()}] 等待期内游戏已启动，取消本次自动重启。")
                        quit_at = None
                    run_start = time.time()
                    stable_reset_done = False
                game_was_running = True

                # 稳定运行一段时间后，重置“连续崩溃”计数
                if (not stable_reset_done and run_start
                        and time.time() - run_start >= config.STABLE_RUN_SECONDS):
                    if restart_times:
                        print(f"[{now_str()}] 游戏已稳定运行 "
                              f"{config.STABLE_RUN_SECONDS//60} 分钟，重置重启计数。")
                    restart_times = []
                    stable_reset_done = True
            else:
                if game_was_running:
                    # 进程从有到无：游戏被关闭（含 Alt+F4 强退/崩溃/正常退出）
                    game_was_running = False
                    run_start = None
                    if config.AUTO_RESTART:
                        quit_at = time.time()
                        ui_status.publish(game_running=False, foreground=False,
                                          restart_at=quit_at+config.RESTART_DELAY, exits={})
                        mins = config.RESTART_DELAY / 60
                        print(f"[{now_str()}] 检测到三角洲已退出，将在 {mins:.0f} 分钟后"
                              f"自动从 WeGame 重启（期间手动打开游戏可取消）。")
                        if config.PUSH_ON_QUIT:
                            push("三角洲已退出，14分钟后自动重启",
                                 f"检测到游戏进程退出。\n\n"
                                 f"- 将在 **{mins:.0f} 分钟** 后自动打开 WeGame 并点击“启动”\n"
                                 f"- 若你自己先打开游戏，则本次自动重启取消\n"
                                 f"- 时间：{now_str()}")
                else:
                    # 持续未运行：检查是否到了重启时间
                    if quit_at is not None and config.AUTO_RESTART:
                        if time.time() - quit_at >= config.RESTART_DELAY:
                            restart_times = [t for t in restart_times
                                             if time.time() - t < 3600]
                            if len(restart_times) >= config.MAX_RESTARTS_PER_HOUR:
                                print(f"[{now_str()}] 1小时内自动重启已达 "
                                      f"{config.MAX_RESTARTS_PER_HOUR} 次，停止自动重启以防循环崩溃。")
                                if config.PUSH_ON_RESTART:
                                    push("自动重启已暂停",
                                         f"游戏 1 小时内退出/重启已达 "
                                         f"{config.MAX_RESTARTS_PER_HOUR} 次，为避免循环崩溃已停止自动重启。\n\n"
                                         f"请检查游戏/网络后手动启动；确认正常后重新运行本监控即可恢复。")
                                quit_at = None
                            else:
                                print(f"[{now_str()}] 等待时间到，执行自动重启……")
                                try:
                                    ok, msg = do_restart()
                                except Exception as exc:
                                    ok, msg = False, f"自动重启执行异常：{exc}"
                                print(f"[{now_str()}] 自动重启结果：{'成功' if ok else '失败'}；{msg}")
                                restart_times.append(time.time())
                                quit_at = None
                                if ok:
                                    game_was_running = True
                                    run_start = time.time()
                                    stable_reset_done = False
                                if config.PUSH_ON_RESTART:
                                    if ok:
                                        push("三角洲已自动重新启动",
                                             f"已通过 WeGame 点击“启动”，游戏进程已启动。\n\n时间：{now_str()}")
                                    else:
                                        push("自动重启失败，请手动处理",
                                             f"自动重启未成功：{msg}\n\n时间：{now_str()}")

            # 截屏识别只在游戏前台进行，避免其他窗口中的绿色和数字误报。
            foreground = running and cs.is_game_foreground(config)
            ui_status.publish(game_running=running, foreground=foreground,
                              restart_at=quit_at+config.RESTART_DELAY if quit_at is not None else None)
            if ascend and foreground:
                try:
                    ascend.tick()
                except Exception as e:
                    print(f"[{now_str()}] 倒计时读取异常：{e}")
            if ascend and not running:
                ui_status.publish(audio={})
                with ascend.lock:
                    ascend.pending_msg = None
                if ascend.tracker:
                    ascend.tracker = None
            if ascend and running and ascend.tracker is None:
                import countdown_reader as cr
                regions = cr.configured_regions(config)
                ascend.tracker = cr.MultiCountdownTracker(regions) if regions else None

            # ---------- 2) 两个撤离点图标及各自倒计时 ----------
            if vision:
                try:
                    observations = vision.scan() if foreground else {}
                    messages = events.update(observations)
                    ui_status.publish(exits=ui_status.extraction_rows(events, observations))
                    for title, content in messages:
                        push(title, content, category='switch' if title.startswith('拉闸') else 'ascend')
                        if config.PLAY_SOUND:
                            play_alert()
                    if time.monotonic() - last_status_log >= 15:
                        status = events.status()
                        if status:
                            print(f"[{now_str()}] 撤离点倒计时：{status}")
                        for name, observation in observations.items():
                            if observation.get('active') and observation.get('seconds') is None:
                                print(f"[{now_str()}] {name}绿色，但倒计时未确认，不报警：{observation.get('timer_text', '')}")
                            elif observation.get('position') is None:
                                print(f"[{now_str()}] {name}未定位到图标，匹配分={observation.get('score', 0):.2f}")
                        last_status_log = time.monotonic()
                    if not running:
                        events.states.clear()
                except Exception as e:
                    print(f"[{now_str()}] 撤离点识别异常：{e}")
            STOP_REQUESTED.wait(config.SCAN_INTERVAL)

    except KeyboardInterrupt:
        pass
    finally:
        STOP_REQUESTED.set()
        stop_hotkey.stop()
        if ascend:
            ascend.stop()
        ui_status.publish(stopped=True, restart_at=None, exits={}, audio={})
        print("\n监控已停止，待执行的自动重启已取消。")


def cmd_read_countdown():
    """连续检查两页倒计时，输出实际选用的单一来源。"""
    import countdown_reader as cr
    regions = cr.configured_regions(config)
    if not regions:
        print("还没框选倒计时，战斗页用5号，地图页用7号文件框选。")
        return
    tr = cr.MultiCountdownTracker(regions)
    for i in range(10):
        v = tr.update()
        print(f"第{i+1}次 {tr.last_text}；{tr.status}；有效剩余={cr.fmt(v) if v is not None else '未读到'}")
        time.sleep(1)


def cmd_test_chat():
    """5 秒后在当前前台窗口模拟：回车->输入测试文字->回车。请先切到游戏并站在安全处。"""
    import chat_sender as cs
    msg = config.CHAT_TEMPLATE.format(start="12:35", end="08:05") + "（测试）"
    print(f"5 秒后发送：{msg}\n请立刻切到游戏对局（安全位置）……")
    time.sleep(5)
    cs.send_chat(msg, method=config.CHAT_INPUT_METHOD)
    print("已发送，请到游戏聊天框确认文字是否正确。若没出字，把 config.py 的 CHAT_INPUT_METHOD 改为 \"paste\" 再试。")


def cmd_listen_test():
    """只开声音监听 3 分钟：用来验证能否听到滴滴声（可在电脑上播放素材视频测试）。"""
    from beep_detector import LoopbackListener
    hits = []
    lis = LoopbackListener(on_alarm=lambda w: (hits.append(w), print(
        f"[{now_str()}] >>> 检测到滴滴警报！第一声在 {dt.datetime.fromtimestamp(w).strftime('%H:%M:%S')}")),
        device_keyword=config.AUDIO_DEVICE_KEYWORD, score_threshold=config.BEEP_SCORE_THRESHOLD,
        confirm_count=config.BEEP_CONFIRM_COUNT, period_tol=config.BEEP_PERIOD_TOL, rearm_sec=30)
    lis.start()
    print("声音监听测试 3 分钟：请在电脑上播放【声音素材\\滴滴声_原声前20秒.mp3】或游戏声音。Ctrl+C 结束。")
    try:
        for _ in range(180):
            time.sleep(1)
            if lis.error:
                break
    except KeyboardInterrupt:
        pass
    lis.stop()
    print(f"测试结束，共检测到 {len(hits)} 次警报。")


def cmd_diagnose_wegame():
    """只读诊断，不激活窗口、不点击、不启动游戏。"""
    data = wl.diagnose_wegame(config)
    print("WeGame进程：" + ("正在运行" if data["process_running"] else "未运行"))
    print("当前前台窗口：" + data["foreground_title"])
    perms = data["permissions"]
    label = lambda flag: "管理员" if flag is True else ("普通权限" if flag is False else "查询失败")
    print("监控工具权限：" + label(perms["monitor_elevated"]))
    for item in perms["wegame"]:
        print(item["role"] + "权限：" + label(item["elevated"]))
    if perms["mismatch"]:
        print("权限不一致，Windows会阻止窗口操作和点击。请右键9号文件，以管理员身份运行监控。")
    windows = data["candidate_windows"]
    print(f"找到可用WeGame主窗口：{len(windows)} 个")
    for w in windows:
        print(f"  标题={w['title']}；最小化={w['minimized']}；前台={w['foreground']}；位置={w['rect']}")
    if not windows:
        print("未找到可用主窗口，请从任务栏或托盘打开WeGame主页面后再运行监控。")
    print("诊断结束：未切换窗口，未点启动，未发送消息。")


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    {
        "--test": cmd_test,
        "--once": cmd_once,
        "--find-btn": cmd_find_btn,
        "--learn-game": cmd_learn_game,
        "--restart-now": cmd_restart_now,
        "--read-countdown": cmd_read_countdown,
        "--test-chat": cmd_test_chat,
        "--listen-test": cmd_listen_test,
        "--diagnose-wegame": cmd_diagnose_wegame,
    }.get(arg, cmd_loop)()


if __name__ == "__main__":
    main()
