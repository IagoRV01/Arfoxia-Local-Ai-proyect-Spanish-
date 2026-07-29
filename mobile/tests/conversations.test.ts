import assert from 'node:assert/strict';
import test from 'node:test';

import {
  chatMessageToEntry,
  conversationsAfterDelete,
  conversationSelectionAfterList,
  conversationAttachmentSource,
  createClientMessageId,
  mergeMessages,
  reconcileLocalEntries,
  storedAttachmentId,
  upsertConversation,
} from '../src/conversations';
import type { ChatMessage, Conversation } from '../src/types';

function message(
  id: string,
  overrides: Partial<ChatMessage> = {},
): ChatMessage {
  return {
    id,
    conversation_id: 'conversation-1',
    role: 'user',
    content: `message ${id}`,
    origin: 'api',
    created_at: `2026-07-24T12:00:${String(id).padStart(2, '0')}Z`,
    metadata: {},
    attachments: [],
    ...overrides,
  };
}

function conversation(
  id: string,
  updatedAt: string,
): Conversation {
  return {
    id,
    title: `Chat ${id}`,
    created_at: '2026-07-24T10:00:00Z',
    updated_at: updatedAt,
    message_count: 1,
    preview: 'Hola',
  };
}

test('prepends older pages without duplicating the boundary message', () => {
  const current = [message('3'), message('4')];
  const older = [message('1'), message('2'), message('3', { content: 'canonical' })];

  const merged = mergeMessages(current, older, 'prepend');

  assert.deepEqual(merged.map((item) => item.id), ['1', '2', '3', '4']);
  assert.equal(merged[2].content, 'message 3');
});

test('appends live updates and replaces an existing canonical message', () => {
  const current = [message('1'), message('2')];
  const live = [
    message('2', { content: 'updated' }),
    message('3'),
  ];

  const merged = mergeMessages(current, live, 'append');

  assert.deepEqual(merged.map((item) => item.id), ['1', '2', '3']);
  assert.equal(merged[1].content, 'updated');
});

test('maps persisted metadata, attachments and screenshots to the chat UI', () => {
  const value = message('10', {
    role: 'assistant',
    content: 'Resultado',
    attachments: [
      {
        attachment_id: 'attachment-1',
        name: 'captura.webp',
        kind: 'screenshot',
        media_type: 'image/webp',
        size: 2048,
      },
    ],
    metadata: {
      model: 'qwen3.5:9b',
      model_mode: 'large',
      sources: [{ title: 'Fuente', url: 'https://example.com' }],
      action_results: [
        {
          success: true,
          action: 'take_screenshot',
          message: 'Hecha',
          data: { screenshot_id: 'a'.repeat(32) },
          requires_confirmation: false,
          requires_authorization: false,
          challenge_id: null,
          authorization_expires_at: null,
          authorization_summary: null,
          password_configured: true,
        },
      ],
    },
  });

  const entry = chatMessageToEntry(value);

  assert.equal(entry.model, 'qwen3.5:9b');
  assert.equal(entry.modelMode, 'large');
  assert.equal(entry.attachments?.[0].name, 'captura.webp');
  assert.deepEqual(
    entry.screenshotIds,
    [],
    'the durable screenshot attachment supersedes the temporary action id',
  );
  assert.equal(entry.sources?.[0].url, 'https://example.com');
  assert.equal(storedAttachmentId(value.attachments[0]), 'attachment-1');
});

test('moves an updated conversation to the top of the shared list', () => {
  const first = conversation('a', '2026-07-24T12:00:00Z');
  const second = conversation('b', '2026-07-24T11:00:00Z');
  const updatedSecond = {
    ...second,
    title: 'Renombrada',
    updated_at: '2026-07-24T13:00:00Z',
  };

  const result = upsertConversation([first, second], updatedSecond);

  assert.deepEqual(result.map((item) => item.id), ['b', 'a']);
  assert.equal(result[0].title, 'Renombrada');
});

test('leaves no conversation selected when deleting the last chat has no replacement', () => {
  const onlyConversation = conversation(
    'only',
    '2026-07-24T12:00:00Z',
  );

  assert.deepEqual(
    conversationsAfterDelete([onlyConversation], onlyConversation.id, null),
    [],
  );
});

test('uses the server replacement after deleting a conversation', () => {
  const deleted = conversation('deleted', '2026-07-24T12:00:00Z');
  const replacement = conversation(
    'replacement',
    '2026-07-24T11:00:00Z',
  );

  assert.deepEqual(
    conversationsAfterDelete([deleted], deleted.id, replacement),
    [replacement],
  );
});

test('creates UUID-shaped idempotency identifiers for chat retries', () => {
  const first = createClientMessageId();
  const second = createClientMessageId();

  assert.match(
    first,
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
  );
  assert.notEqual(first, second);
});

test('builds an authenticated, encoded source for a historical attachment', () => {
  const source = conversationAttachmentSource(
    {
      version: 1,
      baseUrl: 'https://pc.tail.test',
      token: 'dummy-token',
    },
    'chat with spaces',
    'file/one',
  );

  assert.deepEqual(source, {
    uri:
      'https://pc.tail.test/api/conversations/' +
      'chat%20with%20spaces/attachments/file%2Fone',
    headers: {
      Authorization: 'Bearer dummy-token',
    },
  });
});

test('removes an uncertain local bubble once the server confirms its client id', () => {
  const local = [
    {
      id: 'local:turn-1',
      role: 'user' as const,
      text: 'Hola',
      clientMessageId: 'turn-1',
      delivery: 'uncertain' as const,
    },
  ];
  const confirmed = [
    message('20', {
      client_message_id: 'turn-1',
      content: 'Hola',
    }),
  ];

  assert.deepEqual(reconcileLocalEntries(local, confirmed), []);
});

test('selects an existing chat when a reconnect recovers from an empty selection', () => {
  const recovered = conversation('recovered', '2026-07-24T13:00:00Z');

  assert.deepEqual(
    conversationSelectionAfterList(null, [recovered], {
      preserveExisting: true,
      selectDefault: true,
    }),
    { kind: 'select', id: 'recovered' },
  );
});

test('keeps the active chat during background synchronization', () => {
  const active = conversation('active', '2026-07-24T13:00:00Z');

  assert.deepEqual(
    conversationSelectionAfterList('active', [active], {
      preserveExisting: true,
      selectDefault: false,
    }),
    { kind: 'keep' },
  );
  assert.deepEqual(
    conversationSelectionAfterList('active', [], {
      preserveExisting: true,
      selectDefault: false,
    }),
    { kind: 'keep' },
  );
});

test('never invents a selection when the server has no conversations', () => {
  assert.deepEqual(conversationSelectionAfterList(null, []), {
    kind: 'clear',
  });
});
