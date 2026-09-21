from types import SimpleNamespace
from app.services.reminder_media import reference_images


def test_reference_caption_and_missing_file(tmp_path, monkeypatch):
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"example-image")
    monkeypatch.setattr("app.services.reminder_media.get_storage_service",
                        lambda: SimpleNamespace(resolve=lambda path: image))
    task = SimpleNamespace(id="reference", reason="Date illisible")
    evidence = SimpleNamespace(frames=[], media_type="image", storage_path="image",
                               original_filename="photo.jpg")
    result = reference_images([(task, evidence)])
    assert len(result) == 1
    assert "reference" in result[0]['caption']
    assert "Date illisible" in result[0]['caption']
    image.unlink()
    assert reference_images([(task, evidence)]) == []


def test_readability_does_not_require_synchronization(db_session):
    from app.models.evidence import EvidenceFile
    from app.services.readability import readable_filter
    from tests.test_followups import make_report
    good = make_report(db_session)
    bad = make_report(db_session)
    bad.extraction.raw_ocr_text = ""
    pending = make_report(db_session)
    pending.processing_status = "PROCESSING"
    db_session.commit()
    assert [ev.id for ev in db_session.query(EvidenceFile).filter(readable_filter())] == [good.id]
