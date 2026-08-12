from pydantic import BaseModel, Field


class ApplicationProfileIn(BaseModel):
    expected_evidence_type: str = Field(default="video", pattern="^(image|video)$")
    id_regex: str = r"gr\d+\.[a-z0-9\-]+"
    screen_zones: dict = Field(default_factory=dict)
    success_keywords: list[str] = Field(default_factory=list)
    error_keywords: list[str] = Field(default_factory=list)
    date_format_hints: list[str] = Field(default_factory=list)
    logo_keywords: list[str] = Field(default_factory=list)
    primary_color_hint: str | None = None
    video_start_offsets_seconds: list[float] | None = None
    video_end_offsets_seconds: list[float] | None = None
    is_active: bool = True


class ApplicationProfileOut(ApplicationProfileIn):
    id: str
    application_id: str

    model_config = {"from_attributes": True}


class ApplicationCreate(BaseModel):
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=2, max_length=150)
    is_active: bool = True
    profile: ApplicationProfileIn = Field(default_factory=ApplicationProfileIn)


class ApplicationUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None
    profile: ApplicationProfileIn | None = None


class ApplicationOut(BaseModel):
    id: str
    code: str
    name: str
    is_active: bool
    profile: ApplicationProfileOut | None = None

    model_config = {"from_attributes": True}
