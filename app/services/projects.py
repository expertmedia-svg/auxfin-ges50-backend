from collections import defaultdict
from datetime import datetime, time, timedelta
from sqlalchemy.orm import joinedload
from app.models.evidence import EvidenceFile
from app.models.whatsapp import WhatsAppMessage
from app.models.projects import ProjectExpectedGroup, ProjectGroup
from app.models.applications import Application
from app.services.followups import usable


def business_key(value):
    return str(value or '').strip().casefold()


def project_dashboard(db, project_id, start, end, cadence, application_id=None):
    expected = db.query(ProjectExpectedGroup).filter_by(project_id=project_id)
    if application_id:
        expected = expected.filter_by(application_id=application_id)
    expected = expected.all()
    evidence_ids = (db.query(WhatsAppMessage.evidence_id).join(ProjectGroup, ProjectGroup.group_id == WhatsAppMessage.group_id)
                    .filter(ProjectGroup.project_id == project_id))
    query = db.query(EvidenceFile).options(joinedload(EvidenceFile.extraction)).filter(
        EvidenceFile.id.in_(evidence_ids), EvidenceFile.received_at >= datetime.combine(start, time.min),
        EvidenceFile.received_at < datetime.combine(end + timedelta(days=1), time.min))
    if application_id:
        query = query.filter(EvidenceFile.application_id == application_id)
    files = query.all()
    buckets = []
    cursor = start
    while cursor <= end:
        finish = end if cadence == 'period' else min(end, cursor + timedelta(days=6 if cadence == 'weekly' else 0))
        buckets.append((cursor, finish))
        cursor = finish + timedelta(days=1)
    apps = {a.id: a.name for a in db.query(Application).all()}
    indexed = defaultdict(list)
    unknown = 0
    duplicate = 0
    app_counts = defaultdict(lambda: {'received': 0, 'valid': 0, 'duplicates': 0})
    for ev in files:
        stats = app_counts[ev.application_id]
        stats['received'] += 1
        if ev.is_duplicate_of_id or ev.processing_status == 'DUPLICATE':
            duplicate += 1
            stats['duplicates'] += 1
            continue
        if usable(ev):
            stats['valid'] += 1
        group = business_key(ev.extraction.effective_group_id) if ev.extraction else ''
        if not group or not ev.application_id:
            unknown += 1
            continue
        indexed[(ev.application_id, group, ev.received_at.date())].append(ev)
    rows = []
    for item in expected:
        for first, last in buckets:
            matched = []
            day = first
            while day <= last:
                matched.extend(indexed.get((item.application_id, item.business_id, day), []))
                day += timedelta(days=1)
            rows.append({'business_id': item.business_id, 'application': apps.get(item.application_id),
                         'start': str(first), 'end': str(last), 'received': len(matched),
                         'valid': sum(usable(ev) for ev in matched),
                         'status': 'MISSING' if not matched else 'VALID' if any(usable(ev) for ev in matched) else 'RECEIVED_NOT_VALIDATED',
                         'evidence_ids': [ev.id for ev in matched]})
    return {'received': len(files), 'valid': sum(v['valid'] for v in app_counts.values()),
            'duplicates': duplicate, 'unidentified': unknown, 'expected': len(rows),
            'missing': sum(r['status'] == 'MISSING' for r in rows), 'rows': rows,
            'by_application': [{'application': apps.get(k, 'Application inconnue'), **v} for k, v in app_counts.items()],
            'basis': 'Date de réception UTC ; listes et rattachements actuels. Les doublons ne couvrent pas un attendu.'}
