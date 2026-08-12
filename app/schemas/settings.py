from typing import Any

from pydantic import BaseModel


class SettingItem(BaseModel):
    key: str
    value: Any
    description: str | None = None


class SettingsUpdate(BaseModel):
    values: dict[str, Any]
