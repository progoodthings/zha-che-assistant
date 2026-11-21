"""Light desktop layout, based on the selected Product Design reference."""
import os
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk
import settings_store as store

INK, MUTED, LINE, BLUE = '#182334', '#697586', '#E7EBF1', '#3267E3'


def build(m, root):
    m.tk, m.ttk, m.root = tk, ttk, root
    root.title(store.APP_NAME + ' · 管理中心')
    root.geometry('1280x900')
    root.minsize(1120, 800)
    root.configure(bg='white')
    fonts = {}
    def font(size, bold=False, family='Microsoft YaHei UI'):
        key = (size, bold, family)
        if key not in fonts:
            fonts[key] = tkfont.Font(root=root, family=family, size=-round(size*4/3), weight='bold' if bold else 'normal')
        return fonts[key]
    root.option_add('*Font', font(13))
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', background='white', foreground=INK, font=font(13))
    style.configure('TFrame', background='white')
    style.configure('TButton', padding=(15, 9), borderwidth=1, background='white',
                    bordercolor='#CCD4E0', lightcolor='white', darkcolor='white', focuscolor=BLUE)
    style.map('TButton', background=[('active', '#EDF3FF')], foreground=[('disabled', '#A4ACB9')])
    style.configure('Primary.TButton', background=BLUE, foreground='white', bordercolor=BLUE)
    style.map('Primary.TButton', background=[('disabled', '#DCE5F6'), ('active', '#2458CF')],
              foreground=[('disabled', '#8C9CB7')])
    style.configure('TCheckbutton', background='white', padding=(0, 4))
    style.map('TCheckbutton', background=[('active', 'white')])
    style.configure('TEntry', padding=9, fieldbackground='#FAFBFD', bordercolor='#DDE3EC',
                    lightcolor='white', darkcolor='white')
    style.configure('TCombobox', padding=8, bordercolor='#DDE3EC', arrowsize=12)
    m.images = {}
    assets = Path(__file__).resolve().parent/'assets'/'ui'
    for path in assets.glob('*.png'):
        m.images[path.stem] = tk.PhotoImage(file=str(path))
    root.iconphoto(True, m.images['triangle-blue'])
    style.element_create('Toggle.indicator', 'image', m.images['switch-0-0'],
                         ('disabled', 'selected', m.images['switch-1-1']),
                         ('disabled', m.images['switch-0-1']),
                         ('selected', m.images['switch-1-0']))
    style.layout('Switch.TCheckbutton', [('Checkbutton.padding', {'sticky': 'nswe', 'children':
                 [('Toggle.indicator', {'side': 'left', 'sticky': ''}),
                  ('Checkbutton.focus', {'side': 'left', 'sticky': 'w', 'children':
                   [('Checkbutton.label', {'sticky': 'nswe'})]})]})])
    style.element_create('Check.indicator', 'image', m.images['check-0-0'],
                         ('disabled', 'selected', m.images['check-1-1']),
                         ('disabled', m.images['check-0-1']), ('selected', m.images['check-1-0']))
    style.layout('TCheckbutton', [('Checkbutton.padding', {'sticky': 'nswe', 'children':
                 [('Check.indicator', {'side': 'left', 'sticky': ''}),
                  ('Checkbutton.focus', {'side': 'left', 'sticky': 'w', 'children':
                   [('Checkbutton.label', {'sticky': 'nswe'})]})]})])

    def frame(parent, **kw):
        return tk.Frame(parent, bg=kw.pop('bg', 'white'), **kw)

    def label(parent, text=None, size=14, bold=False, color=INK, **kw):
        return tk.Label(parent, text=text, bg=parent.cget('bg'), fg=color,
                        font=font(size, bold),
                        anchor='w', bd=0, **kw)

    def rule(parent, **kw):
        line = frame(parent, bg=LINE, height=1)
        line.pack(fill='x', **kw)

    def toggle(parent, variable):
        widget = ttk.Checkbutton(parent, variable=variable, style='Switch.TCheckbutton', takefocus=True)
        m.form_widgets.append(widget)
        return widget

    def show_serverchan_guide():
        guide = tk.Toplevel(root)
        guide.title('Server 酱使用指南')
        guide.transient(root)
        guide.configure(bg='white')
        guide.bind('<Escape>', lambda _: guide.destroy())
        content = frame(guide, padx=24, pady=20)
        content.pack(fill='both', expand=True)
        label(content, '用微信接收通知', 20, True).pack(anchor='w')
        for title, detail in [
            ('1. 登录并配置接收通道', '用微信扫码登录 Server 酱 Turbo，在「通道配置」中按提示启用微信接收，再到「SendKey」页面复制 SCT 开头的密钥。'),
            ('2. 保存到炸撤小助手', '在「通知」页把密钥粘贴到「默认 Server 酱地址」，开启你需要的推送，点击「保存设置」。同一个地址收所有通知时，独立地址留空即可。'),
            ('3. 确认微信收到通知', '选一个已开启推送的通知类型，点击「发送测试通知」，再查看微信和软件的运行记录。'),
        ]:
            label(content, title, 14, True).pack(anchor='w', pady=(14, 4))
            label(content, detail, 12, wraplength=500, justify='left').pack(anchor='w')
        label(content, 'SendKey 是推送密钥，请勿分享或贴到公开截图。', 11, color=MUTED).pack(anchor='w', pady=(14, 0))

        def open_official(url):
            try:
                os.startfile(url)
            except OSError:
                messagebox.showerror('无法打开浏览器', url, parent=guide)

        actions = frame(content)
        actions.pack(fill='x', pady=(16, 0))
        ttk.Button(actions, text='官方 SendKey 教程',
                   command=lambda: open_official('https://sct.ftqq.com/docs/getting-started/sendkey/')).pack(side='left')
        ttk.Button(actions, text='打开 Turbo 官网',
                   command=lambda: open_official('https://sct.ftqq.com/')).pack(side='left', padx=8)
        ttk.Button(actions, text='关闭', command=guide.destroy).pack(side='right')

    root.rowconfigure(1, weight=1)
    root.columnconfigure(1, weight=1)
    rail = frame(root, bg='#F8FAFD', width=82)
    rail.grid(row=0, column=0, rowspan=3, sticky='ns')
    rail.pack_propagate(False)
    label(rail, image=m.images['triangle-blue']).pack(pady=(24, 27))
    m.nav = {}
    for name, text, icon in [('overview', '监控', 'device-desktop'),
                             ('notifications', '通知', 'bell'), ('tools', '设置', 'settings')]:
        button = tk.Button(rail, text=text, image=m.images[f'{icon}-ink'], compound='top',
                           font=font(12), bg='#F8FAFD', fg='#344054',
                           activebackground='#E7EEFF', activeforeground=BLUE, relief='flat',
                           bd=0, pady=12, cursor='hand2', command=lambda n=name: m.show_page(n))
        button.pack(fill='x', padx=8, pady=4)
        m.nav[name] = button
    frame(root, bg=LINE, width=1).grid(row=0, column=0, rowspan=3, sticky='nse')

    header = frame(root, padx=27, pady=18)
    header.grid(row=0, column=1, sticky='ew')
    label(header, store.APP_NAME, 28, True).pack(side='left')
    m.status_label = label(header, size=12, color=MUTED, textvariable=m.status)
    m.status_label.pack(side='left', padx=25)
    m.stop_button = ttk.Button(header, text='停止监控', command=m.stop, state='disabled')
    m.stop_button.pack(side='right')
    m.start_button = ttk.Button(header, text='开始监控', style='Primary.TButton', command=lambda: m.start_task('monitor'))
    m.start_button.pack(side='right', padx=(8, 10))
    m.save_button = ttk.Button(header, text='保存设置', command=m.save)
    m.save_button.pack(side='right', padx=(8, 0))
    frame(root, bg=LINE, height=1).grid(row=0, column=1, sticky='sew')
    m.page_host = frame(root)
    m.page_host.grid(row=1, column=1, sticky='nsew')
    m.page_host.rowconfigure(0, weight=1)
    m.page_host.columnconfigure(0, weight=1)
    m.pages = {name: frame(m.page_host) for name in [*m.nav, 'logs']}
    for page in m.pages.values():
        page.grid(row=0, column=0, sticky='nsew')

    page = m.pages['overview']
    page.rowconfigure(0, weight=1)
    page.columnconfigure(0, weight=62, uniform='content')
    page.columnconfigure(2, weight=38, uniform='content')
    main = frame(page, padx=27, pady=27)
    main.grid(row=0, column=0, sticky='nsew')
    frame(page, bg=LINE, width=1).grid(row=0, column=1, sticky='ns')
    inspector = frame(page, padx=25, pady=30)
    inspector.grid(row=0, column=2, sticky='nsew')
    label(main, '实时监控', 34, True).pack(anchor='w')
    sub = frame(main)
    sub.pack(fill='x', pady=(14, 44))
    label(sub, image=m.images['device-gamepad-2-green']).pack(side='left', padx=(0, 9))
    m.game_text = tk.StringVar(value='尚未开始监控')
    m.game_label = label(sub, textvariable=m.game_text, color=MUTED)
    m.game_label.pack(side='left')
    table = frame(main)
    table.pack(fill='x')
    for column, weight in enumerate([31, 20, 32, 17]):
        table.columnconfigure(column, weight=weight, uniform='table')
    for column, text in enumerate(['点位', '状态', '剩余时间', '通知']):
        heading = tk.Label(table, text=text, bg='#F3F5F8', fg='#657083', anchor='w',
                           font=font(14), padx=10, pady=12)
        heading.grid(row=0, column=column, sticky='ew')
    m.exit_widgets = {}
    for row, (key, name) in enumerate([('switch', '拉闸撤离点'), ('ascend', '飞升撤离点')], 1):
        identity = frame(table)
        identity.grid(row=row*2-1, column=0, sticky='ew', pady=44)
        icon = label(identity, image=m.images['run-muted'])
        icon.pack(side='left', padx=(7, 8))
        label(identity, name, 18, True).pack(side='left')
        state = label(table, '未监控', 13, color=MUTED, padx=8, pady=4)
        state.grid(row=row*2-1, column=1, sticky='w', padx=5)
        timer = tk.Label(table, text='—', bg='#F3F5F8', fg='#697586',
                         font=font(49, True, 'Consolas'), width=5, padx=12, pady=6)
        timer.grid(row=row*2-1, column=2, sticky='w', padx=6)
        push = label(table, '等待事件', 13, color=MUTED)
        push.grid(row=row*2-1, column=3, sticky='w', padx=9)
        frame(table, bg=LINE, height=1).grid(row=row*2, column=0, columnspan=4, sticky='ew')
        m.exit_widgets[key] = {'state': state, 'timer': timer, 'push': push, 'icon': icon}
    sound_box = frame(main, bg='#EEF4FF', padx=17, pady=17)
    sound_box.pack(fill='x', pady=(30, 0))
    label(sound_box, image=m.images['volume-blue']).pack(side='left', padx=(0, 10))
    sound_copy = frame(sound_box, bg='#EEF4FF')
    sound_copy.pack(side='left', fill='x', expand=True)
    m.audio_text = tk.StringVar(value='等待飞升任务音效')
    m.audio_detail = tk.StringVar(value='触发后推送并记录，切回游戏按 F8 发送')
    label(sound_copy, textvariable=m.audio_text, size=16, bold=True).pack(anchor='w')
    label(sound_copy, textvariable=m.audio_detail, size=12, color=MUTED,
          wraplength=370, justify='left').pack(anchor='w', pady=(4, 0))
    label(sound_box, 'F8', 14, True, BLUE, padx=8, pady=4, relief='solid', borderwidth=1).pack(side='right')

    m.log_toggle = tk.Button(main, text='查看运行记录  ›', anchor='w', command=m.toggle_log,
                             bg='white', fg=INK, activebackground='#F8FAFD', relief='flat', bd=0,
                             font=font(14, True), pady=16, cursor='hand2')
    m.log_toggle.pack(fill='x', pady=(30, 0))
    log_header = frame(m.pages['logs'], padx=38, pady=25)
    log_header.pack(fill='x')
    label(log_header, '运行记录', 26, True).pack(side='left')
    ttk.Button(log_header, text='返回实时监控', command=m.toggle_log).pack(side='right')
    m.log_frame = frame(m.pages['logs'], padx=38, pady=10)
    m.log_frame.pack(fill='both', expand=True)
    m.log_frame.rowconfigure(0, weight=1)
    m.log_frame.columnconfigure(0, weight=1)
    m.log = tk.Text(m.log_frame, height=6, bg='#F7F9FC', fg='#4D596D', insertbackground=INK,
                    font=font(11), relief='flat', padx=12, pady=10,
                    wrap='word', state='disabled')
    m.log.grid(row=0, column=0, sticky='nsew')
    scroll = ttk.Scrollbar(m.log_frame, command=m.log.yview)
    scroll.grid(row=0, column=1, sticky='ns')
    m.log.configure(yscrollcommand=scroll.set)
    m.log_open = False

    label(inspector, '本次监控', 26, True).pack(anchor='w', pady=(0, 24))
    def feature(title, description, variable):
        top = frame(inspector)
        top.pack(fill='x')
        label(top, title, 18, True).pack(side='left')
        toggle(top, variable).pack(side='right')
        label(inspector, description, 14, color=MUTED, wraplength=355, justify='left').pack(anchor='w', pady=(7, 12))

    m.exits_enabled = tk.BooleanVar(value=any(m.feature_vars[k][0].get() for k in ('switch', 'ascend')))
    feature('撤离点监控', '识别绿色图标与倒计时，确认开启后推送', m.exits_enabled)
    for key, text in [('switch', '拉闸撤离点 · 初始 5 分钟'), ('ascend', '飞升撤离点 · 初始 12 分钟')]:
        widget = ttk.Checkbutton(inspector, text=text, variable=m.feature_vars[key][0])
        widget.pack(anchor='w', padx=14, pady=1)
        m.form_widgets.append(widget)
    rule(inspector, pady=20)
    feature('飞升音效', '监听特殊音效，推送并保存局内消息', m.feature_vars['audio'][0])
    rule(inspector, pady=(8, 20))
    feature('自动重启', '游戏退出 14 分钟后，通过 WeGame 启动', m.feature_vars['restart'][0])
    m.restart_text = tk.StringVar(value='开始监控后检测游戏进程')
    m.restart_label = label(inspector, textvariable=m.restart_text, size=10, color=MUTED,
                            wraplength=320, justify='left', padx=8, pady=5)
    m.restart_label.pack(anchor='w', pady=(0, 8))
    m.restart_font = font(10)
    m.restart_waiting_font = font(21, True)
    rule(inspector, pady=(10, 21))
    notify = frame(inspector)
    notify.pack(fill='x')
    label(notify, image=m.images['circle-check-green']).pack(side='left', padx=(0, 7))
    label(notify, 'Server 酱', 15, True).pack(side='left')
    m.target_text = tk.StringVar()
    label(notify, textvariable=m.target_text, size=12, color='#198348').pack(side='left', padx=7)
    notify_actions = frame(inspector)
    notify_actions.pack(anchor='w', pady=(13, 0))
    ttk.Button(notify_actions, text='管理通知', command=lambda: m.show_page('notifications')).pack(side='left')
    ttk.Button(notify_actions, text='Server 酱使用指南', command=show_serverchan_guide).pack(side='left', padx=(8, 0))

    notifications = m.pages['notifications']
    body = frame(notifications, padx=38, pady=27)
    body.pack(fill='both', expand=True)
    notification_header = frame(body)
    notification_header.pack(fill='x')
    label(notification_header, '通知设置', 26, True).pack(side='left')
    ttk.Button(notification_header, text='Server 酱使用指南', command=show_serverchan_guide).pack(side='right')
    label(body, '独立管理每类通知与接收地址', color=MUTED).pack(anchor='w', pady=(7, 26))
    label(body, '默认 Server 酱地址', 13, True).pack(anchor='w')
    label(body, '填写 SendKey 或完整 HTTPS 发送链接；独立地址留空时使用默认地址。', 10, color=MUTED).pack(anchor='w', pady=(6, 12))
    m.entry(body, m.default_target).pack(fill='x')
    ttk.Checkbutton(body, text='显示推送地址', variable=m.show_targets, command=m.toggle_targets).pack(anchor='w', pady=(8, 20))
    rule(body, pady=(0, 20))
    grid = frame(body)
    grid.pack(fill='x')
    grid.columnconfigure(1, weight=1)
    for col, title in enumerate(['通知类型', '独立推送地址', '推送开关']):
        label(grid, title, 10, color=MUTED).grid(row=0, column=col, sticky='w', pady=(0, 9))
    for row, (key, title) in enumerate(store.FEATURES.items(), 1):
        label(grid, title).grid(row=row, column=0, sticky='w', padx=(0, 30), pady=13)
        m.entry(grid, m.feature_vars[key][2]).grid(row=row, column=1, sticky='ew', padx=(0, 28))
        toggle(grid, m.feature_vars[key][1]).grid(row=row, column=2, sticky='w')
    rule(body, pady=23)
    tests = frame(body)
    tests.pack(fill='x')
    label(tests, '验证通知', 12, True).pack(side='left')
    m.category = tk.StringVar(value=store.FEATURES['restart'])
    m.category_combo = ttk.Combobox(tests, textvariable=m.category, values=list(store.FEATURES.values()), state='readonly', width=20)
    m.category_combo.pack(side='left', padx=20)
    m.test_button = ttk.Button(tests, text='发送测试通知', command=lambda: m.start_task('push'))
    m.test_button.pack(side='left')
    label(body, '测试会实际发送通知；发送结果显示在监控页的运行记录中。', 10, color=MUTED).pack(anchor='w', pady=13)

    settings = frame(m.pages['tools'], padx=38, pady=27)
    settings.pack(fill='both', expand=True)
    label(settings, '设置与诊断', 26, True).pack(anchor='w')
    label(settings, '本地提醒、画面校准与启动环境', color=MUTED).pack(anchor='w', pady=(7, 25))
    for text, variable in [('本地提示音', m.sound), ('F8 局内粘贴发送（回车 → 粘贴 → 回车）', m.chat)]:
        widget = ttk.Checkbutton(settings, text=text, variable=variable)
        widget.pack(anchor='w', pady=7)
        m.form_widgets.append(widget)
    rule(settings, pady=(15, 12))
    label(settings, '关闭窗口', 14, True).pack(anchor='w')
    close_row = frame(settings)
    close_row.pack(fill='x', pady=(8, 0))
    check = ttk.Checkbutton(close_row, text='每次关闭时询问', variable=m.close_prompt)
    check.pack(side='left', padx=(0, 20))
    m.form_widgets.append(check)
    label(close_row, '默认操作', 11, color=MUTED).pack(side='left', padx=(0, 10))
    m.close_combo = ttk.Combobox(close_row, textvariable=m.close_choice,
        values=['最小化到托盘', '退出程序'], state='readonly', width=17)
    m.close_combo.pack(side='left')
    label(settings, '关闭询问后直接执行默认操作。托盘图标右键可打开主窗口或退出。',
          10, color=MUTED).pack(anchor='w', pady=(6, 0))
    for title, subtitle, buttons in [
        ('倒计时校准', '分别框选战斗页与地图页，保留另一页已经保存的位置。', [('战斗页倒计时', 'battle'), ('地图页倒计时', 'map')]),
        ('运行诊断', '检查游戏进程、WeGame 窗口和撤离点识别结果。', [('识别游戏进程', 'process'), ('诊断 WeGame', 'diagnose'), ('检查撤离点', 'check-exits')])]:
        rule(settings, pady=18)
        label(settings, title, 14, True).pack(anchor='w')
        label(settings, subtitle, 10, color=MUTED).pack(anchor='w', pady=(7, 15))
        row = frame(settings)
        row.pack(fill='x')
        for text, task in buttons:
            button = ttk.Button(row, text=text, command=lambda t=task: m.start_task(t))
            button.pack(side='left', padx=(0, 12))
            m.form_widgets.append(button)
    label(settings, '监控时保持游戏画面可见；重新缩放地图后，请核对撤离点识别结果。', 10, color=MUTED).pack(anchor='w', pady=18)

    footer = frame(root, bg='#FAFBFD', padx=28, pady=13)
    footer.grid(row=2, column=1, sticky='ew')
    label(footer, 'F8', 12, True, BLUE, relief='solid', borderwidth=1, padx=6, pady=2).pack(side='left')
    label(footer, '局内发送', 12, color=MUTED).pack(side='left', padx=(8, 24))
    label(footer, 'F10', 12, True, '#344054', relief='solid', borderwidth=1, padx=6, pady=2).pack(side='left')
    label(footer, '停止监控并取消自动重启', 12, color=MUTED).pack(side='left', padx=8)
    label(footer, textvariable=m.saved_state, size=11, color=MUTED).pack(side='right')
    def resize(event):
        if event.widget is root:
            scale = min(1, event.width/1440, event.height/1000)
            for (size, bold, family), named_font in fonts.items():
                named_font.configure(size=-round(size*4/3*scale))
    root.bind('<Configure>', resize, add='+')
    m.exits_enabled.trace_add('write', m.toggle_exits)
    for variable in [m.default_target, m.sound, m.chat, m.close_prompt, m.close_choice] + [v for values in m.feature_vars.values() for v in values]:
        variable.trace_add('write', m.mark_dirty)
    m.refresh_summary()
    m.show_page('overview')
    root.protocol('WM_DELETE_WINDOW', m.request_close)
    root.after(500, m.poll)
    m.append('管理中心已就绪。确认功能开关后，点击“开始监控”。\n')
