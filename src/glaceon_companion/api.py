from __future__ import annotations

import asyncio
import hmac
import threading
from pathlib import Path
from typing import Annotated, Any, Literal

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
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .attachments import AttachmentError, MAX_ATTACHMENT_BYTES, MAX_ATTACHMENTS_PER_CHAT
from .game_streaming import GameStreamingError
from .services import CompanionService
from .project_previews import CSP


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


class TravelRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str = Field(max_length=48)
    label: str = Field(max_length=80)
    ssh_alias: str = Field(max_length=64)


class TravelSelectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str = Field(max_length=48)


class TravelHeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ready: bool


class TravelInteractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern=r"^(pet|feed|play|wake|sleep|sit|resume)$")


class WorkRequest(ChatRequest):
    client_message_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")


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
    target: Literal["local", "bc250"] = "local"


def create_api(service: CompanionService, token: str, static_dir: Path) -> FastAPI:
    app = FastAPI(
        title=f"{service.config.name} Companion",
        version="0.15.1",
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

    def travel_authorize(authorization: Annotated[str | None, Header()] = None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Cliente no emparejado")
        device_id = service.travel.authenticate(authorization[7:])
        if device_id is None:
            raise HTTPException(status_code=401, detail="Cliente no emparejado")
        return device_id

    @app.get("/api/travel", dependencies=[auth])
    async def travel_status():
        return service.travel.snapshot()

    @app.post("/api/travel/register", dependencies=[auth])
    async def travel_register(request: TravelRegisterRequest):
        try:
            secret = service.travel.register(request.device_id, request.label, request.ssh_alias)
            return {"device_id": request.device_id, "client_token": secret}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/travel/select", dependencies=[auth])
    async def travel_select(request: TravelSelectRequest):
        try:
            return service.travel.select(request.device_id)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/travel/client/heartbeat")
    async def travel_heartbeat(request: TravelHeartbeatRequest,
                               device_id: str = Depends(travel_authorize)):
        value = service.travel.heartbeat(device_id, request.ready)
        state = service.state_dict()
        # Never disclose conversations, owner credentials, machine tools or filesystem paths.
        value["pet"] = {key: state[key] for key in
            ("name", "asleep", "energy", "hunger", "happiness") if key in state}
        value["pet"]["seated"] = bool(state.get("seated"))
        return value

    @app.post("/api/travel/client/return")
    async def travel_return(device_id: str = Depends(travel_authorize)):
        presence = service.travel.snapshot()
        if presence["active"] == device_id or presence["pending"] == device_id:
            service.travel.home()
        return {"ok": True}

    @app.post("/api/travel/client/interact")
    async def travel_interact(request: TravelInteractionRequest,
                              device_id: str = Depends(travel_authorize)):
        if service.travel.snapshot()["active"] != device_id:
            raise HTTPException(status_code=409, detail="Arfoxia no está en este dispositivo")
        result = service.interact(request.kind)
        return {key: result[key] for key in ("asleep", "seated", "energy", "hunger", "happiness") if key in result}

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
            "continuous_work": True,
            "project_previews": True,
            "cross_chat_memory": service.config.cross_chat_memory_enabled,
            "game_streaming": service.config.game_streaming_enabled,
            "chat_storage_limit_gb": min(
                float(service.config.chat_storage_limit_gb),
                150.0,
            ),
            "version": "0.15.1",
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
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/conversations", dependencies=[auth])
    async def conversations(
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
        cursor: Annotated[str | None, Query(max_length=512)] = None,
    ) -> dict[str, Any]:
        try:
            return service.list_conversations(limit=limit, cursor=cursor)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/tasks", dependencies=[auth], status_code=202)
    async def start_work(request: WorkRequest) -> dict[str, Any]:
        try:
            return service.start_work_task(request.message, conversation_id=request.conversation_id,
                client_message_id=request.client_message_id, attachment_ids=request.attachment_ids,
                research_mode=request.research_mode, origin="api")
        except (ValueError, AttachmentError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/tasks", dependencies=[auth])
    async def list_work(conversation_id: str) -> dict[str, Any]:
        try:
            service.get_conversation(conversation_id)
            return {"tasks": service.work_tasks.list(conversation_id)}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/tasks/{job_id}", dependencies=[auth])
    async def get_work(job_id: str) -> dict[str, Any]:
        try:
            return service.get_work_task(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/tasks/{job_id}/stop", dependencies=[auth])
    async def stop_work(job_id: str) -> dict[str, Any]:
        try:
            return service.work_tasks.stop(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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
        try:
            await service.unload_model()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    async def gaming_status(target: Literal["local", "bc250"] = "local") -> dict[str, Any]:
        try:
            return await asyncio.to_thread(service.game_streaming_status, target) if target != "local" else await asyncio.to_thread(service.game_streaming_status)
        except GameStreamingError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/gaming/targets", dependencies=[auth])
    async def gaming_targets():
        return {"targets": service.game_streaming.targets()}

    @app.post("/api/gaming/bc250/setup", dependencies=[auth])
    async def setup_bc250_sunshine():
        if not service.game_streaming.bc250.available():
            raise HTTPException(status_code=409, detail="Registra la BC-250 por SSH antes de configurar Sunshine.")
        service.events.put({"type": "ui", "action": "configure_bc250_sunshine"})
        return {"ok": True}

    @app.post("/api/gaming/prepare", dependencies=[auth])
    async def prepare_gaming(target: Literal["local", "bc250"] = "local") -> dict[str, Any]:
        try:
            return await asyncio.to_thread(service.prepare_game_streaming, target) if target != "local" else await asyncio.to_thread(service.prepare_game_streaming)
        except GameStreamingError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/gaming/pair", dependencies=[auth])
    async def pair_gaming(request: GameStreamingPairRequest) -> dict[str, Any]:
        result = await asyncio.to_thread(
            service.execute_action,
            "game_streaming_pair",
            {"pin": request.pin, "name": request.name, **({"target": request.target} if request.target != "local" else {})},
            False,
            origin="api",
        )
        return result.to_dict()

    @app.post("/api/ui/show-chat", dependencies=[auth])
    async def show_chat() -> dict[str, bool]:
        service.events.put({"type": "ui", "action": "show_chat"})
        return {"ok": True}

    @app.get("/api/projects", dependencies=[auth])
    async def projects():
        return {"projects": await asyncio.to_thread(service.project_previews.catalogue)}

    @app.post("/api/projects/{project_id}/preview", dependencies=[auth])
    async def open_project_preview(project_id: str):
        try:
            return await asyncio.to_thread(service.project_previews.issue, project_id)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=404, detail="Ese proyecto ya no está disponible; actualiza la lista.") from exc

    @app.get("/project-preview/{ticket}/{asset:path}")
    async def preview_resource(ticket: str, asset: str):
        try:
            path, mime, text = await asyncio.to_thread(service.project_previews.resource, ticket, asset)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=404, detail="Vista caducada o recurso no permitido. Vuelve a abrir el proyecto.") from exc
        headers = {"Content-Security-Policy": CSP, "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                   "X-Content-Type-Options": "nosniff", "Access-Control-Allow-Origin": "*",
                   "Permissions-Policy": "camera=(), microphone=(), geolocation=(), clipboard-read=(), clipboard-write=()"}
        return HTMLResponse(text, headers=headers) if text is not None else FileResponse(path, media_type=mime, headers=headers)

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
