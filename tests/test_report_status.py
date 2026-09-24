from app.models.evidence import EvidenceFile
from app.services.report_status import report_filters
from app.services.followups import usable
from tests.test_followups import make_report


def test_exclusive_categories_match_validation(db_session):
    valid = make_report(db_session, confirmed=True)
    review = make_report(db_session, confirmed=True)
    review.extraction.date_is_ambiguous = True
    waiting = make_report(db_session)
    waiting.processing_status = "QUEUED"
    duplicate = make_report(db_session, confirmed=True)
    duplicate.is_duplicate_of_id = valid.id
    bad = make_report(db_session)
    bad.processing_status = "FAILED"
    db_session.commit()
    groups = {key: {ev.id for ev in db_session.query(EvidenceFile).filter(rule)}
              for key, rule in report_filters().items()}
    assert groups == {"SYNC_VISIBLE": {valid.id, review.id}, "SYNC_REVIEW": set(), "VALID": {valid.id, review.id}, "NOT_VALIDATED": {bad.id},
                      "PENDING": {waiting.id}, "DUPLICATE": {duplicate.id}}
    assert groups["VALID"] == {ev.id for ev in db_session.query(EvidenceFile) if usable(ev)}


def test_success_with_ambiguous_metadata_closes_own_followup(db_session):
    from app.services.followups import update_followups
    from app.models.followup import EvidenceFollowup
    ev = make_report(db_session)
    update_followups(db_session, ev)
    db_session.commit()
    ev.extraction.sync_status = "SUCCESS"
    ev.extraction.date_is_ambiguous = True
    ev.extraction.requires_manual_review = True
    ev.extraction.normalized_date = None
    update_followups(db_session, ev)
    db_session.commit()
    assert usable(ev)
    assert db_session.query(EvidenceFollowup).one().status == "RESOLVED"
    assert ev.extraction.date_is_ambiguous
