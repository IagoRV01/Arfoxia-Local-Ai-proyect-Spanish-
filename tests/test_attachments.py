from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

import glaceon_companion.attachments as attachments_module
from glaceon_companion.attachments import (
    AttachmentError,
    AttachmentStore,
    PreparedAttachment,
    build_ollama_message,
    prepare_attachment,
)


def _image_bytes(
    mode: str,
    size: tuple[int, int],
    color: str,
    image_format: str,
) -> bytes:
    output = io.BytesIO()
    Image.new(mode, size, color).save(output, image_format)
    return output.getvalue()


@pytest.mark.parametrize(
    ("name", "mode", "size", "color", "image_format", "expected_media"),
    [
        (
            "captura.png",
            "RGBA",
            (3_000, 1_000),
            "red",
            "PNG",
            "image/png",
        ),
        (
            "foto.jpg",
            "RGB",
            (640, 480),
            "blue",
            "JPEG",
            "image/jpeg",
        ),
    ],
    ids=["rgba-png", "rgb-jpeg"],
)
def test_prepare_valid_image_normalizes_format_and_dimensions(
    name: str,
    mode: str,
    size: tuple[int, int],
    color: str,
    image_format: str,
    expected_media: str,
) -> None:
    data = _image_bytes(mode, size, color, image_format)
    attachment = prepare_attachment(name, data)

    assert attachment.kind == "image"
    assert attachment.media_type == expected_media
    assert attachment.size == len(data)
    assert attachment.text is None
    assert attachment.image_bytes is not None
    with Image.open(io.BytesIO(attachment.image_bytes)) as normalized:
        assert max(normalized.size) <= attachments_module.NORMALIZED_IMAGE_EDGE
        assert getattr(normalized, "n_frames", 1) == 1


def test_prepare_rejects_animated_image() -> None:
    first = Image.new("RGBA", (8, 8), "red")
    second = Image.new("RGBA", (8, 8), "blue")
    output = io.BytesIO()
    first.save(
        output,
        "PNG",
        save_all=True,
        append_images=[second],
        duration=100,
        loop=0,
    )

    with pytest.raises(AttachmentError, match="animadas"):
        prepare_attachment("animacion.png", output.getvalue())


def test_prepare_rejects_image_over_dimension_limit() -> None:
    data = _image_bytes(
        "RGB",
        (attachments_module.MAX_IMAGE_EDGE + 1, 1),
        "white",
        "PNG",
    )

    with pytest.raises(AttachmentError, match="demasiado grande"):
        prepare_attachment("demasiado-ancha.png", data)


def test_prepare_text_requires_utf8_and_cleans_controls() -> None:
    attachment = prepare_attachment(
        "notas.txt",
        b"\xef\xbb\xbfHola\x00 mundo\r\nlinea",
        "text/plain; charset=utf-8",
    )

    assert attachment.kind == "text"
    assert attachment.media_type == "text/plain"
    assert attachment.text == "Hola  mundo \nlinea"

    with pytest.raises(AttachmentError, match="UTF-8"):
        prepare_attachment("binario.txt", b"\xff\xfe\xfd")


def test_store_sanitizes_traversal_and_control_characters() -> None:
    store = AttachmentStore()

    info = store.add_bytes("../../carpeta\\\x00 secreto.txt", b"contenido")

    assert info.name == "secreto.txt"
    assert store.claim([info.attachment_id])[0].name == "secreto.txt"


def test_claim_is_one_use_and_duplicate_rejection_is_atomic() -> None:
    store = AttachmentStore()
    info = store.add_bytes("uno.txt", b"uno")

    with pytest.raises(AttachmentError, match="dos veces"):
        store.claim([info.attachment_id, info.attachment_id])

    assert [item.text for item in store.claim([info.attachment_id])] == ["uno"]
    with pytest.raises(AttachmentError, match="caducado|ya fue enviado"):
        store.claim([info.attachment_id])


def test_expired_attachment_is_removed_without_affecting_new_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    monkeypatch.setattr(attachments_module.time, "monotonic", lambda: now[0])
    store = AttachmentStore(ttl_seconds=60)
    expired = store.add_bytes("viejo.txt", b"viejo")

    now[0] = 160.0
    fresh = store.add_bytes("nuevo.txt", b"nuevo")

    with pytest.raises(AttachmentError, match="caducado|ya fue enviado"):
        store.claim([expired.attachment_id])
    assert store.claim([fresh.attachment_id])[0].text == "nuevo"


def test_store_quota_rejection_does_not_consume_existing_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(attachments_module, "MAX_TOTAL_UPLOAD_BYTES", 1)
    monkeypatch.setattr(attachments_module, "MAX_STORE_BYTES", 100)
    store = AttachmentStore(max_store_bytes=7)
    first = store.add_bytes("primero.txt", b"1234")

    with pytest.raises(AttachmentError, match="demasiados adjuntos temporales"):
        store.add_bytes("segundo.txt", b"5678")

    monkeypatch.setattr(attachments_module, "MAX_TOTAL_UPLOAD_BYTES", 10)
    assert store.claim([first.attachment_id])[0].text == "1234"


def test_total_chat_quota_rejection_is_atomic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(attachments_module, "MAX_TOTAL_UPLOAD_BYTES", 9)
    store = AttachmentStore()
    first = store.add_bytes("primero.txt", b"12345")
    second = store.add_bytes("segundo.txt", b"67890")

    with pytest.raises(AttachmentError, match="16 MiB|tama(?:n|ñ)o total"):
        store.claim([first.attachment_id, second.attachment_id])

    assert store.claim([first.attachment_id])[0].text == "12345"
    assert store.claim([second.attachment_id])[0].text == "67890"


def test_build_ollama_message_adds_base64_images_and_shares_text_limit() -> None:
    raw_image = b"\x00image-bytes\xff"
    source_message = {"role": "user", "content": "Analiza esto"}
    prepared = [
        PreparedAttachment(
            name="captura.png",
            kind="image",
            media_type="image/png",
            size=len(raw_image),
            image_bytes=raw_image,
        ),
        PreparedAttachment(
            name="primero.txt",
            kind="text",
            media_type="text/plain",
            size=6,
            text="AAAAAA",
        ),
        PreparedAttachment(
            name="segundo.txt",
            kind="text",
            media_type="text/plain",
            size=6,
            text="BBBBBB",
        ),
    ]

    result = build_ollama_message(source_message, prepared, max_text_chars=7)

    assert source_message == {"role": "user", "content": "Analiza esto"}
    assert result["images"] == [base64.b64encode(raw_image).decode("ascii")]
    assert "contenido no confiable" in result["content"]
    assert "AAAAAA" in result["content"]
    assert "\nB\n" in result["content"]
    assert "BB" not in result["content"]


def test_build_ollama_message_without_attachments_returns_unmodified_copy() -> None:
    source_message = {"role": "user", "content": "Hola"}

    result = build_ollama_message(source_message, [], max_text_chars=10)

    assert result == source_message
    assert result is not source_message


def _minimal_text_pdf(text: str) -> bytes:
    stream = f"BT\n/F1 12 Tf\n72 720 Td\n({text}) Tj\nET\n".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        + stream
        + b"endstream",
    ]
    document = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, value in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{index} 0 obj\n".encode("ascii"))
        document.extend(value)
        document.extend(b"\nendobj\n")
    xref_offset = len(document)
    document.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    document.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    document.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(document)


def test_prepare_pdf_extracts_text_when_pypdf_is_available() -> None:
    pytest.importorskip("pypdf")

    attachment = prepare_attachment(
        "documento.pdf",
        _minimal_text_pdf("Hello Arfoxia PDF"),
        "application/pdf",
    )

    assert attachment.kind == "pdf"
    assert attachment.media_type == "application/pdf"
    assert attachment.text is not None
    assert "Hello Arfoxia PDF" in attachment.text
