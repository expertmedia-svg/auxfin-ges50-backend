from datetime import datetime

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: str
    user_id: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    details: dict
    ip_address: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
