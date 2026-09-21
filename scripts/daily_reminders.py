"""Run from backend: python scripts/daily_reminders.py --operator EMAIL [--execute]."""
import argparse
from app.core.database import SessionLocal
from app.models.identity import User
from app.services.daily_reminders import run_daily

parser = argparse.ArgumentParser()
parser.add_argument("--operator", required=True)
parser.add_argument("--execute", action="store_true")
args = parser.parse_args()
with SessionLocal() as db:
    user = db.query(User).filter_by(email=args.operator).one()
    print(run_daily(db, user, execute=args.execute))
