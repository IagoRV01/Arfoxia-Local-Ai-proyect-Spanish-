import io
import json

from fastapi.testclient import TestClient
from PIL import Image

from glaceon_companion.api import create_api
from glaceon_companion.attachments import MAX_ATTACHMENT_BYTES
from glaceon_companion.config import PROJECT_ROOT, ConfigStore
from glaceon_companion.services import CompanionService


def test_api_requires_token_and_serves_mobile_ui(tmp_path):
    store = ConfigStore(tmp_path)
    service = CompanionService(store, store.load())
    token = "test-token"
    app = create_api(
        service,
        token,
        PROJECT_ROOT / "src" / "glaceon_companion" / "static",
    )
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.headers["cache-control"] == "no-store"
        unauthorized = client.get("/api/state")
        assert unauthorized.status_code == 401
        assert unauthorized.headers["cache-control"] == "no-store"
        response = client.get(
            "/api/state", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert "mood" in response.json()
        mobile = client.get("/")
        assert mobile.status_code == 200
        assert "no-cache" in mobile.headers["cache-control"]
        assert "/app.js?v=9" in mobile.text
        worker = client.get("/sw.js")
        assert worker.status_code == 200
        assert "no-store" in worker.headers["cache-control"]
        assert worker.headers["service-worker-allowed"] == "/"

        # A remote boolean cannot bypass the local password challenge.
        bypass = client.post(
            "/api/action",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "action": "power",
                "arguments": {"operation": "restart"},
                "confirmed": True,
            },
        )
        assert bypass.status_code == 422

        proposed = client.post(
            "/api/action",
            headers={"Authorization": f"Bearer {token}"},
            json={"action": "power", "arguments": {"operation": "restart"}},
        )
        assert proposed.status_code == 200
        assert proposed.json()["requires_authorization"] is True
        assert proposed.json()["password_configured"] is False
    service.close()


def test_attachment_upload_and_empty_text_chat_are_authenticated(tmp_path):
    store = ConfigStore(tmp_path)
    service = CompanionService(store, store.load())
    token = "attachment-token"
    app = create_api(
        service,
        token,
        PROJECT_ROOT / "src" / "glaceon_companion" / "static",
    )
    captured = {}
    conversation = service.create_conversation("Adjuntos")

    async def fake_chat(message, *, origin, attachment_ids, conversation_id):
        captured.update(
            {
                "message": message,
                "origin": origin,
                "attachment_ids": attachment_ids,
                "conversation_id": conversation_id,
            }
        )
        return {
            "message": "Veo un cuadrado azul.",
            "model": "qwen3.5:9b-q4_K_M",
            "model_mode": "large",
        }

    service.chat = fake_chat
    image = io.BytesIO()
    Image.new("RGB", (20, 20), "blue").save(image, "PNG")
    headers = {"Authorization": f"Bearer {token}"}
    try:
        with TestClient(app) as client:
            assert (
                client.post(
                    "/api/attachments",
                    files={"file": ("captura.png", image.getvalue(), "image/png")},
                ).status_code
                == 401
            )
            upload = client.post(
                "/api/attachments",
                headers=headers,
                files={"file": ("../captura.png", image.getvalue(), "image/png")},
            )
            assert upload.status_code == 200
            uploaded = upload.json()
            assert uploaded["name"] == "captura.png"
            assert uploaded["kind"] == "image"

            empty = client.post("/api/chat", headers=headers, json={"message": ""})
            assert empty.status_code == 422
            reply = client.post(
                "/api/chat",
                headers=headers,
                json={
                    "message": "",
                    "attachment_ids": [uploaded["attachment_id"]],
                    "conversation_id": conversation["id"],
                },
            )
            assert reply.status_code == 200
            assert reply.json()["model_mode"] == "large"
            assert captured == {
                "message": "",
                "origin": "api",
                "attachment_ids": [uploaded["attachment_id"]],
                "conversation_id": conversation["id"],
            }
    finally:
        service.close()


def test_mobile_assets_recover_from_stale_safari_cache():
    static_dir = PROJECT_ROOT / "src" / "glaceon_companion" / "static"
    index = (static_dir / "index.html").read_text(encoding="utf-8")
    app_js = (static_dir / "app.js").read_text(encoding="utf-8")
    worker = (static_dir / "sw.js").read_text(encoding="utf-8")
    manifest = json.loads(
        (static_dir / "manifest.webmanifest").read_text(encoding="utf-8")
    )

    assert "/style.css?v=9" in index
    assert "/app.js?v=9" in index
    assert "/manifest.webmanifest?v=9" in index
    assert 'id="startup-error"' in index
    assert "arfoxia-ui-v9" in worker
    assert "self.skipWaiting()" in worker
    assert "fetch(event.request)" in worker
    assert manifest["start_url"] == "/?ui=9"
    assert "main().catch(showStartupError)" in app_js
    assert "sessionStorage.setItem" in app_js
    assert '.register("/sw.js?v=9"' in app_js
    assert "?." not in app_js


def test_static_chat_requires_an_explicit_conversation_before_uploading():
    static_dir = PROJECT_ROOT / "src" / "glaceon_companion" / "static"
    index = (static_dir / "index.html").read_text(encoding="utf-8")
    app_js = (static_dir / "app.js").read_text(encoding="utf-8")

    assert 'id="conversation-select"' in index
    assert 'id="new-conversation-button"' in index
    assert 'api("/api/conversations?limit=100")' in app_js

    create_start = app_js.index("async function createConversation()")
    create_end = app_js.index("async function refresh()", create_start)
    create_function = app_js[create_start:create_end]
    assert 'api("/api/conversations", {' in create_function
    assert 'method: "POST"' in create_function

    send_start = app_js.index("async function sendChat(")
    send_end = app_js.index("function attachmentExtension", send_start)
    send_function = app_js[send_start:send_end]
    assert "createConversation(" not in send_function
    assert send_function.index("!conversationId") < send_function.index(
        'api("/api/attachments"'
    )
    assert "conversation_id: conversationId" in send_function

    submit_start = app_js.index('$("#chat-form").addEventListener')
    submit_end = app_js.index('$("#close-confirm").addEventListener', submit_start)
    submit_handler = app_js[submit_start:submit_end]
    assert submit_handler.index("if (!conversationId)") < submit_handler.index(
        "await sendChat(text, conversationId)"
    )


def test_attachment_upload_rejects_oversized_payload_and_model_status_is_private(
    tmp_path,
):
    store = ConfigStore(tmp_path)
    service = CompanionService(store, store.load())
    token = "status-token"
    app = create_api(
        service,
        token,
        PROJECT_ROOT / "src" / "glaceon_companion" / "static",
    )

    async def fake_status():
        return {
            "model": "qwen3.5:4b",
            "model_mode": "small",
            "reason": "game_active",
            "gpu": {"free_gb": 13.9},
            "game": {"active": True, "processes": ["RocketLeague.exe"]},
        }

    service.model_status = fake_status
    headers = {"Authorization": f"Bearer {token}"}
    try:
        with TestClient(app) as client:
            assert client.get("/api/model/status").status_code == 401
            status_response = client.get("/api/model/status", headers=headers)
            assert status_response.status_code == 200
            assert status_response.json()["reason"] == "game_active"

            oversized = client.post(
                "/api/attachments",
                headers=headers,
                files={
                    "file": (
                        "grande.txt",
                        b"x" * (MAX_ATTACHMENT_BYTES + 1),
                        "text/plain",
                    )
                },
            )
            assert oversized.status_code == 413
    finally:
        service.close()


def test_model_mode_switch_is_authenticated_and_strict(tmp_path):
    store = ConfigStore(tmp_path)
    service = CompanionService(store, store.load())
    token = "mode-token"
    app = create_api(
        service,
        token,
        PROJECT_ROOT / "src" / "glaceon_companion" / "static",
    )
    calls = []

    async def fake_switch(mode):
        calls.append(mode)
        return {
            "requested_mode": mode,
            "model_mode": "power" if mode == "power" else "large",
            "model": (
                "qwen3.6:27b-q4_K_M"
                if mode == "power"
                else "qwen3.5:9b-q4_K_M"
            ),
        }

    service.set_model_mode = fake_switch
    headers = {"Authorization": f"Bearer {token}"}
    try:
        with TestClient(app) as client:
            assert (
                client.post("/api/model/mode", json={"mode": "power"}).status_code
                == 401
            )
            activated = client.post(
                "/api/model/mode",
                headers=headers,
                json={"mode": "power"},
            )
            assert activated.status_code == 200
            assert activated.json()["model_mode"] == "power"
            assert calls == ["power"]
            gaming = client.post(
                "/api/model/mode",
                headers=headers,
                json={"mode": "gaming_gpu"},
            )
            assert gaming.status_code == 200
            assert calls == ["power", "gaming_gpu"]
            assert (
                client.post(
                    "/api/model/mode",
                    headers=headers,
                    json={"mode": "turbo"},
                ).status_code
                == 422
            )
            assert (
                client.post(
                    "/api/model/mode",
                    headers=headers,
                    json={"mode": "normal", "extra": True},
                ).status_code
                == 422
            )
    finally:
        service.close()


def test_game_streaming_routes_are_authenticated_and_pin_is_strict(tmp_path):
    store = ConfigStore(tmp_path)
    service = CompanionService(store, store.load())
    token = "gaming-token"
    app = create_api(
        service,
        token,
        PROJECT_ROOT / "src" / "glaceon_companion" / "static",
    )
    calls = []
    safe_status = {
        "ready": True,
        "host": "pc.tailnet.ts.net",
        "pairing_available": True,
    }
    service.game_streaming_status = lambda: dict(safe_status)
    service.prepare_game_streaming = lambda: {
        **safe_status,
        "message": "PC listo.",
    }

    def fake_pair(pin, name):
        calls.append((pin, name))
        return {**safe_status, "paired": True}

    service.pair_game_streaming = fake_pair
    service.authorization.configure("clave-local-segura")
    headers = {"Authorization": f"Bearer {token}"}
    try:
        with TestClient(app) as client:
            assert client.get("/api/gaming/status").status_code == 401
            status_response = client.get("/api/gaming/status", headers=headers)
            assert status_response.status_code == 200
            assert status_response.json()["host"] == "pc.tailnet.ts.net"

            assert client.post("/api/gaming/prepare").status_code == 401
            prepared = client.post("/api/gaming/prepare", headers=headers)
            assert prepared.status_code == 200
            assert prepared.json()["message"] == "PC listo."

            paired = client.post(
                "/api/gaming/pair",
                headers=headers,
                json={"pin": "1234", "name": "iPhone"},
            )
            assert paired.status_code == 200
            assert paired.json()["requires_authorization"] is True
            assert paired.json()["success"] is False
            assert "controle el PC" in paired.json()["authorization_summary"]
            challenge_id = paired.json()["challenge_id"]
            approved = service.authorize_action(
                challenge_id,
                "clave-local-segura",
            )
            assert approved.success is True
            assert approved.data["paired"] is True
            assert calls == [("1234", "iPhone")]
            assert (
                client.post(
                    "/api/gaming/pair",
                    headers=headers,
                    json={"pin": "12ab"},
                ).status_code
                == 422
            )
            assert (
                client.post(
                    "/api/gaming/pair",
                    headers=headers,
                    json={"pin": "1234", "extra": True},
                ).status_code
                == 422
            )
    finally:
        service.close()
