import enum


class EvidenceType(str, enum.Enum):
    IMAGE = "image"
    VIDEO = "video"


class EvidenceSource(str, enum.Enum):
    MANUAL_UPLOAD = "manual_upload"
    WHATSAPP_EXPORT = "whatsapp_export"
    FOLDER_WATCH = "folder_watch"
    WHATSAPP_GATEWAY = "whatsapp_gateway"


class ProcessingStatus(str, enum.Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"
    DUPLICATE = "DUPLICATE"


class WhatsAppConnectionState(str, enum.Enum):
    DISCONNECTED = "DISCONNECTED"
    QR_PENDING = "QR_PENDING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    ERROR = "ERROR"


class WhatsAppMessageType(str, enum.Enum):
    IMAGE = "image"
    VIDEO = "video"
    OTHER = "other"


class WhatsAppDownloadStatus(str, enum.Enum):
    PENDING = "PENDING"
    DOWNLOADING = "DOWNLOADING"
    DOWNLOADED = "DOWNLOADED"
    FAILED = "FAILED"
    SKIPPED_NO_MEDIA = "SKIPPED_NO_MEDIA"
    SKIPPED_UNAUTHORIZED_GROUP = "SKIPPED_UNAUTHORIZED_GROUP"


class SyncStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    UNCONFIRMED = "UNCONFIRMED"


class JobType(str, enum.Enum):
    IMAGE_OCR = "image_ocr"
    VIDEO_ANALYSIS = "video_analysis"
    EXCEL_IMPORT = "excel_import"
    RECONCILIATION = "reconciliation"
    REPORT_GENERATION = "report_generation"


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ReconciliationStatus(str, enum.Enum):
    CONFORME = "CONFORME"
    DECLARE_WHATSAPP_ABSENT_DASHBOARD = "DECLARE_WHATSAPP_ABSENT_DASHBOARD"
    DASHBOARD_SANS_PREUVE_WHATSAPP = "DASHBOARD_SANS_PREUVE_WHATSAPP"
    ECART_DATE = "ECART_DATE"
    DOUBLON_WHATSAPP = "DOUBLON_WHATSAPP"
    DOUBLON_DASHBOARD = "DOUBLON_DASHBOARD"
    ID_ILLISIBLE = "ID_ILLISIBLE"
    DATE_ILLISIBLE = "DATE_ILLISIBLE"
    SYNCHRONISATION_NON_CONFIRMEE = "SYNCHRONISATION_NON_CONFIRMEE"
    ECHEC_SYNCHRONISATION = "ECHEC_SYNCHRONISATION"
    ID_INCONNU = "ID_INCONNU"
    MAUVAISE_APPLICATION = "MAUVAISE_APPLICATION"
    VERIFICATION_MANUELLE = "VERIFICATION_MANUELLE"


class ManualReviewDecision(str, enum.Enum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class ReportType(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"


class ReportFormat(str, enum.Enum):
    XLSX = "xlsx"
    CSV = "csv"
    PDF = "pdf"
