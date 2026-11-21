"""User settings live outside the one-file executable's temporary directory."""
import copy
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

APP_NAME = 'DeltaForce-ZhaChe'

FEATURES = {'restart': '退出后自动重启', 'switch': '拉闸撤离点',
            'ascend': '飞升撤离点', 'audio': '飞升任务音效'}
CALIBRATION_FIELDS = ('COUNTDOWN_REGION', 'MAP_COUNTDOWN_REGION', 'START_BTN_CENTER',
                      'GAME_PROCESS_KEYWORDS')


def data_dir():
    path = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'DeltaForceMonitor'
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path():
    return Path(os.environ.get('DELTA_MONITOR_SETTINGS', str(data_dir() / 'settings.json')))


def defaults():
    import config
    return {'default_target': '', 'sound': bool(config.PLAY_SOUND), 'chat': True,
            'close_prompt': True, 'close_action': 'tray',
            'features': {name: {'enabled': True, 'push': True, 'target': ''} for name in FEATURES},
            'calibration': {name: copy.deepcopy(getattr(config, name)) for name in CALIBRATION_FIELDS}}


def validate_target(target):
    target = target.strip()
    if not target:
        return ''
    if '://' not in target:
        if not all(c.isalnum() or c in '_-' for c in target):
            raise ValueError('SendKey只能包含字母、数字、下划线或横线')
        return target
    url = urlsplit(target)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment:
        raise ValueError('推送链接必须为有效的HTTPS地址，且不包含账号或片段')
    return target


def load():
    result = defaults()
    path = settings_path()
    if path.exists():
        saved = json.loads(path.read_text(encoding='utf-8'))
        for field in ('default_target', 'sound', 'chat', 'close_prompt', 'close_action'):
            if field in saved:
                result[field] = saved[field]
        for name in FEATURES:
            result['features'][name].update(saved.get('features', {}).get(name, {}))
        result['calibration'].update({k: v for k, v in saved.get('calibration', {}).items()
                                      if k in CALIBRATION_FIELDS})
    return result


def save(settings):
    settings = copy.deepcopy(settings)
    if type(settings.get('close_prompt', True)) is not bool or settings.get('close_action', 'tray') not in ('tray', 'exit'):
        raise ValueError('关闭窗口的行为配置不正确')
    settings['default_target'] = validate_target(settings['default_target'])
    for feature in settings['features'].values():
        feature['target'] = validate_target(feature['target'])
        if type(feature['enabled']) is not bool or type(feature['push']) is not bool:
            raise ValueError('功能开关配置不正确')
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def save_calibration(name, value):
    if name not in CALIBRATION_FIELDS:
        raise ValueError('不支持的校准字段')
    settings = load()
    settings['calibration'][name] = value
    save(settings)


def apply(settings):
    import config
    config.SERVERCHAN_KEY = validate_target(settings['default_target'])
    config.AUTO_RESTART = bool(settings['features']['restart']['enabled'])
    config.ASCEND_ALERT = bool(settings['features']['audio']['enabled'])
    config.ENABLED_EXIT_NAMES = [label for name, label in [('switch', '拉闸撤离点'), ('ascend', '飞升撤离点')]
                                 if settings['features'][name]['enabled']]
    config.EXITS_ENABLED = bool(config.ENABLED_EXIT_NAMES)
    config.PLAY_SOUND = bool(settings['sound'])
    config.CHAT_ENABLED = bool(settings['chat'])
    config.NOTIFICATION_ROUTES = {name: {'enabled': bool(row['push']), 'target': row['target']}
                                  for name, row in settings['features'].items()}
    for name, value in settings['calibration'].items():
        if name in CALIBRATION_FIELDS:
            if name == 'GAME_PROCESS_KEYWORDS':
                if not isinstance(value, list) or not value or not all(isinstance(x,str) and x for x in value):
                    raise ValueError('游戏进程配置不正确')
            else:
                length = 2 if name == 'START_BTN_CENTER' else 4
                if not isinstance(value,list) or len(value) not in (0,length) or not all(type(x) is int for x in value):
                    raise ValueError('校准坐标配置不正确')
            setattr(config, name, value)
