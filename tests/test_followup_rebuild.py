from app.services.followup_rebuild import rebuild_followups
from app.models.followup import EvidenceFollowup
from tests.test_followups import make_report


def test_bulk_rebuild_success_ambiguity_and_idempotence(db_session):
    original = make_report(db_session)
    replacement = make_report(db_session, confirmed=True)
    ambiguous = make_report(db_session, group="gr2.test")
    ambiguous.extraction.date_is_ambiguous = True
    db_session.commit()
    rebuild_followups(db_session)
    db_session.commit()
    task = db_session.query(EvidenceFollowup).filter_by(evidence_id=original.id).one()
    assert task.status == "RESOLVED"
    assert task.replacement_evidence_id == replacement.id
    task2 = db_session.query(EvidenceFollowup).filter_by(evidence_id=ambiguous.id).one()
    assert task2.status == "OPEN"
    ambiguous.extraction.sync_status = "SUCCESS"
    db_session.commit()
    rebuild_followups(db_session)
    db_session.commit()
    assert task2.status == "RESOLVED"
    assert ambiguous.extraction.date_is_ambiguous
    rebuild_followups(db_session)
    db_session.commit()
    assert db_session.query(EvidenceFollowup).count() == 2
