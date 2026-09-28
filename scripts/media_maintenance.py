"""Preview by default. Execution requires services to be stopped."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.media_maintenance import maintenance

parser = argparse.ArgumentParser()
parser.add_argument('--reset', action='store_true', help='Effacer rapports et relances définitivement')
parser.add_argument('--execute', action='store_true')
parser.add_argument('--services-stopped', action='store_true')
args = parser.parse_args()
if args.execute and not args.services_stopped:
    parser.error('Arrêtez backend, worker, passerelle et cron des relances, puis indiquez --services-stopped')
with SessionLocal() as db:
    print(json.dumps(maintenance(db, get_settings().storage_root, reset=args.reset,
                               execute=args.execute), ensure_ascii=False, indent=2))
