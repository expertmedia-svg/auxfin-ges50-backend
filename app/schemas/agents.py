from pydantic import BaseModel, Field


class AgentGroupAssignmentIn(BaseModel):
    application_id: str
    group_id: str


class AgentCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    whatsapp_phone: str | None = None
    whatsapp_name: str | None = None
    locality: str | None = None
    is_active: bool = True
    group_assignments: list[AgentGroupAssignmentIn] = Field(default_factory=list)


class AgentUpdate(BaseModel):
    full_name: str | None = None
    whatsapp_phone: str | None = None
    whatsapp_name: str | None = None
    locality: str | None = None
    is_active: bool | None = None
    group_assignments: list[AgentGroupAssignmentIn] | None = None


class AgentOut(BaseModel):
    id: str
    full_name: str
    whatsapp_phone: str | None
    whatsapp_name: str | None
    locality: str | None
    is_active: bool
    group_assignments: list[AgentGroupAssignmentIn]

    model_config = {"from_attributes": True}


class AgentImportReport(BaseModel):
    total_rows: int
    imported: int
    rejected: int
    errors: list[str]
