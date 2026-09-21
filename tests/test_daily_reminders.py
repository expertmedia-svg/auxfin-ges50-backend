from datetime import datetime
import pytest

from app.models.followup import EvidenceFollowup, FollowupMessage
from app.services.followups import update_followups
from app.services.daily_reminders import run_daily
from tests.test_followups import make_report


@pytest.mark.parametrize("uncertain", [False, True])
def test_grouped_daily_send_once_and_tracks_every_report(db_session, monkeypatch, uncertain):
    from app.models.identity import User, Role, UserRole
    user = User(email="auto@test.local", full_name="Operator", hashed_password="x", is_active=True)
    role = Role(code="operateur_validation", name="Operator")
    db_session.add_all([user, role])
    db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    for group in ("gr1.test", "gr2.test"):
        ev = make_report(db_session, group=group)
        ev.received_at = datetime(2026, 9, 21, 12)
        update_followups(db_session, ev)
    db_session.commit()
    db_session.refresh(user)
    calls = []
    def send(recipient, body):
        calls.append(body)
        if uncertain:
            from app.services.whatsapp.gateway_client import GatewayUnavailableError
            raise GatewayUnavailableError("test")
        return {"message_id": "one-message"}
    monkeypatch.setattr("app.services.daily_reminders.send_reminder", send)
    assert run_daily(db_session, user, datetime(2026, 9, 21, 21), True)['sent'] == 0
    assert run_daily(db_session, user, datetime(2026, 9, 21, 22), False)['prepared'] == 1
    assert not calls
    assert run_daily(db_session, user, datetime(2026, 9, 21, 22), True)['unknown' if uncertain else 'sent'] == 1
    assert len(calls) == 1 and 'gr1.test' in calls[0] and 'gr2.test' in calls[0]
    assert db_session.query(FollowupMessage).filter_by(status="UNKNOWN" if uncertain else "SENT").count() == 2
    assert db_session.query(EvidenceFollowup).filter_by(status="OPEN" if uncertain else "WAITING").count() == 2
    assert run_daily(db_session, user, datetime(2026, 9, 21, 23), True)['sent'] == 0
    assert len(calls) == 1
