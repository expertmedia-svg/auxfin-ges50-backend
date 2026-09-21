from pydantic import BaseModel


class OverviewStats(BaseModel):
    report_counts: dict[str, int] = {}
    readable: int = 0
    total_evidence: int
    total_images: int
    total_videos: int
    processed: int
    pending: int
    requires_review: int
    failed: int
    conforme: int
    ecarts: int
    echecs_synchronisation: int
    preuves_illisibles: int
    taux_conformite: float
    taux_traitement_automatique: float


class ApplicationStat(BaseModel):
    application_id: str
    application_name: str
    total_evidence: int
    conforme: int
    ecarts: int


class PeriodStat(BaseModel):
    date: str
    count: int


class AnomalyStat(BaseModel):
    status: str
    count: int
