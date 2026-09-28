"""Linux cron entrypoint: stop only running GES services, purge, restore them."""
import fcntl
import json
import subprocess
import sys
from pathlib import Path

backend = Path(__file__).resolve().parents[1]
names = {'ges-g50-backend', 'ges-g50-worker', 'ges-g50-whatsapp-gateway'}
lock_path = backend / '.media-maintenance.lock'
with lock_path.open('w') as lock:
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit('Maintenance déjà en cours')
    # Do not overlap the separate reminder process (scheduled 22:00–23:55).
    processes = subprocess.check_output(['ps', '-eo', 'args'], text=True)
    if any('scripts/daily_reminders.py' in line for line in processes.splitlines()):
        sys.exit('Relances en cours : purge reportée')
    apps = json.loads(subprocess.check_output(['pm2', 'jlist'], text=True))
    running = [a['name'] for a in apps if a['name'] in names
               and a.get('pm2_env', {}).get('status') == 'online']
    try:
        if running:
            subprocess.run(['pm2', 'stop', *running], check=True)
        subprocess.run([sys.executable, str(backend / 'scripts/media_maintenance.py'),
                        '--execute', '--services-stopped'], cwd=backend, check=True)
    finally:
        if running:
            subprocess.run(['pm2', 'restart', *running], check=True)
