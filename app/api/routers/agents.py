import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session, joinedload

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.deps import require_roles
from app.core.permissions import ADMIN_ROLES, READ_ROLES
from app.models.applications import Agent, AgentGroupAssignment, Application
from app.models.identity import User
from app.schemas.agents import AgentCreate, AgentGroupAssignmentIn, AgentImportReport, AgentOut, AgentUpdate

router = APIRouter(prefix="/agents", tags=["agents"])


def _to_out(agent: Agent) -> AgentOut:
    return AgentOut(
        id=agent.id,
        full_name=agent.full_name,
        whatsapp_phone=agent.whatsapp_phone,
        whatsapp_name=agent.whatsapp_name,
        locality=agent.locality,
        is_active=agent.is_active,
        group_assignments=[
            AgentGroupAssignmentIn(application_id=a.application_id, group_id=a.group_id)
            for a in agent.group_assignments
        ],
    )


def _sync_assignments(db: Session, agent: Agent, assignments: list[AgentGroupAssignmentIn]) -> None:
    db.query(AgentGroupAssignment).filter(AgentGroupAssignment.agent_id == agent.id).delete()
    for item in assignments:
        if db.get(Application, item.application_id) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Application inconnue: {item.application_id}")
        db.add(AgentGroupAssignment(agent_id=agent.id, application_id=item.application_id, group_id=item.group_id))


@router.get("", response_model=list[AgentOut])
def list_agents(
    db: Session = Depends(get_db), _: User = Depends(require_roles(*READ_ROLES))
) -> list[AgentOut]:
    agents = db.query(Agent).options(joinedload(Agent.group_assignments)).order_by(Agent.full_name).all()
    return [_to_out(a) for a in agents]


@router.post("", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
def create_agent(
    payload: AgentCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN_ROLES))
) -> AgentOut:
    agent = Agent(
        full_name=payload.full_name,
        whatsapp_phone=payload.whatsapp_phone,
        whatsapp_name=payload.whatsapp_name,
        locality=payload.locality,
        is_active=payload.is_active,
    )
    db.add(agent)
    db.flush()
    _sync_assignments(db, agent, payload.group_assignments)
    record_audit(db, user_id=user.id, action="agent.create", entity_type="agent", entity_id=agent.id)
    db.commit()
    db.refresh(agent)
    return _to_out(agent)


@router.patch("/{agent_id}", response_model=AgentOut)
def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ADMIN_ROLES)),
) -> AgentOut:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent introuvable")
    for field in ("full_name", "whatsapp_phone", "whatsapp_name", "locality", "is_active"):
        value = getattr(payload, field)
        if value is not None:
            setattr(agent, field, value)
    if payload.group_assignments is not None:
        _sync_assignments(db, agent, payload.group_assignments)
    record_audit(db, user_id=user.id, action="agent.update", entity_type="agent", entity_id=agent.id)
    db.commit()
    db.refresh(agent)
    return _to_out(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_agent(
    agent_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN_ROLES))
) -> None:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent introuvable")
    agent.is_active = False
    record_audit(db, user_id=user.id, action="agent.deactivate", entity_type="agent", entity_id=agent.id)
    db.commit()


@router.post("/import", response_model=AgentImportReport)
def import_agents(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ADMIN_ROLES)),
) -> AgentImportReport:
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Format de fichier non supporte (xlsx, xls, csv)")

    try:
        df = pd.read_csv(file.file) if file.filename.lower().endswith(".csv") else pd.read_excel(file.file)
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Impossible de lire le fichier: {exc}") from exc

    columns_lower = {c.lower().strip(): c for c in df.columns}
    name_col = next((columns_lower[c] for c in columns_lower if "nom" in c or "name" in c), None)
    phone_col = next((columns_lower[c] for c in columns_lower if "phone" in c or "tel" in c or "whatsapp" in c), None)
    locality_col = next((columns_lower[c] for c in columns_lower if "localite" in c or "locality" in c or "zone" in c), None)

    if name_col is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Colonne nom de l'agent introuvable dans le fichier")

    errors: list[str] = []
    imported = 0
    for idx, row in df.iterrows():
        full_name = str(row[name_col]).strip() if pd.notna(row.get(name_col)) else ""
        if not full_name:
            errors.append(f"Ligne {idx + 2}: nom manquant")
            continue
        agent = Agent(
            full_name=full_name,
            whatsapp_phone=str(row[phone_col]).strip() if phone_col and pd.notna(row.get(phone_col)) else None,
            locality=str(row[locality_col]).strip() if locality_col and pd.notna(row.get(locality_col)) else None,
        )
        db.add(agent)
        imported += 1

    record_audit(
        db,
        user_id=user.id,
        action="agent.import",
        details={"total_rows": len(df), "imported": imported, "rejected": len(errors)},
    )
    db.commit()
    return AgentImportReport(total_rows=len(df), imported=imported, rejected=len(errors), errors=errors)
