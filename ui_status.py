"""Optional, local-only state channel from the worker to the desktop view."""
import json
import os
from pathlib import Path
import threading
import time

_lock = threading.RLock()
_state = {}


def publish(**changes):
    target = os.environ.get('DELTA_MONITOR_STATUS')
    if not target:
        return
    with _lock:
        _state.update(changes)
        _state['updated_at'] = time.time()
        path = Path(target)
        try:
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(_state, ensure_ascii=False), encoding='utf-8')
            temporary.replace(path)
        except OSError:
            pass  # Display failures must not interrupt detection or hotkeys.


def section(name, **changes):
    if not os.environ.get('DELTA_MONITOR_STATUS'):
        return
    with _lock:
        values = dict(_state.get(name, {}))
        values.update(changes)
        publish(**{name: values})


def extraction_rows(events, observations, now=None):
    now = time.monotonic() if now is None else now
    rows = {}
    for name, obs in observations.items():
        state = events.states.get(name, {})
        anchor = state.get('anchor')
        trusted = (anchor and state.get('candidate') and
                   state['candidate'][1] == anchor[1] and
                   state.get('streak', 0) >= events.confirm and 0 <= now-anchor[1] <= 8)
        rows[name] = {'state': 'active' if trusted else
                      'checking' if obs.get('active') else
                      'closed' if obs.get('position') is not None else 'unknown',
                      'seconds': max(0, anchor[0]-(now-anchor[1])) if trusted else None,
                      'observed_at': time.time()}
    return rows


def timer_text(row, now=None):
    now = time.time() if now is None else now
    age = now-row.get('observed_at', 0)
    seconds = row.get('seconds')
    if row.get('state') != 'active' or seconds is None or not 0 <= age <= 8:
        return '—'
    remaining = max(0, round(seconds-age))
    return f'{remaining//60:02d}:{remaining%60:02d}'
