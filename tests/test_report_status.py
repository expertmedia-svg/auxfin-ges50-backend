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
    assert groups == {"VALID": {valid.id}, "NOT_VALIDATED": {review.id, bad.id},
                      "PENDING": {waiting.id}, "DUPLICATE": {duplicate.id}}
    assert groups["VALID"] == {ev.id for ev in db_session.query(EvidenceFile) if usable(ev)}
