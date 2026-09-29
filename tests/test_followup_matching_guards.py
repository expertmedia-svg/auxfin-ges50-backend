import pytest
from datetime import timedelta
from app.models.applications import Application
from app.services.followups import matches
from tests.test_followups import make_report


@pytest.mark.parametrize("difference", ["app", "unknown_app", "group", "date", "sender", "ambiguous", "older", "invalid"])
def test_other_report_never_matches(db_session, difference):
    original = make_report(db_session)
    replacement = make_report(db_session, confirmed=True)
    if difference == "app":
        app = Application(code="other", name="Other")
        db_session.add(app)
        db_session.flush()
        replacement.application_id = app.id
    elif difference == "unknown_app":
        original.application_id = replacement.application_id = None
    elif difference == "group":
        replacement.extraction.normalized_group_id = "gr99.other"
    elif difference == "date":
        replacement.extraction.normalized_date = "2026-09-15"
    elif difference == "sender":
        replacement.sender_phone = "22670000002"
    elif difference == "ambiguous":
        replacement.extraction.date_is_ambiguous = True
    elif difference == "older":
        replacement.received_at = original.received_at - timedelta(seconds=1)
    elif difference == "invalid":
        replacement.extraction.sync_status = "UNCONFIRMED"
    assert not matches(db_session, original, replacement)
