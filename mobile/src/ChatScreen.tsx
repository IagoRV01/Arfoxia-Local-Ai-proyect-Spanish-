import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  AppState,
  FlatList,
  KeyboardAvoidingView,
  Linking,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  type StyleProp,
  Text,
  TextInput,
  type ViewStyle,
  View,
} from 'react-native';
import * as DocumentPicker from 'expo-document-picker';
import { File } from 'expo-file-system';
import * as ImageManipulator from 'expo-image-manipulator';
import * as ImagePicker from 'expo-image-picker';
import Markdown, {
  MarkdownIt,
  type RenderRules,
} from 'react-native-markdown-renderer';

import { ApiError, ArfoxiaApi, findScreenshotId } from './api';
import { ConversationListModal } from './ConversationListModal';
import { MarkdownCodeBlock, codeFontFamily } from './MarkdownCodeBlock';
import {
  chatMessageToEntry,
  conversationsAfterDelete,
  conversationSelectionAfterList,
  createClientMessageId,
  mergeMessages,
  reconcileLocalEntries,
  storedAttachmentId,
  upsertConversation,
} from './conversations';
import { isSafeSourceUrl } from './pairing';
import {
  containsMarkdownTable,
  markdownTableCellWidth,
  markdownTableContentWidth,
} from './markdownTableLayout';
import type {
  ChatEntry,
  ChatMessage,
  Conversation,
  ConversationStorage,
  PendingAttachment,
  StoredAttachment,
} from './types';
import {
  Button,
  EmptyState,
  ErrorBanner,
  ScreenshotModal,
  colors,
  sharedStyles,
} from './ui';

type Props = {
  api: ArfoxiaApi;
  onUnauthorized: () => void;
  active?: boolean;
};

type MediaPreview = {
  source: { uri: string; headers: Record<string, string> };
  title: string;
  hint: string;
};

const MAX_ATTACHMENTS = 4;
const MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024;
const MAX_TOTAL_BYTES = 16 * 1024 * 1024;
const CONVERSATION_PAGE_SIZE = 100;
const HISTORY_PAGE_SIZE = 100;
const SYNC_INTERVAL_MS = 8_000;
const allowedExtensions = new Set([
  'png',
  'jpg',
  'jpeg',
  'webp',
  'pdf',
  'txt',
  'md',
  'markdown',
  'csv',
  'json',
  'jsonl',
  'py',
  'js',
  'mjs',
  'cjs',
  'ts',
  'tsx',
  'jsx',
  'html',
  'htm',
  'css',
  'xml',
  'yaml',
  'yml',
  'toml',
  'ini',
  'cfg',
  'log',
  'sql',
  'ps1',
  'bat',
]);
const allowedMediaTypes = new Set([
  'image/png',
  'image/jpeg',
  'image/webp',
  'application/pdf',
  'application/json',
  'application/ld+json',
  'application/x-ndjson',
  'application/javascript',
  'application/xml',
  'application/yaml',
]);

function newId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function extension(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : '';
}

function isAllowed(name: string, mimeType: string): boolean {
  return (
    mimeType.toLowerCase().startsWith('text/') ||
    allowedMediaTypes.has(mimeType.toLowerCase()) ||
    allowedExtensions.has(extension(name))
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${Math.round(bytes / 1024)} KiB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

function safeImageName(name: string | null | undefined): string {
  const base = (name || `imagen-${Date.now()}`).replace(/\.[^.]+$/, '');
  return `${base}.jpg`;
}

function friendlyTime(value?: string): string {
  if (!value) {
    return '';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  return date.toLocaleTimeString('es-ES', {
    hour: '2-digit',
    minute: '2-digit',
  });
}

function attachmentIsPreviewable(attachment: StoredAttachment): boolean {
  return (
    attachment.kind === 'image' ||
    attachment.kind === 'screenshot' ||
    attachment.media_type.startsWith('image/')
  );
}

export function ChatScreen({
  api,
  onUnauthorized,
  active = true,
}: Props) {
  const list = useRef<FlatList<ChatEntry>>(null);
  const selectedIdRef = useRef<string | null>(null);
  const nextConversationCursorRef = useRef<string | null>(null);
  const shouldScrollToEnd = useRef(false);
  const loadGeneration = useRef(0);
  const conversationListGeneration = useRef(0);
  const sendInFlightRef = useRef(false);
  const createInFlightRef = useRef<Promise<void> | null>(null);

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationStorage, setConversationStorage] =
    useState<ConversationStorage>();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [localEntries, setLocalEntries] = useState<ChatEntry[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [nextBeforeId, setNextBeforeId] = useState<string | null>(null);
  const [listOpen, setListOpen] = useState(false);
  const [loadingConversations, setLoadingConversations] = useState(true);
  const [loadingMoreConversations, setLoadingMoreConversations] =
    useState(false);
  const [refreshingConversations, setRefreshingConversations] = useState(false);
  const [nextConversationCursor, setNextConversationCursor] =
    useState<string | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [refreshingHistory, setRefreshingHistory] = useState(false);

  const [message, setMessage] = useState('');
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [intensive, setIntensive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [offline, setOffline] = useState(false);
  const [mediaPreview, setMediaPreview] = useState<MediaPreview | null>(null);

  const selectedConversation = useMemo(
    () => conversations.find((item) => item.id === selectedId) ?? null,
    [conversations, selectedId],
  );
  const entries = useMemo(
    () => [...messages.map(chatMessageToEntry), ...localEntries],
    [localEntries, messages],
  );
  const totalBytes = useMemo(
    () => attachments.reduce((total, attachment) => total + attachment.size, 0),
    [attachments],
  );
  const composerDisabled = busy || !selectedConversation;

  const handleError = useCallback(
    (reason: unknown, fallback: string): boolean => {
      if (reason instanceof ApiError && reason.status === 401) {
        onUnauthorized();
        return true;
      }
      if (
        reason instanceof ApiError &&
        (reason.kind === 'network' || reason.kind === 'timeout')
      ) {
        setOffline(true);
      }
      setError(reason instanceof Error ? reason.message : fallback);
      return false;
    },
    [onUnauthorized],
  );

  const loadConversation = useCallback(
    async (
      conversationId: string,
      options: { quiet?: boolean; refresh?: boolean } = {},
    ) => {
      const generation = options.quiet
        ? loadGeneration.current
        : ++loadGeneration.current;
      if (!options.quiet) {
        setLoadingHistory(true);
        setMessages([]);
        setLocalEntries([]);
        setHasMore(false);
        setNextBeforeId(null);
      } else if (options.refresh) {
        setRefreshingHistory(true);
      }
      try {
        const result = await api.conversationMessages(conversationId, {
          limit: HISTORY_PAGE_SIZE,
        });
        if (
          selectedIdRef.current !== conversationId ||
          (!options.quiet && loadGeneration.current !== generation)
        ) {
          return;
        }
        const incoming = Array.isArray(result.messages) ? result.messages : [];
        setMessages((current) =>
          mergeMessages(
            options.quiet ? current : [],
            incoming,
            options.quiet ? 'append' : 'replace',
          ),
        );
        setLocalEntries((current) =>
          reconcileLocalEntries(current, incoming),
        );
        setConversations((current) =>
          result.conversation
            ? upsertConversation(current, result.conversation)
            : current,
        );
        if (!options.quiet) {
          setHasMore(Boolean(result.has_more));
          setNextBeforeId(result.next_before_id ?? null);
          shouldScrollToEnd.current = true;
        }
        setOffline(false);
        setError('');
      } catch (reason) {
        if (
          reason instanceof ApiError &&
          reason.status === 404 &&
          selectedIdRef.current === conversationId
        ) {
          setConversations((current) =>
            current.filter((item) => item.id !== conversationId),
          );
          setSelectedId(null);
          selectedIdRef.current = null;
          setMessages([]);
          setLocalEntries([]);
          setError(
            'Esta conversación se eliminó en otro dispositivo. Elige otro chat.',
          );
          return;
        }
        handleError(reason, 'No se ha podido cargar la conversación.');
      } finally {
        if (!options.quiet) {
          setLoadingHistory(false);
        }
        if (options.refresh) {
          setRefreshingHistory(false);
        }
      }
    },
    [api, handleError],
  );

  const selectConversation = useCallback(
    (conversation: Conversation) => {
      selectedIdRef.current = conversation.id;
      setSelectedId(conversation.id);
      setAttachments([]);
      setMessage('');
      setError('');
      void loadConversation(conversation.id);
    },
    [loadConversation],
  );

  const loadConversationList = useCallback(
    async (
      options: {
        refreshing?: boolean;
        selectDefault?: boolean;
        append?: boolean;
        preserveExisting?: boolean;
      } = {},
    ) => {
      if (options.append && !nextConversationCursorRef.current) {
        return;
      }
      const generation = ++conversationListGeneration.current;
      if (options.refreshing) {
        setRefreshingConversations(true);
      }
      if (options.append) {
        setLoadingMoreConversations(true);
      }
      try {
        const result = await api.listConversations({
          limit: CONVERSATION_PAGE_SIZE,
          cursor: options.append
            ? nextConversationCursorRef.current ?? undefined
            : undefined,
        });
        if (conversationListGeneration.current !== generation) {
          return;
        }
        const next = Array.isArray(result.conversations)
          ? result.conversations
          : [];
        setConversations((current) => {
          if (!options.append && !options.preserveExisting) {
            return next;
          }
          const incomingIds = new Set(next.map((item) => item.id));
          return [
            ...next,
            ...current.filter((item) => !incomingIds.has(item.id)),
          ];
        });
        nextConversationCursorRef.current = result.next_cursor ?? null;
        setNextConversationCursor(nextConversationCursorRef.current);
        setConversationStorage(result.storage);
        setOffline(false);
        setError('');

        const selection = conversationSelectionAfterList(
          selectedIdRef.current,
          next,
          options,
        );
        if (selection.kind === 'select') {
          selectedIdRef.current = selection.id;
          setSelectedId(selection.id);
          void loadConversation(selection.id);
        } else if (selection.kind === 'clear') {
          selectedIdRef.current = null;
          setSelectedId(null);
          setMessages([]);
          setLocalEntries([]);
        }
      } catch (reason) {
        if (conversationListGeneration.current !== generation) {
          return;
        }
        handleError(reason, 'No se ha podido cargar la lista de conversaciones.');
      } finally {
        if (conversationListGeneration.current === generation) {
          setLoadingConversations(false);
          setLoadingMoreConversations(false);
          setRefreshingConversations(false);
        }
      }
    },
    [api, handleError, loadConversation],
  );

  useEffect(() => {
    void loadConversationList();
  }, [loadConversationList]);

  useEffect(() => {
    if (!active) {
      return;
    }
    const sync = () => {
      const currentId = selectedIdRef.current;
      void loadConversationList({
        selectDefault: !currentId,
        preserveExisting: true,
      });
      if (currentId && !busy) {
        void loadConversation(currentId, { quiet: true });
      }
    };
    const timer = setInterval(sync, SYNC_INTERVAL_MS);
    const subscription = AppState.addEventListener('change', (next) => {
      if (next === 'active') {
        sync();
      }
    });
    return () => {
      clearInterval(timer);
      subscription.remove();
    };
  }, [active, busy, loadConversation, loadConversationList]);

  const createConversation = useCallback(async () => {
    if (createInFlightRef.current) {
      return createInFlightRef.current;
    }
    if (sendInFlightRef.current) {
      setError('Espera a que Arfoxia termine de responder antes de crear otro chat.');
      return;
    }
    const operation = (async () => {
      setError('');
      try {
        const created = await api.createConversation();
        setConversations((current) => upsertConversation(current, created));
        selectConversation(created);
        setOffline(false);
      } catch (reason) {
        handleError(reason, 'No se ha podido crear la conversación.');
        throw reason;
      }
    })();
    createInFlightRef.current = operation;
    try {
      await operation;
    } finally {
      if (createInFlightRef.current === operation) {
        createInFlightRef.current = null;
      }
    }
  }, [api, handleError, selectConversation]);

  const renameConversation = useCallback(
    async (conversation: Conversation, title: string) => {
      setError('');
      try {
        const updated = await api.renameConversation(conversation.id, title);
        setConversations((current) => upsertConversation(current, updated));
        setOffline(false);
      } catch (reason) {
        handleError(reason, 'No se ha podido renombrar la conversación.');
        throw reason;
      }
    },
    [api, handleError],
  );

  const deleteConversation = useCallback(
    async (conversation: Conversation) => {
      setError('');
      try {
        const result = await api.deleteConversation(conversation.id);
        const remaining = conversationsAfterDelete(
          conversations,
          conversation.id,
          result.replacement,
        );
        setConversations(remaining);
        if (selectedIdRef.current === conversation.id) {
          setMessages([]);
          setLocalEntries([]);
          setAttachments([]);
          if (remaining.length) {
            selectConversation(remaining[0]);
          } else {
            selectedIdRef.current = null;
            setSelectedId(null);
          }
        }
        setOffline(false);
      } catch (reason) {
        handleError(reason, 'No se ha podido eliminar la conversación.');
        throw reason;
      }
    },
    [api, conversations, handleError, selectConversation],
  );

  const loadOlder = useCallback(async () => {
    const conversationId = selectedIdRef.current;
    if (!conversationId || !nextBeforeId || loadingOlder) {
      return;
    }
    setLoadingOlder(true);
    try {
      const result = await api.conversationMessages(conversationId, {
        limit: HISTORY_PAGE_SIZE,
        beforeId: nextBeforeId,
      });
      if (selectedIdRef.current !== conversationId) {
        return;
      }
      setMessages((current) =>
        mergeMessages(
          current,
          Array.isArray(result.messages) ? result.messages : [],
          'prepend',
        ),
      );
      setHasMore(Boolean(result.has_more));
      setNextBeforeId(result.next_before_id ?? null);
      setOffline(false);
      setError('');
    } catch (reason) {
      handleError(reason, 'No se han podido cargar los mensajes anteriores.');
    } finally {
      setLoadingOlder(false);
    }
  }, [api, handleError, loadingOlder, nextBeforeId]);

  const reportAttachmentError = useCallback((reason: unknown) => {
    const text =
      reason instanceof Error
        ? reason.message
        : 'No se ha podido preparar el archivo.';
    setError(text);
    Alert.alert('No se puede adjuntar', text);
  }, []);

  const appendAttachments = useCallback(
    (incoming: PendingAttachment[]) => {
      setError('');
      const next = [...attachments];
      for (const attachment of incoming) {
        if (next.length >= MAX_ATTACHMENTS) {
          throw new Error(
            `Solo puedes adjuntar ${MAX_ATTACHMENTS} archivos por mensaje.`,
          );
        }
        if (!attachment.size) {
          throw new Error(`«${attachment.name}» está vacío.`);
        }
        if (attachment.size > MAX_ATTACHMENT_BYTES) {
          throw new Error(`«${attachment.name}» supera el límite de 8 MiB.`);
        }
        if (!isAllowed(attachment.name, attachment.mimeType)) {
          throw new Error(
            `«${attachment.name}» no es una imagen, PDF, texto o archivo de código compatible.`,
          );
        }
        const nextTotal = next.reduce((sum, item) => sum + item.size, 0);
        if (nextTotal + attachment.size > MAX_TOTAL_BYTES) {
          throw new Error('Los adjuntos de un mensaje no pueden superar 16 MiB.');
        }
        const duplicate = next.some(
          (item) =>
            item.name === attachment.name && item.size === attachment.size,
        );
        if (!duplicate) {
          next.push(attachment);
        }
      }
      setAttachments(next);
    },
    [attachments],
  );

  const pickImages = useCallback(async () => {
    if (busy || attachments.length >= MAX_ATTACHMENTS) {
      return;
    }
    try {
      const permission =
        await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!permission.granted) {
        throw new Error(
          'Activa el permiso de Fotos para seleccionar una imagen.',
        );
      }
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ['images'],
        allowsMultipleSelection: true,
        selectionLimit: MAX_ATTACHMENTS - attachments.length,
        quality: 1,
      });
      if (result.canceled) {
        return;
      }
      setStatus('Preparando las imágenes…');
      const prepared: PendingAttachment[] = [];
      for (const asset of result.assets) {
        const normalized = await ImageManipulator.manipulateAsync(
          asset.uri,
          [],
          {
            compress: 0.88,
            format: ImageManipulator.SaveFormat.JPEG,
          },
        );
        const file = new File(normalized.uri);
        prepared.push({
          id: newId(),
          uri: normalized.uri,
          name: safeImageName(asset.fileName),
          mimeType: 'image/jpeg',
          size: file.size,
        });
      }
      appendAttachments(prepared);
    } catch (reason) {
      reportAttachmentError(reason);
    } finally {
      setStatus('');
    }
  }, [appendAttachments, attachments.length, busy, reportAttachmentError]);

  const pickDocuments = useCallback(async () => {
    if (busy || attachments.length >= MAX_ATTACHMENTS) {
      return;
    }
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: '*/*',
        multiple: true,
        copyToCacheDirectory: true,
      });
      if (result.canceled) {
        return;
      }
      const remaining = MAX_ATTACHMENTS - attachments.length;
      const prepared = result.assets.slice(0, remaining).map((asset) => {
        const file = new File(asset.uri);
        return {
          id: newId(),
          uri: asset.uri,
          name: asset.name,
          mimeType: asset.mimeType || 'application/octet-stream',
          size: asset.size ?? file.size,
        };
      });
      appendAttachments(prepared);
      if (result.assets.length > remaining) {
        Alert.alert(
          'Límite de adjuntos',
          `Se han añadido los primeros ${remaining} archivos. El máximo es ${MAX_ATTACHMENTS}.`,
        );
      }
    } catch (reason) {
      reportAttachmentError(reason);
    }
  }, [appendAttachments, attachments.length, busy, reportAttachmentError]);

  const send = useCallback(async () => {
    const typedMessage = message.trim();
    const selected = [...attachments];
    if (
      (!typedMessage && !selected.length) ||
      busy ||
      sendInFlightRef.current
    ) {
      return;
    }
    const conversationId = selectedIdRef.current;
    if (!conversationId) {
      setError(
        'Selecciona una conversación o pulsa + para crear una nueva antes de enviar.',
      );
      setListOpen(true);
      void loadConversationList({
        selectDefault: true,
        preserveExisting: true,
      });
      return;
    }

    sendInFlightRef.current = true;
    setBusy(true);
    setError('');
    setMessage('');

    let uploadedCount = 0;
    const clientMessageId = createClientMessageId();
    const localId = `local:${clientMessageId}`;
    setLocalEntries((current) => [
      ...current,
      {
        id: localId,
        role: 'user',
        text: typedMessage || 'Analiza estos archivos.',
        attachmentNames: selected.map((attachment) => attachment.name),
        clientMessageId,
        delivery: 'sending',
      },
    ]);
    shouldScrollToEnd.current = true;

    try {
      const attachmentIds: string[] = [];
      for (let index = 0; index < selected.length; index += 1) {
        setStatus(
          `Subiendo ${index + 1} de ${selected.length}: ${selected[index].name}…`,
        );
        const uploaded = await api.uploadAttachment(selected[index]);
        attachmentIds.push(uploaded.attachment_id);
        uploadedCount += 1;
      }

      setStatus(
        selected.length
          ? 'Arfoxia está revisando el mensaje y los archivos…'
          : intensive
            ? 'Arfoxia está investigando y contrastando fuentes…'
            : 'Arfoxia está pensando…',
      );
      const response = await api.chat(typedMessage, attachmentIds, {
        conversationId,
        clientMessageId,
        researchMode: intensive || undefined,
      });
      const responseConversationId =
        response.conversation?.id ??
        response.user_message?.conversation_id ??
        response.assistant_message?.conversation_id;
      if (
        responseConversationId &&
        responseConversationId !== conversationId
      ) {
        throw new Error(
          'La respuesta llegó asociada a otra conversación y no se ha mezclado con este chat.',
        );
      }
      const stillSelected = selectedIdRef.current === conversationId;
      if (stillSelected) {
        setAttachments([]);
        setLocalEntries((current) =>
          current.filter((entry) => entry.id !== localId),
        );
      }

      const canonical = [
        response.user_message,
        response.assistant_message,
      ].filter((item): item is ChatMessage => Boolean(item));
      if (canonical.length && stillSelected) {
        setMessages((current) => mergeMessages(current, canonical, 'append'));
      } else if (stillSelected) {
        setLocalEntries((current) => [
          ...current,
          {
            id: `legacy-user:${clientMessageId}`,
            role: 'user',
            text: typedMessage || 'Analiza estos archivos.',
            attachmentNames: selected.map((attachment) => attachment.name),
          },
          {
            id: `legacy-assistant:${clientMessageId}`,
            role: 'assistant',
            text: response.message,
            sources: response.sources?.filter((source) =>
              isSafeSourceUrl(source.url),
            ),
            model: response.model,
            modelMode: response.model_mode,
          },
        ]);
      }
      if (response.conversation) {
        setConversations((current) =>
          upsertConversation(current, response.conversation as Conversation),
        );
      }
      shouldScrollToEnd.current = stillSelected;

      const screenshot = findScreenshotId(response);
      if (stillSelected && screenshot && !response.assistant_message) {
        setMediaPreview({
          source: api.screenshotSource(screenshot),
          title: 'Monitor principal',
          hint: 'Captura privada guardada por Arfoxia.',
        });
      }
      if (response.requires_authorization) {
        Alert.alert(
          'Autorización en el PC',
          'Arfoxia necesita que termines esta autorización en el diálogo privado del ordenador.',
        );
      }
      setOffline(false);
      setError('');
      void loadConversationList({ selectDefault: false });
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) {
        onUnauthorized();
        return;
      }
      handleError(reason, 'No se ha podido enviar el mensaje.');
      const uncertain =
        reason instanceof ApiError &&
        (reason.kind === 'network' || reason.kind === 'timeout');
      if (selectedIdRef.current === conversationId) {
        if (uploadedCount) {
          setAttachments([]);
        } else if (!uncertain) {
          setMessage(typedMessage);
        }
        setLocalEntries((current) =>
          current.map((entry) =>
            entry.id === localId
              ? {
                  ...entry,
                  delivery: uncertain ? 'uncertain' : 'failed',
                }
              : entry,
          ),
        );
      }
    } finally {
      sendInFlightRef.current = false;
      setBusy(false);
      setStatus('');
    }
  }, [
    api,
    attachments,
    busy,
    handleError,
    intensive,
    loadConversationList,
    message,
    onUnauthorized,
  ]);

  const openStoredAttachment = useCallback(
    (attachment: StoredAttachment) => {
      const identifier = storedAttachmentId(attachment);
      const conversationId = selectedIdRef.current;
      if (!identifier || !conversationId) {
        return;
      }
      if (!attachmentIsPreviewable(attachment)) {
        Alert.alert(
          attachment.name,
          `Este archivo está guardado en el historial del PC (${formatBytes(attachment.size)}).`,
        );
        return;
      }
      setMediaPreview({
        source: api.attachmentSource(conversationId, identifier),
        title: attachment.name,
        hint: 'Adjunto recuperado del historial privado de Arfoxia.',
      });
    },
    [api],
  );

  const openMarkdownLink = useCallback((url: string) => {
    if (!isSafeSourceUrl(url)) {
      return false;
    }
    void Linking.openURL(url).catch(() => {
      Alert.alert(
        'No se pudo abrir el enlace',
        'Comprueba la conexión e inténtalo de nuevo.',
      );
    });
    return false;
  }, []);

  const renderEntry = useCallback(
    ({ item }: { item: ChatEntry }) => {
      const mine = item.role === 'user';
      const system = item.role === 'system';
      const hasTable = containsMarkdownTable(item.text);
      const hasCode = safeMarkdownIt.parse(item.text, {}).some(
        (token: { type: string }) => token.type === 'fence' || token.type === 'code_block',
      );
      return (
        <View
          style={[
            styles.bubble,
            mine && styles.bubbleMine,
            system && styles.bubbleSystem,
            (hasTable || hasCode) && styles.bubbleTable,
          ]}
        >
          {!mine && !system ? (
            <Text style={styles.speaker}>Arfoxia</Text>
          ) : null}
          <Markdown
            markdownit={safeMarkdownIt}
            rules={safeMarkdownRules}
            style={mine ? markdownStylesMine : markdownStylesAssistant}
            onLinkPress={openMarkdownLink}
          >
            {item.text}
          </Markdown>
          {item.attachments?.length ? (
            <View style={styles.sentFiles}>
              {item.attachments.map((attachment, index) => {
                const previewable =
                  attachmentIsPreviewable(attachment) &&
                  Boolean(storedAttachmentId(attachment));
                return (
                  <Pressable
                    key={`${storedAttachmentId(attachment) ?? attachment.name}-${index}`}
                    disabled={!previewable}
                    onPress={() => openStoredAttachment(attachment)}
                    style={[
                      styles.storedFile,
                      mine && styles.storedFileMine,
                    ]}
                  >
                    <Text
                      style={[
                        styles.sentFile,
                        mine && styles.sentFileMine,
                      ]}
                      numberOfLines={1}
                    >
                      ◇ {attachment.name}
                    </Text>
                    <Text
                      style={[
                        styles.storedFileMeta,
                        mine && styles.sentFileMine,
                      ]}
                    >
                      {formatBytes(attachment.size)}
                      {previewable ? ' · ver' : ''}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          ) : item.attachmentNames?.length ? (
            <View style={styles.sentFiles}>
              {item.attachmentNames.map((name) => (
                <Text
                  key={name}
                  style={[styles.sentFile, mine && styles.sentFileMine]}
                >
                  ◇ {name}
                </Text>
              ))}
            </View>
          ) : null}
          {item.screenshotIds?.length ? (
            <View style={styles.screenshotActions}>
              {item.screenshotIds.map((identifier, index) => (
                <Button
                  key={identifier}
                  label={
                    item.screenshotIds?.length === 1
                      ? 'Ver captura'
                      : `Ver captura ${index + 1}`
                  }
                  icon="▣"
                  variant="ghost"
                  compact
                  onPress={() =>
                    setMediaPreview({
                      source: api.screenshotSource(identifier),
                      title: 'Monitor principal',
                      hint: 'Captura privada guardada por Arfoxia.',
                    })
                  }
                />
              ))}
            </View>
          ) : null}
          {item.model || item.modelMode ? (
            <Text style={styles.modelMeta}>
              {[item.modelMode, item.model].filter(Boolean).join(' · ')}
            </Text>
          ) : null}
          {item.sources?.length ? (
            <View style={styles.sources}>
              <Text style={styles.sourcesTitle}>Fuentes consultadas</Text>
              {item.sources
                .filter((source) => isSafeSourceUrl(source.url))
                .slice(0, 12)
                .map((source, index) => (
                  <Pressable
                    key={`${source.url}-${index}`}
                    accessibilityRole="link"
                    onPress={() => void Linking.openURL(source.url)}
                    style={styles.sourceLink}
                  >
                    <Text style={styles.sourceText} numberOfLines={2}>
                      {source.title || source.url}
                    </Text>
                    <Text style={styles.sourceArrow}>↗</Text>
                  </Pressable>
                ))}
            </View>
          ) : null}
          {item.delivery ? (
            <Text
              style={[
                styles.delivery,
                item.delivery === 'failed' && styles.deliveryFailed,
              ]}
            >
              {item.delivery === 'sending'
                ? 'Enviando…'
                : item.delivery === 'uncertain'
                  ? 'Sin confirmar · se comprobará al reconectar'
                  : 'No se ha podido confirmar el envío'}
            </Text>
          ) : friendlyTime(item.createdAt) ? (
            <Text
              style={[
                styles.messageTime,
                mine && styles.messageTimeMine,
              ]}
            >
              {friendlyTime(item.createdAt)}
            </Text>
          ) : null}
        </View>
      );
    },
    [api, openMarkdownLink, openStoredAttachment],
  );

  return (
    <KeyboardAvoidingView
      style={styles.page}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={8}
    >
      <View style={styles.header}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Abrir conversaciones"
          disabled={busy}
          onPress={() => setListOpen(true)}
          style={({ pressed }) => [
            styles.headerButton,
            pressed && styles.headerButtonPressed,
            busy && styles.headerButtonDisabled,
          ]}
        >
          <Text style={styles.headerButtonIcon}>☰</Text>
        </Pressable>
        <View style={styles.headerTitle}>
          <Text style={sharedStyles.label}>Historial compartido</Text>
          <Text style={styles.title} numberOfLines={1}>
            {selectedConversation?.title || 'Hablar con Arfoxia'}
          </Text>
        </View>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Nueva conversación"
          disabled={busy}
          onPress={() => void createConversation().catch(() => {})}
          style={({ pressed }) => [
            styles.headerButton,
            pressed && styles.headerButtonPressed,
            busy && styles.headerButtonDisabled,
          ]}
        >
          <Text style={styles.headerButtonIcon}>＋</Text>
        </Pressable>
      </View>

      {offline ? (
        <View style={styles.offlineBanner}>
          <Text style={styles.offlineText}>
            Sin conexión · el historial visible sigue disponible y se
            sincronizará al volver el PC.
          </Text>
        </View>
      ) : null}
      {error ? (
        <View style={styles.bannerWrap}>
          <ErrorBanner message={error} />
        </View>
      ) : null}

      {loadingHistory || (loadingConversations && !selectedId) ? (
        <View style={styles.historyLoading}>
          <ActivityIndicator color={colors.ice} />
          <Text style={styles.historyLoadingText}>Cargando conversación…</Text>
        </View>
      ) : (
        <FlatList
          ref={list}
          data={entries}
          renderItem={renderEntry}
          keyExtractor={(item) => item.id}
          contentContainerStyle={[
            styles.messages,
            !entries.length && styles.emptyMessages,
          ]}
          ItemSeparatorComponent={() => <View style={styles.messageGap} />}
          ListEmptyComponent={
            <EmptyState
              icon="✦"
              title={
                selectedConversation
                  ? 'Empieza este chat'
                  : 'Crea una conversación'
              }
              detail={
                selectedConversation
                  ? 'Escribe un mensaje, envía un archivo o pide una investigación.'
                  : 'Pulsa el botón + para crear tu primer chat con Arfoxia.'
              }
            />
          }
          ListHeaderComponent={
            hasMore ? (
              <View style={styles.olderWrap}>
                <Button
                  label="Cargar mensajes anteriores"
                  variant="ghost"
                  compact
                  busy={loadingOlder}
                  onPress={() => void loadOlder()}
                />
              </View>
            ) : null
          }
          refreshControl={
            <RefreshControl
              refreshing={refreshingHistory}
              onRefresh={() => {
                const currentId = selectedIdRef.current;
                if (currentId) {
                  void loadConversation(currentId, {
                    quiet: true,
                    refresh: true,
                  });
                } else {
                  void loadConversationList({ refreshing: true });
                }
              }}
              tintColor={colors.ice}
            />
          }
          maintainVisibleContentPosition={{ minIndexForVisible: 0 }}
          showsVerticalScrollIndicator={false}
          onContentSizeChange={() => {
            if (shouldScrollToEnd.current) {
              shouldScrollToEnd.current = false;
              list.current?.scrollToEnd({ animated: false });
            }
          }}
        />
      )}

      <View style={styles.composer}>
        {attachments.length ? (
          <View style={styles.attachmentPanel}>
            <View style={styles.attachmentSummary}>
              <Text style={styles.attachmentSummaryText}>
                {attachments.length} de {MAX_ATTACHMENTS} ·{' '}
                {formatBytes(totalBytes)}
              </Text>
            </View>
            <View style={styles.attachmentList}>
              {attachments.map((attachment) => (
                <View key={attachment.id} style={styles.attachmentChip}>
                  <Text style={styles.attachmentName} numberOfLines={1}>
                    {attachment.name}
                  </Text>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`Quitar ${attachment.name}`}
                    disabled={busy}
                    onPress={() =>
                      setAttachments((current) =>
                        current.filter((item) => item.id !== attachment.id),
                      )
                    }
                  >
                    <Text style={styles.remove}>×</Text>
                  </Pressable>
                </View>
              ))}
            </View>
          </View>
        ) : null}

        <View style={styles.composerTools}>
          <View style={styles.addTools}>
            <Button
              label="Imagen"
              icon="▧"
              variant="ghost"
              compact
              disabled={
                composerDisabled || attachments.length >= MAX_ATTACHMENTS
              }
              onPress={() => void pickImages()}
            />
            <Button
              label="Archivo"
              icon="◇"
              variant="ghost"
              compact
              disabled={
                composerDisabled || attachments.length >= MAX_ATTACHMENTS
              }
              onPress={() => void pickDocuments()}
            />
          </View>
          <Pressable
            accessibilityRole="switch"
            accessibilityState={{ checked: intensive }}
            disabled={composerDisabled}
            onPress={() => setIntensive((value) => !value)}
            style={[
              styles.researchToggle,
              intensive && styles.researchToggleOn,
            ]}
          >
            <View
              style={[styles.toggleDot, intensive && styles.toggleDotOn]}
            />
            <Text
              style={[
                styles.researchText,
                intensive && styles.researchTextOn,
              ]}
            >
              Investigación
            </Text>
          </Pressable>
        </View>

        <View style={styles.inputRow}>
          <TextInput
            value={message}
            onChangeText={setMessage}
            editable={!composerDisabled}
            maxLength={1200}
            multiline
            placeholder={
              selectedConversation
                ? 'Escribe a Arfoxia…'
                : 'Selecciona un chat o pulsa + para crear uno…'
            }
            placeholderTextColor="#7191A2"
            style={styles.input}
          />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Enviar mensaje"
            disabled={
              composerDisabled || (!message.trim() && !attachments.length)
            }
            onPress={() => void send()}
            style={({ pressed }) => [
              styles.send,
              (composerDisabled ||
                (!message.trim() && !attachments.length)) &&
                styles.sendDisabled,
              pressed && styles.sendPressed,
            ]}
          >
            <Text style={styles.sendText}>{busy ? '…' : '↑'}</Text>
          </Pressable>
        </View>
        {status ? <Text style={styles.status}>{status}</Text> : null}
      </View>

      <ConversationListModal
        visible={listOpen}
        conversations={conversations}
        storage={conversationStorage}
        selectedId={selectedId}
        loading={loadingConversations}
        loadingMore={loadingMoreConversations}
        hasMore={Boolean(nextConversationCursor)}
        refreshing={refreshingConversations}
        error={error}
        onClose={() => setListOpen(false)}
        onRefresh={() =>
          void loadConversationList({
            refreshing: true,
            selectDefault: false,
            preserveExisting: true,
          })
        }
        onLoadMore={() =>
          void loadConversationList({
            append: true,
            selectDefault: false,
          })
        }
        onSelect={selectConversation}
        onCreate={createConversation}
        onRename={renameConversation}
        onDelete={deleteConversation}
      />

      <ScreenshotModal
        visible={Boolean(mediaPreview)}
        source={mediaPreview?.source ?? null}
        title={mediaPreview?.title}
        hint={mediaPreview?.hint}
        onClose={() => setMediaPreview(null)}
      />
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  page: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    minHeight: 69,
    paddingHorizontal: 13,
    paddingTop: 10,
    paddingBottom: 10,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(35, 85, 114, 0.50)',
  },
  headerTitle: {
    flex: 1,
    minWidth: 0,
  },
  title: {
    color: colors.text,
    fontSize: 19,
    lineHeight: 24,
    fontWeight: '800',
    letterSpacing: -0.25,
  },
  headerButton: {
    width: 43,
    height: 43,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  headerButtonPressed: {
    opacity: 0.7,
    transform: [{ scale: 0.96 }],
  },
  headerButtonDisabled: {
    opacity: 0.4,
  },
  headerButtonIcon: {
    color: colors.ice,
    fontSize: 21,
    lineHeight: 24,
    fontWeight: '800',
  },
  offlineBanner: {
    paddingHorizontal: 15,
    paddingVertical: 8,
    backgroundColor: 'rgba(255, 210, 131, 0.10)',
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255, 210, 131, 0.30)',
  },
  offlineText: {
    color: colors.warning,
    fontSize: 11,
    lineHeight: 16,
    textAlign: 'center',
    fontWeight: '700',
  },
  bannerWrap: {
    paddingHorizontal: 15,
    paddingTop: 9,
  },
  historyLoading: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
  },
  historyLoadingText: {
    color: colors.muted,
    fontSize: 12,
  },
  messages: {
    flexGrow: 1,
    justifyContent: 'flex-end',
    padding: 16,
    paddingBottom: 20,
  },
  emptyMessages: {
    justifyContent: 'center',
  },
  olderWrap: {
    alignItems: 'center',
    paddingBottom: 14,
  },
  messageGap: {
    height: 10,
  },
  bubble: {
    maxWidth: '88%',
    alignSelf: 'flex-start',
    borderRadius: 18,
    borderBottomLeftRadius: 5,
    padding: 13,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 6,
  },
  bubbleMine: {
    alignSelf: 'flex-end',
    borderBottomLeftRadius: 18,
    borderBottomRightRadius: 5,
    backgroundColor: colors.ice,
    borderColor: colors.ice,
  },
  bubbleSystem: {
    maxWidth: '100%',
    alignSelf: 'stretch',
    borderBottomLeftRadius: 18,
    backgroundColor: 'rgba(255, 141, 154, 0.10)',
    borderColor: 'rgba(255, 141, 154, 0.45)',
  },
  bubbleTable: {
    width: '100%',
    maxWidth: '100%',
    alignSelf: 'stretch',
  },
  speaker: {
    color: colors.ice,
    fontSize: 11,
    fontWeight: '900',
    textTransform: 'uppercase',
    letterSpacing: 0.7,
  },
  sentFiles: {
    gap: 5,
    marginTop: 3,
  },
  sentFile: {
    flexShrink: 1,
    color: colors.ice,
    fontSize: 11,
    lineHeight: 15,
  },
  sentFileMine: {
    color: '#164158',
  },
  storedFile: {
    minHeight: 35,
    paddingHorizontal: 9,
    paddingVertical: 6,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
    borderRadius: 10,
    backgroundColor: '#071D2C',
  },
  storedFileMine: {
    backgroundColor: 'rgba(6, 21, 34, 0.10)',
  },
  storedFileMeta: {
    color: colors.muted,
    fontSize: 9,
  },
  screenshotActions: {
    alignItems: 'flex-start',
    gap: 5,
    marginTop: 4,
  },
  modelMeta: {
    marginTop: 3,
    color: colors.muted,
    fontSize: 10,
    lineHeight: 14,
  },
  sources: {
    marginTop: 8,
    paddingTop: 9,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    gap: 7,
  },
  sourcesTitle: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: '800',
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  sourceLink: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 7,
    paddingHorizontal: 9,
    borderRadius: 10,
    backgroundColor: '#071D2C',
  },
  sourceText: {
    flex: 1,
    color: colors.ice,
    fontSize: 12,
    lineHeight: 17,
  },
  sourceArrow: {
    color: colors.ice,
    fontSize: 15,
  },
  delivery: {
    color: '#21536A',
    fontSize: 9,
    textAlign: 'right',
    fontWeight: '700',
  },
  deliveryFailed: {
    color: '#8A3343',
  },
  messageTime: {
    color: '#7197AA',
    fontSize: 9,
    textAlign: 'right',
  },
  messageTimeMine: {
    color: '#28627B',
  },
  composer: {
    paddingHorizontal: 13,
    paddingTop: 10,
    paddingBottom: 10,
    gap: 9,
    backgroundColor: colors.backgroundRaised,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  attachmentPanel: {
    gap: 7,
  },
  attachmentSummary: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
  },
  attachmentSummaryText: {
    color: colors.muted,
    fontSize: 10,
    fontWeight: '700',
  },
  attachmentList: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
  },
  attachmentChip: {
    maxWidth: '48%',
    minHeight: 33,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingLeft: 10,
    paddingRight: 6,
    borderRadius: 10,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  attachmentName: {
    flexShrink: 1,
    color: colors.text,
    fontSize: 11,
  },
  remove: {
    color: colors.muted,
    fontSize: 22,
    lineHeight: 28,
    paddingHorizontal: 3,
  },
  composerTools: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
  },
  addTools: {
    flexDirection: 'row',
    gap: 6,
  },
  researchToggle: {
    height: 36,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
    borderRadius: 12,
    paddingHorizontal: 10,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: 'transparent',
  },
  researchToggleOn: {
    backgroundColor: 'rgba(131, 232, 255, 0.12)',
    borderColor: colors.iceStrong,
  },
  toggleDot: {
    width: 7,
    height: 7,
    borderRadius: 99,
    backgroundColor: colors.muted,
  },
  toggleDotOn: {
    backgroundColor: colors.ice,
  },
  researchText: {
    color: colors.muted,
    fontSize: 10,
    fontWeight: '800',
  },
  researchTextOn: {
    color: colors.ice,
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 8,
  },
  input: {
    flex: 1,
    minHeight: 46,
    maxHeight: 120,
    paddingHorizontal: 13,
    paddingVertical: 11,
    borderRadius: 15,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: '#061A29',
    color: colors.text,
    fontSize: 15,
    lineHeight: 21,
  },
  send: {
    width: 46,
    height: 46,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 15,
    backgroundColor: colors.ice,
  },
  sendDisabled: {
    opacity: 0.38,
  },
  sendPressed: {
    transform: [{ scale: 0.95 }],
  },
  sendText: {
    color: colors.background,
    fontSize: 25,
    lineHeight: 27,
    fontWeight: '900',
  },
  status: {
    color: colors.ice,
    fontSize: 11,
    lineHeight: 16,
    textAlign: 'center',
  },
  markdownTableScroller: {
    width: '100%',
    maxWidth: '100%',
    alignSelf: 'stretch',
    marginBottom: 7,
  },
  markdownTableScrollerContent: {
    flexGrow: 0,
    paddingBottom: 3,
  },
  markdownTable: {
    alignSelf: 'flex-start',
  },
});

function createMarkdownStyles(
  textColor: string,
  accentColor: string,
  surfaceColor: string,
  borderColor: string,
) {
  return StyleSheet.create({
    root: {
      flexShrink: 1,
    },
    text: {
      color: textColor,
      fontSize: 15,
      lineHeight: 22,
      flexShrink: 1,
    },
    paragraph: {
      marginTop: 0,
      marginBottom: 6,
    },
    headingContainer: {
      marginTop: 4,
      marginBottom: 7,
    },
    heading: {
      color: textColor,
      fontWeight: '800',
    },
    heading1: {
      fontSize: 22,
      lineHeight: 28,
    },
    heading2: {
      fontSize: 19,
      lineHeight: 25,
    },
    heading3: {
      fontSize: 17,
      lineHeight: 23,
    },
    heading1Container: {
      paddingBottom: 5,
      borderBottomColor: borderColor,
    },
    heading2Container: {
      paddingBottom: 4,
      borderBottomColor: borderColor,
    },
    blockquote: {
      marginBottom: 7,
      paddingHorizontal: 10,
      borderLeftColor: accentColor,
    },
    list: {
      marginBottom: 7,
    },
    listUnorderedItemIcon: {
      color: textColor,
      lineHeight: 22,
    },
    listOrderedItemIcon: {
      color: textColor,
      lineHeight: 22,
    },
    codeInline: {
      fontFamily: codeFontFamily,
      color: textColor,
      backgroundColor: surfaceColor,
      fontSize: 13,
    },
    codeBlock: {
      fontFamily: codeFontFamily,
      color: textColor,
      backgroundColor: surfaceColor,
      borderColor,
      borderWidth: 1,
      padding: 10,
      marginBottom: 7,
      fontSize: 13,
      lineHeight: 19,
    },
    pre: {
      marginBottom: 7,
    },
    link: {
      color: accentColor,
      textDecorationLine: 'underline',
    },
    hr: {
      height: 1,
      marginTop: 7,
      marginBottom: 7,
      backgroundColor: borderColor,
    },
    table: {
      marginBottom: 7,
      borderColor,
    },
    tableHeader: {
      backgroundColor: surfaceColor,
    },
    tableHeaderCell: {
      paddingVertical: 5,
      paddingHorizontal: 7,
      borderColor,
    },
    tableRow: {
      borderColor,
    },
    tableRowCell: {
      paddingVertical: 5,
      paddingHorizontal: 7,
      borderColor,
    },
  });
}

const markdownStylesAssistant = createMarkdownStyles(
  colors.text,
  colors.ice,
  '#071D2C',
  colors.border,
);

const markdownStylesMine = createMarkdownStyles(
  colors.background,
  '#164158',
  'rgba(7, 29, 44, 0.12)',
  'rgba(7, 29, 44, 0.28)',
);

const safeMarkdownIt = new MarkdownIt({
  html: false,
  linkify: false,
  breaks: true,
  typographer: true,
});
safeMarkdownIt.validateLink = isSafeSourceUrl;

const safeMarkdownRules: RenderRules = {
  fence: (node) => <MarkdownCodeBlock key={node.key} content={node.content} language={node.sourceInfo} />,
  code_block: (node) => <MarkdownCodeBlock key={node.key} content={node.content} />,
  image: (node) => (
    <Text key={node.key}>
      {node.attributes.alt
        ? `[Imagen omitida: ${node.attributes.alt}]`
        : '[Imagen omitida]'}
    </Text>
  ),
  table: (node, children, _parents, markdownStyle) => {
    const contentWidth = markdownTableContentWidth(node);
    return (
      <ScrollView
        key={node.key}
        horizontal
        nestedScrollEnabled
        directionalLockEnabled
        alwaysBounceHorizontal={false}
        showsHorizontalScrollIndicator
        indicatorStyle="white"
        accessibilityLabel="Tabla desplazable horizontalmente"
        accessibilityHint="Desliza a izquierda o derecha para ver todas las columnas"
        style={styles.markdownTableScroller}
        contentContainerStyle={styles.markdownTableScrollerContent}
      >
        <View
          style={[
            markdownStyle.table as StyleProp<ViewStyle>,
            styles.markdownTable,
            {
              width: contentWidth,
              minWidth: contentWidth,
              marginBottom: 0,
            },
          ]}
        >
          {children}
        </View>
      </ScrollView>
    );
  },
  th: (node, children, parentNodes, markdownStyle) => {
    const width = markdownTableCellWidth(parentNodes);
    const cellSize: ViewStyle = {
      width,
      minWidth: width,
      maxWidth: width,
      flex: 0,
      flexBasis: width,
      flexGrow: 0,
      flexShrink: 0,
    };
    return (
      <View
        key={node.key}
        style={[
          markdownStyle.tableHeaderCell as StyleProp<ViewStyle>,
          cellSize,
        ]}
      >
        {children}
      </View>
    );
  },
  td: (node, children, parentNodes, markdownStyle) => {
    const width = markdownTableCellWidth(parentNodes);
    const cellSize: ViewStyle = {
      width,
      minWidth: width,
      maxWidth: width,
      flex: 0,
      flexBasis: width,
      flexGrow: 0,
      flexShrink: 0,
    };
    return (
      <View
        key={node.key}
        style={[
          markdownStyle.tableRowCell as StyleProp<ViewStyle>,
          cellSize,
        ]}
      >
        {children}
      </View>
    );
  },
};
