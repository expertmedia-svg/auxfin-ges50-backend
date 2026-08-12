from datetime import datetime

from pydantic import BaseModel


class WhatsAppStatusWebhookIn(BaseModel):
    connection_state: str
    qr_data_url: str | None = None
    phone_number: str | None = None
    display_name: str | None = None
    last_error: str | None = None
    connected_at: datetime | None = None


class WhatsAppMessageWebhookIn(BaseModel):
    whatsapp_message_id: str
    group_external_id: str
    group_name: str | None = None
    sender_external_id: str | None = None
    sender_name: str | None = None
    sender_phone: str | None = None
    message_date: datetime
    message_type: str
    caption_text: str | None = None
    media_external_id: str | None = None
    media_filename: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    sha256: str | None = None
    storage_path: str | None = None
    download_status: str
    last_error: str | None = None


class WhatsAppGatewayStatusOut(BaseModel):
    connection_state: str
    phone_number: str | None
    display_name: str | None
    last_heartbeat_at: datetime | None
    last_error: str | None
    connected_at: datetime | None

    model_config = {"from_attributes": True}


class WhatsAppGroupOut(BaseModel):
    id: str
    whatsapp_group_external_id: str
    name: str
    is_monitored: bool
    application_id: str | None
    supervisor_id: str | None
    zone_label: str | None
    last_activity_at: datetime | None
    media_received_today: int = 0
    error_count: int = 0

    model_config = {"from_attributes": True}


class WhatsAppGroupUpdate(BaseModel):
    is_monitored: bool | None = None
    application_id: str | None = None
    supervisor_id: str | None = None
    zone_label: str | None = None


class WhatsAppMessageOut(BaseModel):
    id: str
    whatsapp_message_id: str
    group_id: str | None
    group_external_id: str
    sender_name: str | None
    sender_phone: str | None
    message_date: datetime
    message_type: str
    media_filename: str | None
    download_status: str
    evidence_id: str | None
    retry_count: int
    last_error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class WhatsAppQueueSummary(BaseModel):
    pending: int
    downloading: int
    processing: int
    failed: int
    unassigned: int
