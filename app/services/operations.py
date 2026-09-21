"""Lectures métier partagées par le contrôle, les exports et l'assistant.

Les chiffres sont calculés en Python/SQLAlchemy, jamais inventés par le modèle.
"""
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import joinedload

from app.models.applications import Agent, AgentGroupAssignment
from app.models.dashboard import DashboardImportRow
from app.models.evidence import EvidenceFile
from app.models.followup import EvidenceFollowup, FollowupMessage
from app.services.followups import report_key, same_sender, sender_identity, usable, utc_naive


class OperationQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset: Literal["coverage", "followups", "evidence"] = "coverage"
    scope: Literal["all", "selected"] = "selected"
    start: date
    end: date
    cadence: Literal["daily", "period"] = "daily"
    application: str = Field(default="", max_length=150)
    agent: str = Field(default="", max_length=200)
    group: str = Field(default="", max_length=200)
    locality: str = Field(default="", max_length=150)
    status: str = Field(default="", max_length=50)

    @model_validator(mode="after")
    def period_valid(self):
        if self.dataset == "coverage" and self.scope == "all":
            raise ValueError("Les rapports attendus nécessitent une période sélectionnée.")
        if self.end < self.start or (self.end - self.start).days > 92:
            raise ValueError("Choisissez une période ordonnée de 93 jours maximum.")
        return self


def phone_key(value):
    if not value or "@" in value:
        return None  # Un LID WhatsApp n'est pas un numéro de téléphone.
    digits = re.sub(r"[\s+().-]", "", value)
    return digits if re.fullmatch(r"\d{8,15}", digits) else None


def evidence_rows(db, query):
    agents = db.query(Agent).all()
    by_id = {a.id: a for a in agents}
    by_phone = defaultdict(list)
    for agent in agents:
        if phone_key(agent.whatsapp_phone):
            by_phone[phone_key(agent.whatsapp_phone)].append(agent)
    rows, objects = [], {}
    # Pas de limite silencieuse : l'export et le tableau utilisent le même jeu.
    evidences = db.query(EvidenceFile).options(joinedload(EvidenceFile.extraction), joinedload(EvidenceFile.application))
    for ev in evidences:
        ex = ev.extraction
        day = ex.effective_date if ex else None
        basis = "report_date"
        if not day or (ex and ex.date_is_ambiguous):
            day = utc_naive(ev.received_at).date().isoformat()
            basis = "received_at_unverified"
        if query.scope != "all" and not query.start.isoformat() <= day <= query.end.isoformat():
            continue
        agent = by_id.get(ev.agent_id)
        candidates = by_phone.get(phone_key(ev.sender_phone), [])
        if agent is None and len(candidates) == 1:
            agent = candidates[0]
        if agent is None:
            agent = by_id.get(sender_identity(db, ev))
        state = ("DUPLICATE" if ev.is_duplicate_of_id or ev.processing_status == "DUPLICATE" else
                 "SYNCHRONIZED" if usable(ev) else
                 "PENDING" if ev.processing_status in ("PENDING", "QUEUED", "PROCESSING") else
                 "FAILED" if ex and ex.sync_status == "FAILED" else
                 "REVIEW" if ex and ex.sync_status == "SUCCESS" else "UNCONFIRMED")
        rows.append({
            "evidence_id": ev.id, "agent_id": agent.id if agent else None,
            "agent": agent.full_name if agent else ev.sender_name or "Agent non identifié",
            "identity_source": "registry" if agent else "sender_unverified",
            "locality": agent.locality if agent else None,
            "application_id": ev.application_id,
            "application": ev.application.name if ev.application else "Application inconnue",
            "group": ex.effective_group_id if ex else None,
            "date": day, "date_basis": basis, "received_at": ev.received_at.isoformat(),
            "status": state, "sync_status": ex.sync_status if ex else "UNCONFIRMED",
            "processing_status": ev.processing_status,
            "sender_identity": sender_identity(db, ev),
            "evidence_text": ex.sync_status_evidence_text if ex else None,
            "requires_review": ex.requires_manual_review if ex else True,
        })
        objects[ev.id] = ev
    return rows, objects


def _filter(rows, query):
    return [r for r in rows if all(not getattr(query, k) or getattr(query, k).casefold() in str(r.get(k) or "").casefold()
                                  for k in ("application", "agent", "group", "locality"))
            and (not query.status or r.get("status") == query.status
                 or (query.status == "TO_REVIEW" and r.get("processing_status") == "REQUIRES_REVIEW")
                 or (query.status == "NOT_VALIDATED" and r.get("status") in ("REVIEW", "FAILED", "UNCONFIRMED")))]


def operational_data(db, query: OperationQuery):
    evidence, objects = evidence_rows(db, query)
    warnings = []
    coverage_available = True
    if query.dataset == "evidence":
        rows = evidence
    elif query.dataset == "followups":
        rows = []
        indexed = {e["evidence_id"]: e for e in evidence}
        messages = defaultdict(list)
        for m in db.query(FollowupMessage).order_by(FollowupMessage.created_at, FollowupMessage.id):
            messages[m.followup_id].append(m)
        groups = {}
        tasks = db.query(EvidenceFollowup).order_by(EvidenceFollowup.created_at, EvidenceFollowup.id).all()
        for task in tasks:
            if task.evidence_id not in indexed:
                continue
            original = objects[task.evidence_id]
            key = report_key(db, original) or (task.id,)
            groups.setdefault(key, []).append(task)
        for tasks in groups.values():
            tasks.sort(key=lambda t: (utc_naive(objects[t.evidence_id].received_at), t.id))
            task = tasks[0]
            original = objects[task.evidence_id]
            row = dict(indexed[task.evidence_id])
            history = sorted([m for t in tasks for m in messages[t.id]], key=lambda m: utc_naive(m.created_at))
            # Une réception est une preuve de retour, pas nécessairement une correction valide.
            returned = [e for e in objects.values() if e.id != original.id and not e.is_duplicate_of_id
                        and utc_naive(e.received_at) > utc_naive(original.received_at)
                        and history and utc_naive(e.received_at) > utc_naive(history[0].created_at)
                        and same_sender(db, original, e) and report_key(db, original)
                        and report_key(db, original) == report_key(db, e)]
            resolved = next((t for t in tasks if t.status == "RESOLVED"), None)
            row.update({"followup_id": task.id, "related_followup_ids": [t.id for t in tasks],
                        "reason": task.reason, "status": "RESOLVED" if resolved else
                        "RETURNED_INVALID" if returned else "WAITING" if history else "OPEN",
                        "returned_count": len(returned), "attempt_count": len(history),
                        "last_send_status": history[-1].status if history else None,
                        "uncertain_send": any(m.status in ("UNKNOWN", "SENDING") for m in history),
                        "replacement_evidence_id": resolved.replacement_evidence_id if resolved else None})
            rows.append(row)
        warnings.append("Retour après relance rapproché uniquement si agent, application, groupe et date concordent. "
                        "Les autres retours restent à vérifier.")
    else:
        assignments = db.query(AgentGroupAssignment).options(joinedload(AgentGroupAssignment.agent),
                                                            joinedload(AgentGroupAssignment.application)).all()
        assignments = [a for a in assignments if a.agent.is_active and a.application.is_active]
        days = ([query.start + timedelta(days=i) for i in range((query.end - query.start).days + 1)]
                if query.cadence == "daily" else [query.start])
        if len(assignments) * len(days) > 20000:
            raise ValueError("Plus de 20 000 contrôles attendus : réduisez la période.")
        index = defaultdict(list)
        for ev in evidence:
            if ev["status"] != "DUPLICATE" and ev["date_basis"] == "report_date":
                index[ev["agent_id"], ev["application_id"], ev["group"]].append(ev)
        dashboard = defaultdict(set)
        for dr in db.query(DashboardImportRow).options(joinedload(DashboardImportRow.dashboard_import)).filter_by(
                is_valid=True, is_duplicate=False):
            if dr.dashboard_import.status == "COMPLETED":
                dashboard[dr.dashboard_import.application_id, dr.normalized_group_id].add(dr.sync_date)
        rows = []
        for assignment in assignments:
            found = index[assignment.agent_id, assignment.application_id, assignment.group_id]
            for day in days:
                matching = [e for e in found if query.cadence == "period" or e["date"] == day.isoformat()]
                priority = {"SYNCHRONIZED": 0, "REVIEW": 1, "PENDING": 2, "FAILED": 3, "UNCONFIRMED": 4}
                best = min(matching, key=lambda e: priority[e["status"]]) if matching else None
                rows.append({"agent_id": assignment.agent_id, "agent": assignment.agent.full_name,
                             "locality": assignment.agent.locality, "application": assignment.application.name,
                             "group": assignment.group_id, "date": day.isoformat(),
                             "period_end": query.end.isoformat() if query.cadence == "period" else day.isoformat(),
                             "status": best["status"] if best else "MISSING",
                             "evidence_id": best["evidence_id"] if best else None,
                             "submission_count": len(matching),
                             "dashboard_present": bool(best and best["date"] in dashboard[
                                 assignment.application_id, assignment.group_id])})
        warnings.extend([
            "Attendus calculés sur les affectations actives actuelles ; pas de calendrier historique des affectations.",
            "Une date ambiguë ou un agent inconnu empêche le rapprochement. MISSING signifie aucune preuve attribuable.",
            "Présence dashboard = ligne dans un import terminé, pas une vérification en temps réel du système principal.",
        ])
        if not assignments:
            coverage_available = False
            warnings.append("Aucune affectation active : impossible de déterminer qui devait transmettre un rapport.")
    rows = _filter(rows, query)
    if len(rows) > 20000:
        raise ValueError("Plus de 20 000 lignes : affinez les filtres.")
    return {"query": query.model_dump(mode="json"), "total": len(rows),
            "coverage_available": coverage_available,
            "registered_agents_count": len({r["agent_id"] for r in rows if r.get("agent_id")}),
            "unregistered_contacts_count": len({r["sender_identity"] for r in rows
                                                 if not r.get("agent_id") and r.get("sender_identity")}),
            "unknown_sender_reports_count": sum(not r.get("agent_id") and not r.get("sender_identity") for r in rows),
            "review_queue_count": sum(r.get("processing_status") == "REQUIRES_REVIEW" for r in rows),
            "counts": dict(Counter(r["status"] for r in rows)), "rows": rows, "warnings": warnings,
            "unattributed_evidence_count": sum(not r["agent_id"] or r["date_basis"] != "report_date" for r in evidence)}
