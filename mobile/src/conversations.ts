import type {
  ChatEntry,
  ChatMessage,
  ChatMessageMetadata,
  Conversation,
  Credentials,
  Source,
  StoredAttachment,
} from './types';

export function conversationAttachmentSource(
  credentials: Credentials,
  conversationId: string,
  attachmentId: string,
) {
  return {
    uri:
      `${credentials.baseUrl}/api/conversations/` +
      `${encodeURIComponent(conversationId)}/attachments/` +
      encodeURIComponent(attachmentId),
    headers: {
      Authorization: `Bearer ${credentials.token}`,
    },
  };
}

function validScreenshotId(value: unknown): value is string {
  return typeof value === 'string' && /^[A-Za-z0-9]{16,64}$/.test(value);
}

export function storedAttachmentId(
  attachment: StoredAttachment,
): string | null {
  const value = attachment.attachment_id ?? attachment.id;
  return typeof value === 'string' && value.trim() ? value : null;
}

export function messageScreenshotIds(message: ChatMessage): string[] {
  const metadata = message.metadata ?? {};
  const identifiers = new Set<string>();
  const direct = [
    metadata.screenshot_id,
    ...(Array.isArray(metadata.screenshot_ids) ? metadata.screenshot_ids : []),
  ];
  direct.filter(validScreenshotId).forEach((value) => identifiers.add(value));

  const actionResults = metadata.action_results ??
    (metadata.action_result ? [metadata.action_result] : []);
  for (const result of actionResults) {
    const value = result?.data?.screenshot_id;
    if (validScreenshotId(value)) {
      identifiers.add(value);
    }
  }
  return [...identifiers];
}

function metadataSources(metadata: ChatMessageMetadata | null): Source[] {
  return Array.isArray(metadata?.sources) ? metadata.sources : [];
}

export function chatMessageToEntry(message: ChatMessage): ChatEntry {
  const metadata = message.metadata ?? {};
  const attachments = Array.isArray(message.attachments)
    ? message.attachments
    : [];
  const hasPersistentScreenshot = attachments.some(
    (attachment) =>
      attachment.kind === 'screenshot' ||
      attachment.name.toLowerCase().startsWith('captura-arfoxia-'),
  );
  return {
    id: message.id,
    role: message.role,
    text: message.content,
    attachmentNames: attachments.map((attachment) => attachment.name),
    attachments,
    sources: metadataSources(message.metadata),
    model: typeof metadata.model === 'string' ? metadata.model : null,
    modelMode:
      typeof metadata.model_mode === 'string'
        ? metadata.model_mode
        : undefined,
    createdAt: message.created_at,
    screenshotIds: hasPersistentScreenshot ? [] : messageScreenshotIds(message),
  };
}

export function mergeMessages(
  current: ChatMessage[],
  incoming: ChatMessage[],
  mode: 'replace' | 'prepend' | 'append',
): ChatMessage[] {
  const ordered =
    mode === 'replace'
      ? incoming
      : mode === 'prepend'
        ? [...incoming, ...current]
        : [...current, ...incoming];
  const output: ChatMessage[] = [];
  const indexes = new Map<string, number>();
  for (const message of ordered) {
    const existing = indexes.get(message.id);
    if (existing === undefined) {
      indexes.set(message.id, output.length);
      output.push(message);
    } else {
      output[existing] = message;
    }
  }
  return output;
}

export function reconcileLocalEntries(
  entries: ChatEntry[],
  messages: ChatMessage[],
): ChatEntry[] {
  const confirmedClientIds = new Set(
    messages
      .map((message) => message.client_message_id)
      .filter((value): value is string => Boolean(value)),
  );
  if (!confirmedClientIds.size) {
    return entries;
  }
  return entries.filter(
    (entry) =>
      !entry.clientMessageId ||
      !confirmedClientIds.has(entry.clientMessageId),
  );
}

export function upsertConversation(
  conversations: Conversation[],
  value: Conversation,
): Conversation[] {
  const without = conversations.filter((item) => item.id !== value.id);
  return [value, ...without].sort((left, right) => {
    const byPinned = Number(Boolean(right.pinned)) - Number(Boolean(left.pinned));
    if (byPinned) {
      return byPinned;
    }
    const byDate = right.updated_at.localeCompare(left.updated_at);
    return byDate || right.id.localeCompare(left.id);
  });
}

export function conversationsAfterDelete(
  conversations: Conversation[],
  deletedId: string,
  replacement?: Conversation | null,
): Conversation[] {
  const remaining = conversations.filter((item) => item.id !== deletedId);
  if (!replacement || replacement.id === deletedId) {
    return remaining;
  }
  return upsertConversation(remaining, replacement);
}

export type ConversationSelectionDecision =
  | { kind: 'keep' }
  | { kind: 'select'; id: string }
  | { kind: 'clear' };

export function conversationSelectionAfterList(
  currentId: string | null,
  incoming: Conversation[],
  options: {
    append?: boolean;
    preserveExisting?: boolean;
    selectDefault?: boolean;
  } = {},
): ConversationSelectionDecision {
  if (options.append) {
    return { kind: 'keep' };
  }
  if (
    currentId &&
    (options.preserveExisting ||
      incoming.some((conversation) => conversation.id === currentId))
  ) {
    return { kind: 'keep' };
  }
  if (options.selectDefault !== false && incoming.length) {
    return { kind: 'select', id: incoming[0].id };
  }
  if (!incoming.length && !options.preserveExisting) {
    return { kind: 'clear' };
  }
  return { kind: 'keep' };
}

export function createClientMessageId(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
    const random = Math.floor(Math.random() * 16);
    const value = char === 'x' ? random : (random & 0x3) | 0x8;
    return value.toString(16);
  });
}
