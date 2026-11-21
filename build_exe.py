from pathlib import Path
import shutil
import subprocess
import sys
from settings_store import APP_NAME

root=Path(__file__).resolve().parent
stage=root/'build_source'
stage.mkdir(exist_ok=True)
files=['desktop_app.py','desktop_view.py','ui_status.py','settings_store.py','monitor.py','config.py','notifier.py','ascend_alert.py','chat_sender.py','countdown_reader.py','extraction_events.py','color_detector.py','beep_detector.py','wegame_launcher.py','calibrate_countdown.py','calibrate_button.py','calibrate.py']
for name in files:
    text=(root/name).read_text(encoding='utf-8')
    if name=='config.py':
        lines=text.splitlines()
        changed=0
        for i,line in enumerate(lines):
            if line.startswith('SERVERCHAN_KEY ='):
                lines[i]='SERVERCHAN_KEY = ""'
                changed+=1
        assert changed==1, 'missing credential assignment'
        text='\n'.join(lines)+'\n'
    (stage/name).write_text(text,encoding='utf-8')
shutil.copytree(root/'assets',stage/'assets',dirs_exist_ok=True,ignore=shutil.ignore_patterns('*.ttf','*.css'))
shutil.copyfile(root/'beep_template.json',stage/'beep_template.json')
command=[sys.executable,'-m','PyInstaller','--noconfirm','--onefile','--windowed','--uac-admin','--name',APP_NAME,'--icon',str(root/'assets'/'ui'/'app.ico'),'--distpath',str(root/'dist'),'--workpath',str(root/'build'),'--specpath',str(root),'--hidden-import','pystray._win32','--collect-all','soundcard','--collect-submodules','winrt','--hidden-import','scipy.signal','--hidden-import','scipy._cyutility','--add-data',str(stage/'assets')+';assets','--add-data',str(stage/'beep_template.json')+';.',str(stage/'desktop_app.py')]
subprocess.run(command,cwd=stage,check=True)
