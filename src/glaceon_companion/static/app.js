const MAX_ATTACHMENTS = 4;
const MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024;
const MAX_TOTAL_ATTACHMENT_BYTES = 16 * 1024 * 1024;
const ALLOWED_ATTACHMENT_EXTENSIONS = new Set([
  "png", "jpg", "jpeg", "webp", "pdf", "txt", "md", "markdown", "csv", "json",
  "jsonl", "py", "js", "mjs", "cjs", "ts", "tsx", "jsx", "html", "htm", "css",
  "xml", "yaml", "yml", "toml", "ini", "cfg", "log", "sql", "ps1", "bat",
]);
const ALLOWED_ATTACHMENT_TYPES = new Set([
  "image/png", "image/jpeg", "image/webp", "application/pdf", "application/json",
  "application/ld+json", "application/x-ndjson", "application/javascript",
  "application/xml", "application/yaml",
]);
const state = {
  token: "",
  screenshotUrl: null,
  conversations: [],
  selectedConversationId: "",
  conversationBusy: false,
  pendingAttachments: [],
  chatBusy: false,
  nextAttachmentKey: 1,
};
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function readToken() {
  const fragment = new URLSearchParams(location.hash.slice(1));
  const incoming = fragment.get("token");
  if (incoming) {
    state.token = incoming;
    let persisted = false;
    try {
      localStorage.setItem("glaceon-token", incoming);
      persisted = true;
    } catch (error) {
      try {
        sessionStorage.setItem("glaceon-token", incoming);
        persisted = true;
      } catch (sessionError) {
        // Safari can block both stores. The in-memory token still works.
      }
    }
    if (persisted) {
      try {
        history.replaceState(null, "", `${location.pathname}${location.search}`);
      } catch (error) {
        // Keeping the fragment is safer than aborting the whole interface.
      }
    }
    return;
  }
  try {
    state.token = localStorage.getItem("glaceon-token") || "";
  } catch (error) {
    try {
      state.token = sessionStorage.getItem("glaceon-token") || "";
    } catch (sessionError) {
      state.token = "";
    }
  }
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}), Authorization: `Bearer ${state.token}` };
  const bodyIsFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  if (options.body && typeof options.body !== "string" && !bodyIsFormData) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg || String(item)).join("; ")
      : (typeof detail === "string" ? detail : "");
    const error = new Error(message || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return response;
}

function meter(label, value, invert = false) {
  const display = Math.round(value);
  const positive = invert ? 100 - display : display;
  return `<div class="meter"><span>${label}</span><div class="track"><div class="fill" style="width:${positive}%"></div></div><strong>${display}</strong></div>`;
}

function renderState(value) {
  $("#mood").textContent = value.mood;
  $("#meters").innerHTML = [
    meter("Hambre", value.hunger, true),
    meter("Felicidad", value.happiness),
    meter("Energía", value.energy),
    meter("Confianza", value.trust),
  ].join("");
}

function addMessage(text, mine = false) {
  const bubble = document.createElement("div");
  bubble.className = `bubble${mine ? " me" : ""}`;
  bubble.textContent = text;
  $("#messages").appendChild(bubble);
  bubble.scrollIntoView({ behavior: "smooth", block: "end" });
  return bubble;
}

function addModelMeta(result, bubble) {
  const mode = String(result.model_mode || "").trim();
  const model = String(result.model || "").trim();
  if (!mode && !model) return;
  const friendlyModes = {
    large: "modo amplio",
    small: "modo ligero",
    adaptive: "modo adaptativo",
  };
  const parts = [];
  if (mode) parts.push(friendlyModes[mode.toLowerCase()] || mode);
  if (model) parts.push(model);
  const badge = document.createElement("span");
  badge.className = "model-meta";
  badge.textContent = parts.join(" · ");
  bubble.appendChild(badge);
}

function addSources(sources = []) {
  const seen = new Set();
  const safeSources = sources.filter((source) => {
    try { return new URL(source.url).protocol === "https:"; } catch { return false; }
  }).filter((source) => {
    if (seen.has(source.url)) return false;
    seen.add(source.url);
    return true;
  }).slice(0, 12);
  if (!safeSources.length) return;
  const bubble = document.createElement("div");
  bubble.className = "bubble sources";
  const heading = document.createElement("strong");
  heading.textContent = "Fuentes online";
  bubble.appendChild(heading);
  safeSources.forEach((source) => {
    const link = document.createElement("a");
    link.href = source.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = source.title || new URL(source.url).hostname;
    bubble.appendChild(document.createElement("br"));
    bubble.appendChild(link);
  });
  $("#messages").appendChild(bubble);
}

function updateChatControls() {
  const selectionMissing = !state.selectedConversationId;
  const blocked = state.chatBusy || state.conversationBusy;
  const select = $("#conversation-select");
  const create = $("#new-conversation-button");
  const input = $("#message");
  const send = $("#send-button");
  const attach = $("#attach-button");
  const attachmentInput = $("#attachment-input");

  select.disabled = blocked || !state.conversations.length;
  create.disabled = blocked;
  input.disabled = blocked || selectionMissing;
  send.disabled = blocked || selectionMissing;
  attach.disabled =
    blocked ||
    selectionMissing ||
    state.pendingAttachments.length >= MAX_ATTACHMENTS;
  attachmentInput.disabled = blocked || selectionMissing;
  input.placeholder = selectionMissing
    ? "Selecciona un chat o pulsa + Nueva…"
    : "Escribe una orden o un mensaje…";
}

function clearConversationDraft() {
  state.pendingAttachments = [];
  $("#message").value = "";
  const messages = $("#messages");
  while (messages.firstChild) messages.removeChild(messages.firstChild);
  renderAttachments();
}

function renderConversationSelector() {
  const select = $("#conversation-select");
  while (select.firstChild) select.removeChild(select.firstChild);
  if (!state.conversations.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No hay conversaciones";
    select.appendChild(option);
    state.selectedConversationId = "";
  } else {
    for (const conversation of state.conversations) {
      const option = document.createElement("option");
      option.value = conversation.id;
      option.textContent = conversation.title || "Nueva conversación";
      select.appendChild(option);
    }
    select.value = state.selectedConversationId;
  }
  updateChatControls();
}

async function loadConversations() {
  const response = await api("/api/conversations?limit=100");
  const payload = await response.json();
  const incoming = Array.isArray(payload.conversations)
    ? payload.conversations.filter(
        (conversation) =>
          conversation &&
          typeof conversation.id === "string" &&
          conversation.id,
      )
    : [];
  const previous = state.selectedConversationId;
  state.conversations = incoming;
  const currentStillExists = incoming.some(
    (conversation) => conversation.id === previous,
  );
  state.selectedConversationId = currentStillExists
    ? previous
    : (incoming[0] ? incoming[0].id : "");
  if (state.selectedConversationId !== previous) {
    clearConversationDraft();
  }
  renderConversationSelector();
  if (!state.selectedConversationId) {
    setChatStatus(
      "No hay ninguna conversación. Pulsa + Nueva para crear una.",
    );
  }
}

async function createConversation() {
  if (state.chatBusy || state.conversationBusy) return;
  state.conversationBusy = true;
  updateChatControls();
  try {
    const response = await api("/api/conversations", {
      method: "POST",
      body: {},
    });
    const payload = await response.json();
    const created = payload.conversation || payload;
    if (!created || typeof created.id !== "string" || !created.id) {
      throw new Error("El servidor no devolvió la nueva conversación.");
    }
    state.conversations = [
      created,
      ...state.conversations.filter(
        (conversation) => conversation.id !== created.id,
      ),
    ];
    state.selectedConversationId = created.id;
    clearConversationDraft();
    renderConversationSelector();
    setChatStatus("Conversación creada. Ya puedes escribir a Arfoxia.");
  } finally {
    state.conversationBusy = false;
    updateChatControls();
  }
}

async function refresh() {
  try {
    const response = await api("/api/state");
    renderState(await response.json());
    $("#connection").textContent = "Conectado de forma segura";
    $("#dashboard").classList.remove("hidden");
    $("#pairing").classList.add("hidden");
    $("#startup-error").classList.add("hidden");
  } catch (error) {
    $("#connection").textContent = "Sin conexión";
    if (!state.token || error.status === 401) {
      $("#pairing").classList.remove("hidden");
    }
    if ($("#dashboard").classList.contains("hidden")) {
      $("#startup-error").classList.remove("hidden");
    }
  }
}

async function interact(kind) {
  const response = await api("/api/interact", { method: "POST", body: { kind } });
  renderState(await response.json());
}

async function executeAction(action, args = {}) {
  const response = await api("/api/action", { method: "POST", body: { action, arguments: args } });
  const result = await response.json();
  if (result.requires_authorization) {
    showAuthorizationNotice(result.message);
    return result;
  }
  if (action === "pc_status" && result.data) {
    $("#pc-status").textContent = JSON.stringify(result.data, null, 2);
    $("#pc-status").classList.remove("hidden");
  }
  if (result.data && result.data.screenshot_id) {
    await showScreenshot(result.data.screenshot_id);
  }
  addMessage(result.message);
  return result;
}

async function showScreenshot(id) {
  const response = await api(`/api/screenshots/${id}`);
  const blob = await response.blob();
  if (state.screenshotUrl) URL.revokeObjectURL(state.screenshotUrl);
  state.screenshotUrl = URL.createObjectURL(blob);
  $("#screenshot").src = state.screenshotUrl;
  $("#screenshot").classList.remove("hidden");
}

function showAuthorizationNotice(text) {
  $("#confirm-text").textContent = text || "Autoriza esta acción en el diálogo privado del PC.";
  const dialog = $("#confirm-dialog");
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
}

async function sendChat(message, conversationId) {
  if (
    !conversationId ||
    !state.conversations.some(
      (conversation) => conversation.id === conversationId,
    )
  ) {
    throw new Error(
      "Selecciona una conversación o pulsa + Nueva antes de enviar.",
    );
  }
  const attachments = [...state.pendingAttachments];
  const attachmentIds = [];
  const attachmentNames = attachments.map((entry) => entry.file.name);

  for (let index = 0; index < attachments.length; index += 1) {
    const entry = attachments[index];
    entry.status = "uploading";
    entry.error = "";
    setChatStatus(`Subiendo ${index + 1} de ${attachments.length}: ${entry.file.name}…`);
    renderAttachments();
    try {
      const form = new FormData();
      form.append("file", entry.file, entry.file.name);
      const uploadResponse = await api("/api/attachments", { method: "POST", body: form });
      const uploaded = await uploadResponse.json();
      if (!uploaded.attachment_id) {
        throw new Error("El servidor no devolvió un identificador para el archivo.");
      }
      attachmentIds.push(uploaded.attachment_id);
      entry.status = "uploaded";
      renderAttachments();
    } catch (error) {
      entry.status = "error";
      entry.error = error.message;
      renderAttachments();
      throw new Error(`No se pudo subir “${entry.file.name}”: ${error.message}`);
    }
  }

  const visibleMessage = [
    message,
    attachmentNames.length ? `📎 ${attachmentNames.join(", ")}` : "",
  ].filter(Boolean).join("\n");
  addMessage(visibleMessage, true);
  setChatStatus(attachments.length ? "Arfoxia está revisando el mensaje y los archivos…" : "Arfoxia está pensando…");
  const response = await api("/api/chat", {
    method: "POST",
    body: {
      message,
      attachment_ids: attachmentIds,
      conversation_id: conversationId,
    },
  });
  const result = await response.json();
  const responseConversationId =
    result.conversation_id ||
    (result.conversation && result.conversation.id) ||
    (result.user_message && result.user_message.conversation_id) ||
    (result.assistant_message && result.assistant_message.conversation_id);
  if (
    responseConversationId &&
    responseConversationId !== conversationId
  ) {
    throw new Error(
      "La respuesta pertenece a otra conversación y no se ha mezclado con este chat.",
    );
  }
  const responseBubble = addMessage(result.message);
  addModelMeta(result, responseBubble);
  const actionResults = result.action_results || (result.action_result ? [result.action_result] : []);
  for (const actionResult of actionResults) {
    if (actionResult.data && actionResult.data.screenshot_id) {
      await showScreenshot(actionResult.data.screenshot_id);
    }
  }
  addSources(result.sources || []);
  if (result.requires_authorization) showAuthorizationNotice(result.message);
  await refresh();
  loadConversations().catch(() => {});
  return result;
}

function attachmentExtension(name) {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : "";
}

function isAllowedAttachment(file) {
  const type = String(file.type || "").toLowerCase();
  return type.startsWith("text/")
    || ALLOWED_ATTACHMENT_TYPES.has(type)
    || ALLOWED_ATTACHMENT_EXTENSIONS.has(attachmentExtension(file.name));
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

function addAttachments(fileList) {
  if (!state.selectedConversationId) {
    setChatStatus(
      "Selecciona una conversación o pulsa + Nueva antes de adjuntar.",
      "error",
    );
    return;
  }
  const errors = [];
  for (const file of [...fileList]) {
    if (state.pendingAttachments.length >= MAX_ATTACHMENTS) {
      errors.push(`Solo puedes adjuntar ${MAX_ATTACHMENTS} archivos por mensaje.`);
      break;
    }
    if (!file.size) {
      errors.push(`“${file.name}” está vacío.`);
      continue;
    }
    if (file.size > MAX_ATTACHMENT_BYTES) {
      errors.push(`“${file.name}” supera el límite de 8 MiB.`);
      continue;
    }
    if (!isAllowedAttachment(file)) {
      errors.push(`“${file.name}” no es una imagen, PDF, texto ni archivo de código compatible.`);
      continue;
    }
    const pendingBytes = state.pendingAttachments.reduce((total, entry) => total + entry.file.size, 0);
    if (pendingBytes + file.size > MAX_TOTAL_ATTACHMENT_BYTES) {
      errors.push("El conjunto de adjuntos no puede superar 16 MiB.");
      continue;
    }
    const duplicate = state.pendingAttachments.some((entry) =>
      entry.file.name === file.name
      && entry.file.size === file.size
      && entry.file.lastModified === file.lastModified
    );
    if (duplicate) {
      errors.push(`“${file.name}” ya está adjunto.`);
      continue;
    }
    state.pendingAttachments.push({
      key: state.nextAttachmentKey,
      file,
      status: "ready",
      error: "",
    });
    state.nextAttachmentKey += 1;
  }
  renderAttachments();
  setChatStatus(errors.join(" "), errors.length ? "error" : "");
}

function removeAttachment(key) {
  if (state.chatBusy || state.conversationBusy) return;
  state.pendingAttachments = state.pendingAttachments.filter((entry) => entry.key !== key);
  renderAttachments();
  if (!state.pendingAttachments.length) setChatStatus("");
}

function renderAttachments() {
  const list = $("#attachment-list");
  while (list.firstChild) list.removeChild(list.firstChild);
  for (const entry of state.pendingAttachments) {
    const chip = document.createElement("span");
    chip.className = `attachment-chip ${entry.status}`;
    if (entry.error) chip.title = entry.error;

    const name = document.createElement("span");
    name.className = "attachment-name";
    name.textContent = entry.file.name;
    chip.appendChild(name);

    const size = document.createElement("span");
    size.className = "attachment-size";
    size.textContent = formatBytes(entry.file.size);
    chip.appendChild(size);

    if (entry.status === "uploading") {
      const progress = document.createElement("span");
      progress.className = "attachment-progress";
      progress.setAttribute("aria-label", "Subiendo");
      chip.appendChild(progress);
    } else if (entry.status === "uploaded") {
      const done = document.createElement("span");
      done.className = "attachment-done";
      done.textContent = "✓";
      done.setAttribute("aria-label", "Subido");
      chip.appendChild(done);
    } else if (entry.status === "error") {
      const failed = document.createElement("span");
      failed.className = "attachment-failed";
      failed.textContent = "!";
      failed.setAttribute("aria-label", "Error de subida");
      chip.appendChild(failed);
    }

    if (!state.chatBusy && !state.conversationBusy) {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "attachment-remove";
      remove.textContent = "×";
      remove.setAttribute("aria-label", `Quitar ${entry.file.name}`);
      remove.addEventListener("click", () => removeAttachment(entry.key));
      chip.appendChild(remove);
    }
    list.appendChild(chip);
  }

  const panel = $("#attachment-panel");
  panel.classList.toggle("hidden", !state.pendingAttachments.length);
  const totalBytes = state.pendingAttachments.reduce((total, entry) => total + entry.file.size, 0);
  $("#attachment-summary").textContent = state.pendingAttachments.length
    ? `${state.pendingAttachments.length} de ${MAX_ATTACHMENTS} archivos · ${formatBytes(totalBytes)}`
    : "";
  updateChatControls();
}

function setChatStatus(message, kind = "") {
  const status = $("#chat-status");
  status.textContent = message;
  status.className = `chat-status${kind ? ` ${kind}` : ""}${message ? "" : " hidden"}`;
}

function setChatBusy(busy) {
  state.chatBusy = busy;
  renderAttachments();
}

async function main() {
  readToken();
  if (!state.token) {
    $("#connection").textContent = "Falta emparejar este dispositivo";
    $("#pairing").classList.remove("hidden");
    return;
  }
  $$('[data-interaction]').forEach((button) => button.addEventListener("click", () => interact(button.dataset.interaction).catch(showError)));
  $$('[data-action]').forEach((button) => button.addEventListener("click", () => executeAction(button.dataset.action).catch(showError)));
  $$('[data-open]').forEach((button) => button.addEventListener("click", () => executeAction("open_app", { app: button.dataset.open }).catch(showError)));
  $("#conversation-select").addEventListener("change", (event) => {
    const conversationId = String(event.target.value || "");
    const exists = state.conversations.some(
      (conversation) => conversation.id === conversationId,
    );
    state.selectedConversationId = exists ? conversationId : "";
    clearConversationDraft();
    updateChatControls();
    setChatStatus(
      state.selectedConversationId
        ? ""
        : "Selecciona una conversación o pulsa + Nueva.",
    );
  });
  $("#new-conversation-button").addEventListener("click", () => {
    createConversation().catch((error) => {
      showError(error);
      setChatStatus(error.message, "error");
    });
  });
  $("#attach-button").addEventListener("click", () => $("#attachment-input").click());
  $("#attachment-input").addEventListener("change", (event) => {
    addAttachments(event.target.files);
    event.target.value = "";
  });
  $("#chat-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = $("#message");
    const text = input.value.trim();
    if (state.chatBusy) return;
    const conversationId = state.selectedConversationId;
    if (!conversationId) {
      setChatStatus(
        "Selecciona una conversación o pulsa + Nueva antes de enviar.",
        "error",
      );
      $("#conversation-select").focus();
      return;
    }
    if (!text && !state.pendingAttachments.length) {
      setChatStatus("Escribe un mensaje o adjunta al menos un archivo.", "error");
      return;
    }
    setChatBusy(true);
    try {
      await sendChat(text, conversationId);
      input.value = "";
      state.pendingAttachments = [];
      renderAttachments();
      setChatStatus("");
    } catch (error) {
      showError(error);
      setChatStatus(error.message, "error");
    } finally {
      setChatBusy(false);
      input.focus();
    }
  });
  $("#close-confirm").addEventListener("click", () => {
    const dialog = $("#confirm-dialog");
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  });
  await refresh();
  try {
    await loadConversations();
  } catch (error) {
    showError(error);
    setChatStatus(
      "No se ha podido cargar la lista de conversaciones.",
      "error",
    );
    updateChatControls();
  }
  setInterval(() => {
    refresh();
    loadConversations().catch(() => {});
  }, 60000);
}

function showError(error) { addMessage(`No he podido completar eso: ${error.message}`); }
function showStartupError(error) {
  $("#connection").textContent = "No se ha podido iniciar";
  $("#startup-error").classList.remove("hidden");
  $("#pairing").classList.remove("hidden");
}

if ("serviceWorker" in navigator) {
  navigator.serviceWorker
    .register("/sw.js?v=9", { scope: "/" })
    .then((registration) => registration.update())
    .catch(() => {});
}
main().catch(showStartupError);
