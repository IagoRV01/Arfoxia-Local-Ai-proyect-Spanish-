from __future__ import annotations

import asyncio
import hmac
import threading
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .attachments import AttachmentError, MAX_ATTACHMENT_BYTES, MAX_ATTACHMENTS_PER_CHAT
from .game_streaming import GameStreamingError
from .services import CompanionService


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(default="", max_length=1200)
    attachment_ids: list[str] = Field(
        default_factory=list,
        max_length=MAX_ATTACHMENTS_PER_CHAT,
    )
    conversation_id: str = Field(min_length=1, max_length=64)
    client_message_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    research_mode: bool = False

    @model_validator(mode="after")
    def require_content(self) -> "ChatRequest":
        if not self.message.strip() and not self.attachment_ids:
            raise ValueError("El mensaje o un adjunto son obligatorios")
        return self


class InteractionRequest(BaseModel):
    kind: str


class ConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=80)


class ConversationRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=80)


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ModelModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = Field(pattern=r"^(normal|power|gaming_gpu|dual)$")


class GameStreamingPairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pin: str = Field(pattern=r"^[0-9]{4}$")
    name: str = Field(default="iPhone de Iago", min_length=1, max_length=64)


def create_api(service: CompanionService, token: str, static_dir: Path) -> FastAPI:
    app = FastAPI(
        title=f"{service.config.name} Companion",
        version="0.14.0",
        docs_url=None,
        redoc_url=None,
    )

    @app.middleware("http")
    async def mobile_cache_policy(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        elif path == "/sw.js":
            response.headers["Cache-Control"] = (
                "no-cache, no-store, must-revalidate"
            )
            response.headers["Service-Worker-Allowed"] = "/"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        elif path in {
            "/",
            "/index.html",
            "/app.js",
            "/style.css",
            "/manifest.webmanifest",
        }:
            response.headers["Cache-Control"] = (
                "no-cache, max-age=0, must-revalidate"
            )
        return response

    def authorize(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = f"Bearer {token}"
        if not authorization or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    auth = Depends(authorize)

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "name": service.config.name,
            "species": service.config.species,
            "gender": service.config.gender,
            "languages": service.config.supported_languages,
            "online_search": service.config.online_search_enabled,
            "intensive_search": service.config.online_search_enabled,
            "attachments": True,
            "adaptive_models": service.config.adaptive_model_enabled,
            "codex_bridge": service.config.codex_bridge_enabled,
            "eevee_companion": service.config.eevee_companion_enabled,
            "physical_interactions": True,
            "privileged_actions": True,
            "conversations": True,
            "cross_chat_memory": service.config.cross_chat_memory_enabled,
            "game_streaming": service.config.game_streaming_enabled,
            "chat_storage_limit_gb": min(
                float(service.config.chat_storage_limit_gb),
                150.0,
            ),
            "version": "0.14.0",
        }

    @app.get("/api/state", dependencies=[auth])
    async def state_value() -> dict[str, Any]:
        return service.state_dict()

    @app.post("/api/interact", dependencies=[auth])
    async def interact(request: InteractionRequest) -> dict[str, Any]:
        try:
            return service.interact(request.kind)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/chat", dependencies=[auth])
    async def chat(request: ChatRequest) -> dict[str, Any]:
        try:
            options: dict[str, Any] = {
                "origin": "api",
                "attachment_ids": request.attachment_ids,
                "conversation_id": request.conversation_id,
            }
            if request.client_message_id is not None:
                options["client_message_id"] = request.client_message_id
            if request.research_mode:
                options["research_mode"] = True
            return await service.chat(request.message, **options)
        except (ValueError, AttachmentError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/conversations", dependencies=[auth])
    async def conversations(
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
        cursor: Annotated[str | None, Query(max_length=512)] = None,
    ) -> dict[str, Any]:
        try:
            return service.list_conversations(limit=limit, cursor=cursor)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post(
        "/api/conversations",
        dependencies=[auth],
        status_code=status.HTTP_201_CREATED,
    )
    async def create_conversation(
        request: ConversationCreateRequest,
    ) -> dict[str, Any]:
        try:
            return service.create_conversation(request.title)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/conversations/{conversation_id}", dependencies=[auth])
    async def conversation(conversation_id: str) -> dict[str, Any]:
        try:
            return service.get_conversation(conversation_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/api/conversations/{conversation_id}", dependencies=[auth])
    async def rename_conversation(
        conversation_id: str,
        request: ConversationRenameRequest,
    ) -> dict[str, Any]:
        try:
            return service.rename_conversation(conversation_id, request.title)
        except ValueError as exc:
            code = 404 if "no existe" in str(exc).casefold() else 400
            raise HTTPException(status_code=code, detail=str(exc)) from exc

    @app.delete("/api/conversations/{conversation_id}", dependencies=[auth])
    async def delete_conversation(conversation_id: str) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(
                service.delete_conversation,
                conversation_id,
            )
        except ValueError as exc:
            code = 409 if "terminando una respuesta" in str(exc) else 404
            raise HTTPException(status_code=code, detail=str(exc)) from exc

    @app.get(
        "/api/conversations/{conversation_id}/messages",
        dependencies=[auth],
    )
    async def conversation_messages(
        conversation_id: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
        before_id: Annotated[int | None, Query(ge=1)] = None,
    ) -> dict[str, Any]:
        try:
            return service.conversation_messages(
                conversation_id,
                limit=limit,
                before_id=before_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get(
        "/api/conversations/{conversation_id}/attachments/{attachment_id}",
        dependencies=[auth],
    )
    async def conversation_attachment(
        conversation_id: str,
        attachment_id: str,
    ) -> FileResponse:
        try:
            path, metadata = service.conversation_attachment(
                conversation_id,
                attachment_id,
            )
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(
            path,
            media_type=str(metadata["media_type"]),
            filename=str(metadata["name"]),
        )

    @app.post("/api/attachments", dependencies=[auth])
    async def upload_attachment(file: UploadFile = File(...)) -> dict[str, Any]:
        try:
            data = await file.read(MAX_ATTACHMENT_BYTES + 1)
        finally:
            await file.close()
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Cada adjunto puede ocupar como máximo 8 MiB.",
            )
        try:
            info = service.add_attachment_bytes(
                file.filename or "adjunto",
                data,
                file.content_type or "",
            )
        except AttachmentError as exc:
            raise HTTPException(status_code=415, detail=str(exc)) from exc
        return info.to_dict()

    @app.post("/api/action", dependencies=[auth])
    async def action(request: ActionRequest) -> dict[str, Any]:
        result = await asyncio.to_thread(
            service.execute_action,
            request.action,
            request.arguments,
            False,
            origin="api",
        )
        return result.to_dict()

    @app.get("/api/screenshots/{screenshot_id}", dependencies=[auth])
    async def screenshot(screenshot_id: str) -> FileResponse:
        path = service.actions.screenshot_path(screenshot_id)
        if not path:
            raise HTTPException(status_code=404, detail="Captura no encontrada")
        return FileResponse(path, media_type="image/webp", filename="captura-arfoxia.webp")

    @app.post("/api/model/unload", dependencies=[auth])
    async def unload() -> dict[str, bool]:
        await service.unload_model()
        return {"ok": True}

    @app.get("/api/model/status", dependencies=[auth])
    async def model_status() -> dict[str, Any]:
        return await service.model_status()

    @app.post("/api/model/mode", dependencies=[auth])
    async def set_model_mode(request: ModelModeRequest) -> dict[str, Any]:
        try:
            return await service.set_model_mode(request.mode)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/gaming/status", dependencies=[auth])
    async def gaming_status() -> dict[str, Any]:
        return await asyncio.to_thread(service.game_streaming_status)

    @app.post("/api/gaming/prepare", dependencies=[auth])
    async def prepare_gaming() -> dict[str, Any]:
        try:
            return await asyncio.to_thread(service.prepare_game_streaming)
        except GameStreamingError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/gaming/pair", dependencies=[auth])
    async def pair_gaming(request: GameStreamingPairRequest) -> dict[str, Any]:
        result = await asyncio.to_thread(
            service.execute_action,
            "game_streaming_pair",
            {"pin": request.pin, "name": request.name},
            False,
            origin="api",
        )
        return result.to_dict()

    @app.post("/api/ui/show-chat", dependencies=[auth])
    async def show_chat() -> dict[str, bool]:
        service.events.put({"type": "ui", "action": "show_chat"})
        return {"ok": True}

    app.mount("/", StaticFiles(directory=static_dir, html=True), name="mobile")
    return app


class ApiServerThread(threading.Thread):
    def __init__(self, app: FastAPI, host: str, port: int) -> None:
        super().__init__(name="glaceon-api", daemon=True)
        self.server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=host,
                port=port,
                log_level="warning",
                access_log=False,
                log_config=None,
            )
        )

    def run(self) -> None:
        self.server.run()

    def stop(self) -> None:
        self.server.should_exit = True
