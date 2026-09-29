from tests.test_evidence_status_and_origin import client, auth_token  # noqa: F401
from tests.test_followups import make_report
from app.models.evidence import EvidenceFile
from app.models.followup import EvidenceFollowup
from app.services.followups import update_followups
from app.services.report_status import report_filters


def test_manual_confirmation_counts_and_closes_followup(db_session, client, auth_token):
    ev = make_report(db_session)
    update_followups(db_session, ev)
    db_session.commit()
    headers = {"Authorization": f"Bearer {auth_token}"}
    response = client.post(f"/api/evidence/{ev.id}/validate", json={"comment": "Coche visible"}, headers=headers)
    assert response.status_code == 204
    db_session.expire_all()
    assert ev.extraction.sync_status == "SUCCESS"
    assert ev.extraction.correction_history[-1]["previous_sync_status"] == "UNCONFIRMED"
    assert db_session.query(EvidenceFile).filter(report_filters()["VALID"]).count() == 1
    assert db_session.query(EvidenceFollowup).one().status == "RESOLVED"
    response = client.post(f"/api/evidence/{ev.id}/reject", json={"comment": "Correction"}, headers=headers)
    assert response.status_code == 204
    assert db_session.query(EvidenceFile).filter(report_filters()["VALID"]).count() == 0
