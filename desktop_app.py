"""Desktop management UI and isolated monitor worker entry point."""
import json
import os
import queue
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback
import settings_store as store


def worker(task, log_path, stop_path, category='restart'):
    with open(log_path, 'w', encoding='utf-8', buffering=1) as output:
        sys.stdout = sys.stderr = output
        try:
            store.apply(store.load())
            import monitor
            def stop_watch():
                while not Path(stop_path).exists():
                    time.sleep(.15)
                monitor.request_stop()
            if task != 'smoke':
                threading.Thread(target=stop_watch, daemon=True).start()
            if task == 'monitor':
                monitor.cmd_loop()
            elif task in ('battle', 'map'):
                import calibrate_countdown
                calibrate_countdown.main(task)
            elif task == 'process':
                monitor.cmd_learn_game()
            elif task == 'diagnose':
                monitor.cmd_diagnose_wegame()
            elif task == 'push':
                from notifier import notify
                notify(category, store.APP_NAME + ' · 测试通知',
                       '这是' + store.FEATURES[category] + '的独立推送测试。')
            elif task == 'check-exits':
                monitor.cmd_once()
            elif task == 'smoke':
                # Packaged imports, resources and OCR: no capture, network or input.
                import cv2
                import numpy as np
                import scipy.signal
                import soundcard
                import chat_sender
                import countdown_reader
                import beep_detector
                from extraction_events import ExtractionVision
                vision = ExtractionVision()
                assert all(image is not None for image in vision.templates.values())
                assert beep_detector.load_template()['harmonics']
                assert countdown_reader._get_engine() is not None
                assert cv2.__version__ and np.__version__
                print('PACKAGED_SMOKE_OK')
        except KeyboardInterrupt:
            print('任务已停止。')
        except BaseException:
            traceback.print_exc()
            return 1
    return 0


class Manager:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk, self.root = tk, ttk, root
        self.process = None
        self.task = None
        self.offset = 0
        self.closing = False
        self.closing_at = None
        self.tray_icon = None
        self.tray_ready = False
        self.tray_events = queue.SimpleQueue()
        self.close_dialog = None
        self.settings = store.load()
        self.form_widgets = []
        self.feature_vars = {name: (tk.BooleanVar(value=row['enabled']), tk.BooleanVar(value=row['push']),
                                    tk.StringVar(value=row['target']))
                             for name, row in self.settings['features'].items()}
        self.default_target = tk.StringVar(value=self.settings['default_target'])
        self.sound = tk.BooleanVar(value=self.settings['sound'])
        self.chat = tk.BooleanVar(value=self.settings['chat'])
        self.close_prompt = tk.BooleanVar(value=self.settings['close_prompt'])
        self.close_choice = tk.StringVar(value='退出程序' if self.settings['close_action'] == 'exit' else '最小化到托盘')
        self.show_targets = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='●  已停止')
        self.saved_state = tk.StringVar(value='配置已保存')
        self.live = {}
        self.status_path = store.data_dir() / 'dashboard.json'
        self.show_path = store.data_dir() / 'show.request'
        self.show_path.unlink(missing_ok=True)
        self._syncing_exits = False
        from desktop_view import build
        build(self, root)

    def show_page(self, name):
        self.pages[name].tkraise()
        self.current_page = name
        self.log_open = name == 'logs'
        icons = {'overview': 'device-desktop', 'notifications': 'bell', 'tools': 'settings'}
        for key, button in self.nav.items():
            selected = key == name or (key == 'overview' and name == 'logs')
            button.configure(bg='#E7EEFF' if selected else '#F8FAFD',
                             fg='#3267E3' if selected else '#344054',
                             image=self.images[icons[key]+('-blue' if selected else '-ink')])

    def toggle_log(self):
        self.show_page('overview' if self.log_open else 'logs')

    def toggle_exits(self, *args):
        if self._syncing_exits:
            return
        self._syncing_exits = True
        try:
            for key in ('switch', 'ascend'):
                self.feature_vars[key][0].set(self.exits_enabled.get())
        finally:
            self._syncing_exits = False
        self.refresh_summary()

    def refresh_summary(self):
        self.target_text.set('已配置' if self.default_target.get().strip() or
                             any(row[2].get().strip() for row in self.feature_vars.values()) else '待配置')
        if not self._syncing_exits:
            self._syncing_exits = True
            self.exits_enabled.set(any(self.feature_vars[k][0].get() for k in ('switch', 'ascend')))
            self._syncing_exits = False
        self.refresh_dashboard()

    def mark_dirty(self, *args):
        self.saved_state.set('有未保存的修改')
        self.refresh_summary()

    def refresh_dashboard(self):
        from ui_status import timer_text
        now = time.time()
        active = self.process is not None and self.task == 'monitor'
        fresh = active and 0 <= now-self.live.get('updated_at', 0) <= 20
        running = self.live.get('game_running') if fresh else None
        foreground = self.live.get('foreground', False) if fresh else False
        self.game_text.set('尚未开始监控' if not active else '正在连接监控进程…' if not fresh else
                           '游戏运行中 · 正在识别画面' if foreground else
                           '游戏运行中 · 等待游戏画面' if running else '游戏未运行 · 等待启动')
        for key, name in [('switch', '拉闸撤离点'), ('ascend', '飞升撤离点')]:
            widgets = self.exit_widgets[key]
            row = self.live.get('exits', {}).get(name, {}) if foreground else {}
            timer = timer_text(row, now)
            enabled = self.feature_vars[key][0].get()
            label = ('已关闭' if not enabled else '未监控' if not active else
                     '已开启' if timer != '—' else '画面不可见' if fresh and running and not foreground else
                     {'closed': '未开启', 'checking': '确认中'}.get(row.get('state'), '等待识别'))
            opened = label == '已开启'
            widgets['state'].configure(text=label, fg='#198348' if opened else '#697586',
                                       bg='#E4F5E9' if opened else '#F3F5F8')
            widgets['timer'].configure(text=timer if opened else '—',
                                       fg='white' if opened else '#697586',
                                       bg='#14683D' if opened else '#F3F5F8')
            widgets['icon'].configure(image=self.images['run-green' if opened else 'run-muted'])
            delivery = self.live.get('deliveries', {}).get(key) if active else None
            text = '推送关闭' if not self.feature_vars[key][1].get() else {
                'sending': '推送中', 'sent': '已推送', 'failed': '推送失败', 'disabled': '推送关闭'
            }.get(delivery, '等待事件')
            widgets['push'].configure(text=text, fg='#198348' if text == '已推送' else '#697586')
        audio = self.live.get('audio', {}) if active else {}
        message = audio.get('message')
        self.audio_text.set('音效监控已关闭' if not self.feature_vars['audio'][0].get() else
                            '飞升音效已触发' if message else '等待飞升任务音效')
        if message:
            delivered = self.live.get('deliveries', {}).get('audio')
            state = '已局内发送' if audio.get('sent') else '消息已过期' if now > audio.get('expires_at', 0) else '切回游戏按 F8 发送'
            self.audio_detail.set(time.strftime('%H:%M:%S', time.localtime(audio['detected_at'])) + ' · ' +
                                  {'sent': '已推送', 'failed': '推送失败', 'disabled': '推送关闭', 'sending': '推送中'}.get(delivered, '已记录') + ' · ' + state)
        else:
            self.audio_detail.set('触发后推送并记录，切回游戏按 F8 发送')
        deadline = self.live.get('restart_at') if fresh else None
        if not self.feature_vars['restart'][0].get():
            text = '自动重启已关闭'
        elif not active:
            text = '开始监控后检测游戏进程'
        elif deadline:
            seconds = max(0, round(deadline-now))
            text = f'等待重启 {seconds//60:02d}:{seconds%60:02d}'
        elif running is None:
            text = '正在检测游戏进程…'
        else:
            text = '游戏运行中' if running else '游戏未运行；尚无重启计划'
        self.restart_text.set(text)
        waiting = bool(deadline and self.feature_vars['restart'][0].get())
        self.restart_label.configure(font=self.restart_waiting_font if waiting else self.restart_font,
                                     fg='white' if waiting else '#697586',
                                     bg='#8B4513' if waiting else 'white')

    def entry(self, parent, variable):
        widget = self.ttk.Entry(parent, textvariable=variable, show='•')
        self.form_widgets.append(widget)
        return widget

    def toggle_targets(self):
        for widget in self.form_widgets:
            if isinstance(widget, self.ttk.Entry):
                widget.configure(show='' if self.show_targets.get() else '•')

    def append(self, text):
        # Keep credentials out of the visible log, including third-party exceptions.
        for target in [self.default_target.get()] + [row[2].get() for row in self.feature_vars.values()]:
            if target:
                text = text.replace(target, '[已隐藏推送地址]')
        self.log.configure(state='normal')
        self.log.insert('end', text)
        if int(self.log.index('end-1c').split('.')[0]) > 1500:
            self.log.delete('1.0', '300.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def save(self):
        from tkinter import messagebox
        try:
            settings = store.load()  # Preserve calibration written by a child task.
            settings.update(default_target=self.default_target.get().strip(), sound=self.sound.get(), chat=self.chat.get())
            settings.update(close_prompt=self.close_prompt.get(), close_action=self.selected_close_action())
            settings['features'] = {name: {'enabled': e.get(), 'push': p.get(), 'target': t.get().strip()}
                                    for name, (e, p, t) in self.feature_vars.items()}
            store.save(settings)
            self.settings = settings
            self.saved_state.set('配置已保存')
            self.refresh_summary()
            self.append('设置已保存。\n')
            return True
        except Exception as exc:
            messagebox.showerror('设置未保存', str(exc), parent=self.root)
            return False

    def set_busy(self, busy):
        for widget in self.form_widgets + [self.start_button, self.save_button, self.test_button]:
            widget.configure(state='disabled' if busy else 'normal')
        self.category_combo.configure(state='disabled' if busy else 'readonly')
        self.close_combo.configure(state='disabled' if busy else 'readonly')
        self.stop_button.configure(state='normal' if busy else 'disabled')
        self.saved_state.set('运行中 · 停止后可修改配置' if busy else '配置已保存')
        if busy:
            self.start_button.pack_forget()
            self.save_button.pack_forget()
        else:
            self.start_button.pack(side='right', after=self.stop_button, padx=(8, 10))
            self.save_button.pack(side='right', after=self.start_button, padx=(8, 0))

    def start_task(self, task):
        if self.process or not self.save():
            return
        if task == 'monitor' and not any(row['enabled'] for row in self.settings['features'].values()):
            self.append('请至少开启一项功能。\n')
            return
        self.log_path = store.data_dir() / 'current.log'
        self.stop_path = store.data_dir() / 'stop.request'
        self.stop_path.unlink(missing_ok=True)
        self.log_path.write_text('', encoding='utf-8')
        self.offset = 0
        self.task = task
        self.live = {}
        self.status_path.unlink(missing_ok=True)
        category = next(name for name, label in store.FEATURES.items() if label == self.category.get())
        executable = [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, str(Path(__file__).resolve())]
        args = executable + ['--worker', task, str(self.log_path), str(self.stop_path), category]
        try:
            env = os.environ.copy()
            env['DELTA_MONITOR_STATUS'] = str(self.status_path)
            self.process = subprocess.Popen(args, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        except OSError as exc:
            self.append('启动失败：' + str(exc) + '\n')
            return
        self.set_busy(True)
        self.status.set('●  监控运行中' if task == 'monitor' else '●  正在执行操作')
        self.show_page('overview')
        if task != 'monitor' and not self.log_open:
            self.toggle_log()
        self.refresh_dashboard()

    def stop(self):
        if self.process:
            self.stop_path.touch()
            self.status.set('●  正在停止…')
            self.stop_button.configure(state='disabled')

    def poll(self):
        self.poll_tray()
        if self.closing and self.process is None:
            return
        if self.process:
            if self.task == 'monitor':
                try:
                    self.live = json.loads(self.status_path.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    pass
            if self.log_path.exists():
                with self.log_path.open(encoding='utf-8', errors='replace') as log:
                    log.seek(self.offset)
                    text = log.read()
                    self.offset = log.tell()
                if text:
                    self.append(text)
            code = self.process.poll()
            if code is not None:
                self.process = None
                self.set_busy(False)
                self.status.set('●  已停止' if code == 0 else '●  操作异常，请查看日志')
                self.append('任务已结束。\n')
            elif self.closing and time.monotonic()-self.closing_at > 20:
                self.process.terminate()
                self.append('正在结束未响应的监控进程。\n')
        self.refresh_dashboard()
        if self.closing and self.process is None:
            self.destroy()
            return
        self.root.after(500, self.poll)

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.closing_at = time.monotonic()
        self.stop()
        if not self.process:
            self.destroy()

    def destroy(self):
        if self.tray_icon:
            self.tray_icon.stop()
            self.tray_icon = None
        self.root.destroy()

    def selected_close_action(self):
        return 'exit' if self.close_choice.get() == '退出程序' else 'tray'

    def apply_close(self, action, remember=False):
        if remember:
            from tkinter import messagebox
            was_dirty = self.saved_state.get() == '有未保存的修改'
            try:
                settings = store.load()
                settings.update(close_prompt=False, close_action=action)
                store.save(settings)
            except (OSError, ValueError) as exc:
                messagebox.showerror('关闭方式未保存', str(exc), parent=self.root)
                return
            self.close_prompt.set(False)
            self.close_choice.set('退出程序' if action == 'exit' else '最小化到托盘')
            if not was_dirty:
                self.saved_state.set('运行中 · 停止后可修改配置' if self.process else '配置已保存')
        if action == 'tray':
            self.hide_to_tray()
        else:
            self.close()

    def request_close(self):
        if self.closing:
            return
        if not self.close_prompt.get():
            self.apply_close(self.selected_close_action())
            return
        if self.close_dialog and self.close_dialog.winfo_exists():
            self.close_dialog.lift()
            return
        tk, ttk = self.tk, self.ttk
        dialog = self.close_dialog = tk.Toplevel(self.root)
        dialog.title('关闭 ' + store.APP_NAME)
        dialog.configure(bg='white')
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.geometry(f'490x320+{self.root.winfo_rootx()+150}+{self.root.winfo_rooty()+120}')
        body = ttk.Frame(dialog, padding=24)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='关闭窗口时要怎么做？', font=('Microsoft YaHei UI', 14, 'bold')).pack(anchor='w')
        ttk.Label(body, text='最小化后监控继续运行；退出将停止监控并取消自动重启。',
                  wraplength=425).pack(anchor='w', pady=(10, 12))
        action = tk.StringVar(value=self.selected_close_action())
        remember = tk.BooleanVar(value=False)
        for value, label in [('tray', '最小化到右下角托盘'), ('exit', '退出程序')]:
            ttk.Radiobutton(body, text=label, value=value, variable=action).pack(anchor='w', pady=3)
        ttk.Checkbutton(body, text='以后不再询问（可在设置中修改）', variable=remember).pack(anchor='w', pady=(10, 8))
        buttons = ttk.Frame(body)
        buttons.pack(fill='x')
        def confirm():
            choice, save = action.get(), remember.get()
            dialog.destroy()
            self.apply_close(choice, save)
        ttk.Button(buttons, text='确定', style='Primary.TButton', command=confirm).pack(side='right')
        ttk.Button(buttons, text='取消', command=dialog.destroy).pack(side='right', padx=8)
        dialog.bind('<Escape>', lambda _: dialog.destroy())
        dialog.grab_set()

    def hide_to_tray(self):
        if self.tray_ready:
            self.root.withdraw()
            return
        if self.tray_icon:
            return
        from tkinter import messagebox
        try:
            import pystray
            from PIL import Image
            self.tray_icon = pystray.Icon('DeltaForceMonitor',
                Image.open(Path(__file__).parent/'assets'/'ui'/'app.png').copy(), store.APP_NAME,
                menu=pystray.Menu(
                    pystray.MenuItem('打开 ' + store.APP_NAME, lambda: self.tray_events.put(('show', None)), default=True),
                    pystray.MenuItem('退出程序', lambda: self.tray_events.put(('exit', None)))))
            def ready(icon):
                try:
                    icon.visible = True
                    self.tray_events.put(('hide', None))
                except Exception as exc:
                    self.tray_events.put(('error', str(exc)))
            self.tray_icon.run_detached(setup=ready)
        except Exception as exc:
            if self.tray_icon:
                self.tray_icon.stop()
                self.tray_icon = None
            messagebox.showerror('无法最小化到托盘', str(exc), parent=self.root)

    def poll_tray(self):
        if self.show_path.exists():
            self.show_path.unlink(missing_ok=True)
            self.tray_events.put(('show', None))
        while not self.tray_events.empty():
            action, message = self.tray_events.get_nowait()
            if self.closing:
                continue
            if action == 'hide':
                self.tray_ready = True
                self.root.withdraw()
            elif action == 'show':
                self.root.deiconify()
                self.root.lift()
            elif action == 'exit':
                self.close()
            elif action == 'error':
                from tkinter import messagebox
                self.root.deiconify()
                if self.tray_icon:
                    self.tray_icon.stop()
                    self.tray_icon = None
                self.tray_ready = False
                messagebox.showerror('无法最小化到托盘', message, parent=self.root)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--worker':
        return worker(*sys.argv[2:])
    # Avoid two management windows sharing a monitor log or stop request.
    import ctypes
    from ctypes import wintypes
    ctypes.windll.kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    ctypes.windll.kernel32.CreateMutexW.restype = wintypes.HANDLE
    ctypes.windll.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, 'Local\\DeltaForceMonitorManager')
    if not mutex or ctypes.windll.kernel32.GetLastError() == 183:
        (store.data_dir() / 'show.request').touch()
        return 0
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        try:
            Manager(root)
        except Exception as exc:
            messagebox.showerror('无法打开管理中心', str(exc), parent=root)
            root.destroy()
            return 1
        root.mainloop()
        return 0
    finally:
        ctypes.windll.kernel32.CloseHandle(mutex)


if __name__ == '__main__':
    raise SystemExit(main())
