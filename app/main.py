import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import (
    agents,
    applications,
    audit,
    auth,
    dashboard_imports,
    evidence,
    reconciliation,
    reports,
    statistics,
    system_health,
    users,
    whatsapp,
)
from app.api.routers import (
    settings as settings_router,
)
from app.core.config import get_settings

logging.basicConfig(level=logging.INFO)
settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="API de controle des synchronisations des applications eCoach (GES-G50-SYNC-CONTROL)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(applications.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(settings_router.router, prefix="/api")
app.include_router(evidence.router, prefix="/api")
app.include_router(dashboard_imports.router, prefix="/api")
app.include_router(reconciliation.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(statistics.router, prefix="/api")
app.include_router(system_health.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(whatsapp.router, prefix="/api")


@app.get("/api/health", tags=["system"])
def health() -> dict:
    return {"status": "ok", "service": settings.app_name}
