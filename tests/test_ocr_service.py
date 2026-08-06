from app.services.ocr import OCRError, OCRService, _clean_text


def test_clean_text_removes_empty_and_duplicate_lines() -> None:
    text = _clean_text(" Hello   world \n\nhello world\nToken   limit ")

    assert text == "Hello world\nToken limit"


def test_check_status_reports_engine_initialization_failure(monkeypatch) -> None:
    service = OCRService()

    def fail_to_initialize():
        raise OCRError("RapidOCR 初始化失败: broken model")

    monkeypatch.setattr(service, "_get_engine", fail_to_initialize)
    status = service.check_status()
    assert status.ok is False
    assert "broken model" in status.message


def test_extract_text_skips_orientation_classification_for_screenshots(
    tmp_path, monkeypatch
) -> None:
    image_path = tmp_path / "capture.png"
    image_path.write_bytes(b"fake")
    calls: list[dict] = []

    def fake_engine(path: str, **kwargs):
        calls.append({"path": path, **kwargs})
        return ([[None, "Hello"]], None)

    service = OCRService()
    monkeypatch.setattr(service, "_get_engine", lambda: fake_engine)

    assert service.extract_text(image_path) == "Hello"
    assert calls == [{"path": str(image_path), "use_cls": False}]
