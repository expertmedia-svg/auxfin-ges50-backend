from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_roles
from app.core.permissions import READ_ROLES
from app.models.applications import Application
from app.models.enums import EvidenceType, ProcessingStatus, ReconciliationStatus
from app.models.evidence import EvidenceFile
from app.models.identity import User
from app.models.reconciliation import ReconciliationResult, ReconciliationRun
from app.schemas.statistics import AnomalyStat, ApplicationStat, OverviewStats, PeriodStat

router = APIRouter(prefix="/statistics", tags=["statistics"])

_ANOMALY_STATUSES = [
    ReconciliationStatus.DECLARE_WHATSAPP_ABSENT_DASHBOARD,
    ReconciliationStatus.DASHBOARD_SANS_PREUVE_WHATSAPP,
    ReconciliationStatus.ECART_DATE,
    ReconciliationStatus.DOUBLON_WHATSAPP,
    ReconciliationStatus.DOUBLON_DASHBOARD,
    ReconciliationStatus.ID_ILLISIBLE,
    ReconciliationStatus.DATE_ILLISIBLE,
    ReconciliationStatus.SYNCHRONISATION_NON_CONFIRMEE,
    ReconciliationStatus.ECHEC_SYNCHRONISATION,
    ReconciliationStatus.ID_INCONNU,
    ReconciliationStatus.MAUVAISE_APPLICATION,
    ReconciliationStatus.VERIFICATION_MANUELLE,
]


def _latest_run(db: Session) -> ReconciliationRun | None:
    return db.query(ReconciliationRun).filter(ReconciliationRun.status == "COMPLETED").order_by(
        ReconciliationRun.finished_at.desc()
    ).first()


def _period_bounds(period_start: str | None, period_end: str | None) -> tuple[datetime | None, datetime | None]:
    """Convertit des dates 'YYYY-MM-DD' en bornes datetime inclusives
    (debut de journee / fin de journee), en UTC comme EvidenceFile.received_at."""
    start = datetime.combine(date.fromisoformat(period_start), datetime.min.time(), tzinfo=UTC) if period_start else None
    end = (
        datetime.combine(date.fromisoformat(period_end), datetime.min.time(), tzinfo=UTC) + timedelta(days=1)
        if period_end
        else None
    )
    return start, end


def _apply_period(query, column, start: datetime | None, end: datetime | None):
    if start is not None:
        query = query.filter(column >= start)
    if end is not None:
        query = query.filter(column < end)
    return query


PeriodStartParam = Query(default=None, description="Debut de periode (YYYY-MM-DD), inclus")
PeriodEndParam = Query(default=None, description="Fin de periode (YYYY-MM-DD), inclus")


@router.get("/overview", response_model=OverviewStats)
def overview(
    period_start: str | None = PeriodStartParam,
    period_end: str | None = PeriodEndParam,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*READ_ROLES)),
) -> OverviewStats:
    start, end = _period_bounds(period_start, period_end)
    has_period = start is not None or end is not None

    def count_evidence(*filters):
        query = db.query(func.count(EvidenceFile.id))
        query = _apply_period(query, EvidenceFile.received_at, start, end)
        for f in filters:
            query = query.filter(f)
        return query.scalar() or 0

    total_evidence = count_evidence()
    total_images = count_evidence(EvidenceFile.media_type == EvidenceType.IMAGE)
    total_videos = count_evidence(EvidenceFile.media_type == EvidenceType.VIDEO)
    processed = count_evidence(EvidenceFile.processing_status == ProcessingStatus.COMPLETED)
    pending = count_evidence(
        EvidenceFile.processing_status.in_([ProcessingStatus.PENDING, ProcessingStatus.QUEUED, ProcessingStatus.PROCESSING])
    )
    requires_review = count_evidence(EvidenceFile.processing_status == ProcessingStatus.REQUIRES_REVIEW)
    failed = count_evidence(EvidenceFile.processing_status == ProcessingStatus.FAILED)

    run = _latest_run(db)
    conforme = ecarts = echecs = illisibles = 0
    total_reconciled = 0
    if run and not has_period:
        summary = run.summary or {}
        conforme = summary.get(ReconciliationStatus.CONFORME.value, 0)
        ecarts = summary.get(ReconciliationStatus.ECART_DATE.value, 0)
        echecs = summary.get(ReconciliationStatus.ECHEC_SYNCHRONISATION.value, 0)
        illisibles = summary.get(ReconciliationStatus.ID_ILLISIBLE.value, 0) + summary.get(
            ReconciliationStatus.DATE_ILLISIBLE.value, 0
        )
        total_reconciled = sum(summary.values())
    elif run and has_period:
        # Les resultats sans preuve WhatsApp associee (ex. DASHBOARD_SANS_PREUVE_WHATSAPP)
        # n'ont pas de date de reception a filtrer : ils sont exclus des stats par periode.
        status_query = _apply_period(
            db.query(ReconciliationResult.status, func.count(ReconciliationResult.id))
            .join(EvidenceFile, ReconciliationResult.evidence_id == EvidenceFile.id)
            .filter(ReconciliationResult.run_id == run.id),
            EvidenceFile.received_at,
            start,
            end,
        ).group_by(ReconciliationResult.status)
        counts = {status.value if hasattr(status, "value") else status: c for status, c in status_query.all()}
        conforme = counts.get(ReconciliationStatus.CONFORME.value, 0)
        ecarts = counts.get(ReconciliationStatus.ECART_DATE.value, 0)
        echecs = counts.get(ReconciliationStatus.ECHEC_SYNCHRONISATION.value, 0)
        illisibles = counts.get(ReconciliationStatus.ID_ILLISIBLE.value, 0) + counts.get(
            ReconciliationStatus.DATE_ILLISIBLE.value, 0
        )
        total_reconciled = sum(counts.values())

    taux_conformite = round((conforme / total_reconciled) * 100, 1) if total_reconciled else 0.0
    taux_traitement = round((processed / total_evidence) * 100, 1) if total_evidence else 0.0

    return OverviewStats(
        total_evidence=total_evidence,
        total_images=total_images,
        total_videos=total_videos,
        processed=processed,
        pending=pending,
        requires_review=requires_review,
        failed=failed,
        conforme=conforme,
        ecarts=ecarts,
        echecs_synchronisation=echecs,
        preuves_illisibles=illisibles,
        taux_conformite=taux_conformite,
        taux_traitement_automatique=taux_traitement,
    )


@router.get("/by-application", response_model=list[ApplicationStat])
def by_application(
    period_start: str | None = PeriodStartParam,
    period_end: str | None = PeriodEndParam,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*READ_ROLES)),
) -> list[ApplicationStat]:
    start, end = _period_bounds(period_start, period_end)
    applications = db.query(Application).all()
    run = _latest_run(db)
    results: list[ApplicationStat] = []
    for app in applications:
        total_query = _apply_period(
            db.query(func.count(EvidenceFile.id)).filter(EvidenceFile.application_id == app.id),
            EvidenceFile.received_at,
            start,
            end,
        )
        total = total_query.scalar() or 0
        conforme = ecarts = 0
        if run:
            base_query = (
                db.query(ReconciliationResult.status, func.count(ReconciliationResult.id))
                .join(EvidenceFile, ReconciliationResult.evidence_id == EvidenceFile.id)
                .filter(ReconciliationResult.run_id == run.id, ReconciliationResult.application_id == app.id)
            )
            base_query = _apply_period(base_query, EvidenceFile.received_at, start, end)
            rows = base_query.group_by(ReconciliationResult.status).all()
            counts = {status.value if hasattr(status, "value") else status: c for status, c in rows}
            conforme = counts.get(ReconciliationStatus.CONFORME.value, 0)
            ecarts = counts.get(ReconciliationStatus.ECART_DATE.value, 0)
        results.append(
            ApplicationStat(
                application_id=app.id,
                application_name=app.name,
                total_evidence=total,
                conforme=conforme,
                ecarts=ecarts,
            )
        )
    return results


# Fenetre par defaut selon la granularite, si le client ne fixe pas `days`
# explicitement : ~30 jours, ~13 semaines, ~12 mois.
_DEFAULT_WINDOW_DAYS = {"day": 30, "week": 91, "month": 365}


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())  # lundi de la semaine ISO


@router.get("/by-period", response_model=list[PeriodStat])
def by_period(
    granularity: str = Query(default="day", pattern="^(day|week|month)$"),
    days: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*READ_ROLES)),
) -> list[PeriodStat]:
    window = days if days is not None else _DEFAULT_WINDOW_DAYS[granularity]
    since = datetime.now(UTC) - timedelta(days=window)

    # Agregation par jour calendaire toujours cote SQL (portable SQLite/Postgres
    # via func.date()), puis regroupement semaine/mois fait en Python : les
    # fonctions de troncature de date different trop entre dialectes pour s'y fier.
    rows = (
        db.query(func.date(EvidenceFile.received_at), func.count(EvidenceFile.id))
        .filter(EvidenceFile.received_at >= since)
        .group_by(func.date(EvidenceFile.received_at))
        .order_by(func.date(EvidenceFile.received_at))
        .all()
    )

    if granularity == "day":
        return [PeriodStat(date=str(d), count=c) for d, c in rows]

    buckets: dict[str, int] = defaultdict(int)
    for raw_day, count in rows:
        day_value = raw_day if isinstance(raw_day, date) else date.fromisoformat(str(raw_day))
        if granularity == "week":
            key = _week_start(day_value).isoformat()
        else:  # month
            key = f"{day_value.year:04d}-{day_value.month:02d}"
        buckets[key] += count

    return [PeriodStat(date=key, count=buckets[key]) for key in sorted(buckets)]


@router.get("/anomalies", response_model=list[AnomalyStat])
def anomalies(
    period_start: str | None = PeriodStartParam,
    period_end: str | None = PeriodEndParam,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*READ_ROLES)),
) -> list[AnomalyStat]:
    run = _latest_run(db)
    if not run:
        return []
    start, end = _period_bounds(period_start, period_end)
    if start is None and end is None:
        summary = run.summary or {}
        return [
            AnomalyStat(status=status.value, count=summary.get(status.value, 0))
            for status in _ANOMALY_STATUSES
            if summary.get(status.value, 0) > 0
        ]

    # Filtre par periode : uniquement les anomalies rattachees a une preuve
    # WhatsApp (evidence_id non nul) — les anomalies purement cote dashboard
    # (ex. DASHBOARD_SANS_PREUVE_WHATSAPP) n'ont pas de date de reception.
    query = _apply_period(
        db.query(ReconciliationResult.status, func.count(ReconciliationResult.id))
        .join(EvidenceFile, ReconciliationResult.evidence_id == EvidenceFile.id)
        .filter(ReconciliationResult.run_id == run.id),
        EvidenceFile.received_at,
        start,
        end,
    ).group_by(ReconciliationResult.status)
    counts = {status.value if hasattr(status, "value") else status: c for status, c in query.all()}
    return [
        AnomalyStat(status=status.value, count=counts.get(status.value, 0))
        for status in _ANOMALY_STATUSES
        if counts.get(status.value, 0) > 0
    ]
