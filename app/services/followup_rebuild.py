"""Bulk rebuild without repeated all-pairs database searches; caller commits."""
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime

from app.models.followup import EvidenceFollowup
from app.services.followups import problem_reason, usable, utc_naive
from app.services.operations import OperationQuery, evidence_rows


def rebuild_followups(db, progress=None):
    today = datetime.utcnow().date()
    rows, objects = evidence_rows(db, OperationQuery(dataset="evidence", scope="all", start=today, end=today))
    identities = {r["evidence_id"]: r["sender_identity"] for r in rows}
    def key(ev):
        ex = ev.extraction
        if identities[ev.id] and ev.application_id and ex and ex.effective_group_id and ex.effective_date and not ex.date_is_ambiguous:
            return identities[ev.id], ev.application_id, ex.effective_group_id, ex.effective_date
        return None
    candidates = defaultdict(list)
    for ev in objects.values():
        if usable(ev):
            ev.processing_status = "COMPLETED"
            report = key(ev)
            if report:
                candidates[report].append((utc_naive(ev.received_at), ev.id))
    for values in candidates.values():
        values.sort()
    tasks = {t.evidence_id: t for t in db.query(EvidenceFollowup).all()}
    for number, ev in enumerate(objects.values(), 1):
        task = tasks.get(ev.id)
        if task and task.status == "RESOLVED" and task.replacement_evidence_id:
            replacement = objects.get(task.replacement_evidence_id)
            if replacement and not usable(replacement) and replacement.processing_status not in ("PENDING", "QUEUED", "PROCESSING"):
                task.status = "OPEN"
                task.replacement_evidence_id = None
                task.resolved_at = None
        reason = problem_reason(ev)
        if reason:
            if task is None:
                task = EvidenceFollowup(evidence_id=ev.id, reason=reason, status="OPEN")
                db.add(task)
                tasks[ev.id] = task
            elif task.status != "RESOLVED":
                task.reason = reason
        if task and task.status != "RESOLVED":
            replacement_id = ev.id if usable(ev) else None
            report = key(ev)
            values = candidates.get(report, []) if report else []
            if not replacement_id and values:
                index = bisect_left(values, (utc_naive(ev.received_at), ""))
                if index < len(values):
                    replacement_id = values[index][1]
            if replacement_id:
                task.status = "RESOLVED"
                task.replacement_evidence_id = replacement_id
                task.resolved_at = datetime.utcnow()
        if progress and number % 250 == 0:
            progress(number, len(objects))
    db.flush()
    return len(tasks)
