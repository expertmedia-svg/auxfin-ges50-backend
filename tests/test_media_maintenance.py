import pytest
from datetime import datetime, timedelta
from app.services.media_maintenance import maintenance
from app.models.evidence import EvidenceFile
from app.models.followup import EvidenceFollowup
from tests.test_followups import make_report


def test_retention_preserves_stats_and_recent_files(db_session, tmp_path):
    old = make_report(db_session, confirmed=True)
    old.received_at = datetime.utcnow() - timedelta(days=15)
    old.storage_path = 'uploads/old.mp4'
    new = make_report(db_session)
    new.storage_path = 'uploads/new.mp4'
    (tmp_path / 'uploads').mkdir()
    for name in ('old.mp4', 'new.mp4'):
        (tmp_path / 'uploads' / name).write_bytes(b'video')
    db_session.commit()
    assert maintenance(db_session, tmp_path)['files'] == 1
    assert (tmp_path / old.storage_path).exists()
    maintenance(db_session, tmp_path, execute=True)
    assert not (tmp_path / old.storage_path).exists()
    assert (tmp_path / new.storage_path).exists()
    assert db_session.query(EvidenceFile).count() == 2
    assert old.extraction.sync_status == 'SUCCESS'


def test_reset_removes_reports_and_followups(db_session, tmp_path):
    ev = make_report(db_session)
    ev.storage_path = 'uploads/x.mp4'
    db_session.add(EvidenceFollowup(evidence_id=ev.id, reason='test'))
    db_session.commit()
    maintenance(db_session, tmp_path, reset=True, execute=True)
    assert db_session.query(EvidenceFile).count() == 0
    assert db_session.query(EvidenceFollowup).count() == 0


def test_refuse_outside_root(db_session, tmp_path):
    ev = make_report(db_session)
    ev.storage_path = '../outside.mp4'
    db_session.commit()
    with pytest.raises(ValueError):
        maintenance(db_session, tmp_path, reset=True, execute=True)
    assert db_session.query(EvidenceFile).count() == 1


def test_pending_and_shared_path_protected(db_session, tmp_path):
    old = make_report(db_session)
    old.received_at = datetime.utcnow() - timedelta(days=20)
    old.storage_path = 'uploads/shared.mp4'
    pending = make_report(db_session)
    pending.processing_status = 'PENDING'
    pending.received_at = old.received_at
    pending.storage_path = old.storage_path
    (tmp_path / 'uploads').mkdir()
    (tmp_path / old.storage_path).write_bytes(b'video')
    db_session.commit()
    result = maintenance(db_session, tmp_path, execute=True)
    assert result['protected_reports'] == 1
    assert result['files'] == 0
    assert (tmp_path / old.storage_path).exists()
