import { fetch as expoFetch } from 'expo/fetch';
import { File } from 'expo-file-system';

import { conversationAttachmentSource } from './conversations';
import { MODEL_MODE_ENDPOINT, modelModeRequest } from './modelMode';
import type {
  ActionResult,
  AttachmentInfo,
  ChatMessage,
  ChatResponse,
  Conversation,
  ConversationListResponse,
  ConversationMessagesResponse,
  Credentials,
  DeleteConversationResponse,
  Health,
  GameStreamingStatus,
  InteractionKind,
  ModelStatus,
  RequestedModelMode,
  PcStatus,
  PetState,
  PendingAttachment,
} from './types';

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  body?: unknown;
  timeoutMs?: number;
  authenticated?: boolean;
};

type ValidationItem = {
  msg?: string;
};

export class ApiError extends Error {
  status?: number;
  kind: 'http' | 'network' | 'timeout';

  constructor(
    message: string,
    options: { status?: number; kind?: 'http' | 'network' | 'timeout' } = {},
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = options.status;
    this.kind = options.kind ?? 'http';
  }
}

function errorMessage(payload: unknown, status: number): string {
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === 'string' && detail.trim()) {
      return detail;
    }
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => (item as ValidationItem)?.msg)
        .filter((value): value is string => Boolean(value));
      if (messages.length) {
        return messages.join(' ');
      }
    }
  }
  if (status === 401) {
    return 'El emparejamiento ya no es válido. Vuelve a escanear el QR.';
  }
  return `Arfoxia respondió con el error ${status}.`;
}

function networkMessage(): string {
  return (
    'No puedo llegar a Arfoxia. Comprueba que el PC esté encendido y que ' +
    'Tailscale esté conectado en el iPhone.'
  );
}

export class ArfoxiaApi {
  constructor(readonly credentials: Credentials) {}

  private async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const {
      method = 'GET',
      body,
      timeoutMs = 12_000,
      authenticated = true,
    } = options;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    const headers: Record<string, string> = {
      Accept: 'application/json',
    };
    if (authenticated) {
      headers.Authorization = `Bearer ${this.credentials.token}`;
    }
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
    }

    try {
      const response = await expoFetch(`${this.credentials.baseUrl}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        throw new ApiError(errorMessage(payload, response.status), {
          status: response.status,
        });
      }
      return payload as T;
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
      if (controller.signal.aborted) {
        throw new ApiError('Arfoxia ha tardado demasiado en responder.', {
          kind: 'timeout',
        });
      }
      throw new ApiError(networkMessage(), { kind: 'network' });
    } finally {
      clearTimeout(timeout);
    }
  }

  health(): Promise<Health> {
    return this.request<Health>('/api/health', { authenticated: false });
  }

  state(): Promise<PetState> {
    return this.request<PetState>('/api/state');
  }

  interact(kind: InteractionKind): Promise<PetState> {
    return this.request<PetState>('/api/interact', {
      method: 'POST',
      body: { kind },
    });
  }

  chat(
    message: string,
    attachmentIds: string[],
    options: {
      conversationId: string;
      clientMessageId?: string;
      researchMode?: boolean;
    },
  ): Promise<ChatResponse> {
    return this.request<ChatResponse>('/api/chat', {
      method: 'POST',
      body: {
        message,
        attachment_ids: attachmentIds,
        conversation_id: options.conversationId,
        client_message_id: options.clientMessageId,
        research_mode: options.researchMode,
      },
      timeoutMs: 900_000,
    });
  }

  listConversations(
    options: { limit?: number; cursor?: string } = {},
  ): Promise<ConversationListResponse> {
    const params = new URLSearchParams();
    params.set('limit', String(options.limit ?? 100));
    if (options.cursor) {
      params.set('cursor', options.cursor);
    }
    return this.request<ConversationListResponse>(
      `/api/conversations?${params.toString()}`,
    );
  }

  async createConversation(title?: string): Promise<Conversation> {
    const payload = await this.request<
      Conversation | { conversation: Conversation }
    >('/api/conversations', {
      method: 'POST',
      body: title?.trim() ? { title: title.trim() } : {},
    });
    return 'conversation' in payload ? payload.conversation : payload;
  }

  async renameConversation(
    conversationId: string,
    title: string,
  ): Promise<Conversation> {
    const payload = await this.request<
      Conversation | { conversation: Conversation }
    >(`/api/conversations/${encodeURIComponent(conversationId)}`, {
      method: 'PATCH',
      body: { title: title.trim() },
    });
    return 'conversation' in payload ? payload.conversation : payload;
  }

  deleteConversation(
    conversationId: string,
  ): Promise<DeleteConversationResponse> {
    return this.request<DeleteConversationResponse>(
      `/api/conversations/${encodeURIComponent(conversationId)}`,
      {
        method: 'DELETE',
      },
    );
  }

  conversationMessages(
    conversationId: string,
    options: { limit?: number; beforeId?: string } = {},
  ): Promise<ConversationMessagesResponse> {
    const params = new URLSearchParams();
    params.set('limit', String(options.limit ?? 100));
    if (options.beforeId) {
      params.set('before_id', String(options.beforeId));
    }
    return this.request<ConversationMessagesResponse>(
      `/api/conversations/${encodeURIComponent(conversationId)}/messages?${params.toString()}`,
    );
  }

  action(action: string, args: Record<string, unknown> = {}): Promise<ActionResult> {
    return this.request<ActionResult>('/api/action', {
      method: 'POST',
      body: { action, arguments: args },
      timeoutMs: 60_000,
    });
  }

  modelStatus(): Promise<ModelStatus> {
    return this.request<ModelStatus>('/api/model/status');
  }

  setModelMode(mode: RequestedModelMode): Promise<ModelStatus> {
    return this.request<ModelStatus>(MODEL_MODE_ENDPOINT, {
      method: 'POST',
      body: modelModeRequest(mode),
      timeoutMs: 900_000,
    });
  }

  unloadModel(): Promise<{ ok: boolean }> {
    return this.request<{ ok: boolean }>('/api/model/unload', {
      method: 'POST',
      timeoutMs: 60_000,
    });
  }

  showDesktopChat(): Promise<{ ok: boolean }> {
    return this.request<{ ok: boolean }>('/api/ui/show-chat', {
      method: 'POST',
    });
  }

  gameStreamingStatus(): Promise<GameStreamingStatus> {
    return this.request<GameStreamingStatus>('/api/gaming/status');
  }

  prepareGameStreaming(): Promise<GameStreamingStatus> {
    return this.request<GameStreamingStatus>('/api/gaming/prepare', {
      method: 'POST',
      timeoutMs: 60_000,
    });
  }

  pairGameStreaming(
    pin: string,
    name = 'iPhone de Iago',
  ): Promise<ActionResult> {
    return this.request<ActionResult>('/api/gaming/pair', {
      method: 'POST',
      body: { pin, name },
      timeoutMs: 60_000,
    });
  }

  async pcStatus(): Promise<{ result: ActionResult; status: PcStatus | null }> {
    const result = await this.action('pc_status');
    return {
      result,
      status: result.data as PcStatus | null,
    };
  }

  async uploadAttachment(attachment: PendingAttachment): Promise<AttachmentInfo> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 60_000);
    const body = new FormData();
    const file = new File(attachment.uri);
    body.append('file', file, attachment.name);

    try {
      const response = await expoFetch(
        `${this.credentials.baseUrl}/api/attachments`,
        {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            Authorization: `Bearer ${this.credentials.token}`,
          },
          body,
          signal: controller.signal,
        },
      );
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        throw new ApiError(errorMessage(payload, response.status), {
          status: response.status,
        });
      }
      return payload as AttachmentInfo;
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
      if (controller.signal.aborted) {
        throw new ApiError('El archivo ha tardado demasiado en subir.', {
          kind: 'timeout',
        });
      }
      throw new ApiError(networkMessage(), { kind: 'network' });
    } finally {
      clearTimeout(timeout);
    }
  }

  screenshotSource(screenshotId: string) {
    return {
      uri: `${this.credentials.baseUrl}/api/screenshots/${encodeURIComponent(screenshotId)}`,
      headers: {
        Authorization: `Bearer ${this.credentials.token}`,
      },
    };
  }

  attachmentSource(conversationId: string, attachmentId: string) {
    return conversationAttachmentSource(
      this.credentials,
      conversationId,
      attachmentId,
    );
  }
}

export function findScreenshotId(
  response: Pick<ChatResponse, 'action_result' | 'action_results'>,
): string | null {
  const results = response.action_results ?? (response.action_result ? [response.action_result] : []);
  for (const result of results) {
    const id = result.data?.screenshot_id;
    if (typeof id === 'string' && /^[A-Za-z0-9]{16,64}$/.test(id)) {
      return id;
    }
  }
  return null;
}

export function findMessageScreenshotIds(message: ChatMessage): string[] {
  const metadata = message.metadata ?? {};
  const identifiers = new Set<string>();
  const directIds = [
    metadata.screenshot_id,
    ...(Array.isArray(metadata.screenshot_ids) ? metadata.screenshot_ids : []),
  ];
  for (const value of directIds) {
    if (typeof value === 'string' && /^[A-Za-z0-9]{16,64}$/.test(value)) {
      identifiers.add(value);
    }
  }
  const results = metadata.action_results ??
    (metadata.action_result ? [metadata.action_result] : []);
  for (const result of results) {
    const value = result.data?.screenshot_id;
    if (typeof value === 'string' && /^[A-Za-z0-9]{16,64}$/.test(value)) {
      identifiers.add(value);
    }
  }
  return [...identifiers];
}
