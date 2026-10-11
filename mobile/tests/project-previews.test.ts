import assert from 'node:assert/strict';
import test from 'node:test';
import { previewNavigationAllowed, previewUrl, validatedPreviews } from '../src/projectPreviews';
import { chatMessageToEntry } from '../src/conversations';
import type { ChatMessage, Credentials, PreviewSession } from '../src/types';

const credentials: Credentials = {version: 1, baseUrl: 'https://pc.example.ts.net', token: 'owner-secret'};
const path = `/project-preview/${'a'.repeat(43)}/index.html`;
const session: PreviewSession = {path, title: 'Jardín', entry: 'jardin/index.html', kind: 'html', expires_in: 1800};
const project = {id: 'b'.repeat(32), title: 'Jardín', entry: 'jardin/index.html', kind: 'html', modified_at: 1, size: 20};

test('preview URL has a limited ticket and never the owner credential', () => {
  const url = previewUrl(credentials, session);
  assert.equal(url, credentials.baseUrl + path);
  assert.ok(!url.includes(credentials.token));
});

test('rejects insecure, external, API, malformed and traversal preview URLs', () => {
  for (const invalid of ['https://evil.example/result', '//evil.example/result', '/api/action', path + '?token=owner-secret', path + '#x', path.replace('index.html', '..%2fprivate.html'), path.replace('index.html', '%2e%2e/index.html'), path.replace('index.html', 'C%3Asecret'), path.replace('index.html', '%00.html'), path.replace('index.html', '%')]) {
    assert.throws(() => previewUrl(credentials, {...session, path: invalid}), invalid);
  }
  assert.throws(() => previewUrl({...credentials, baseUrl: 'http://pc.example.ts.net'}, session));
});

test('navigation stays within the capability and never opens tools or deep links', () => {
  const initial = credentials.baseUrl + path;
  assert.equal(previewNavigationAllowed(initial, initial), true);
  assert.equal(previewNavigationAllowed(initial.replace('index.html', 'page.html'), initial), true);
  assert.equal(previewNavigationAllowed('about:blank', initial), true);
  for (const url of ['https://evil.example', credentials.baseUrl + '/api/action', 'file:///secret', 'javascript:alert(1)', 'shortcuts://run-shortcut', initial.replace('index.html', '../secret'), initial.replace('https://', 'http://'), initial.replace('https://', 'https://owner:secret@')]) {
    assert.equal(previewNavigationAllowed(url, initial), false, url);
  }
});

test('validates descriptors and preserves result buttons in shared history', () => {
  assert.deepEqual(validatedPreviews([null, project, {id: 'bad'}, {...project, kind: 'executable'}]), [project]);
  const message: ChatMessage = {id: '1', conversation_id: 'chat', role: 'assistant', content: 'Hecho', origin: 'api', created_at: '', metadata: {project_previews: [project as any]}, attachments: []};
  assert.equal(chatMessageToEntry(message).projectPreviews?.[0].id, project.id);
  assert.equal(chatMessageToEntry({...message, metadata: {}}).projectPreviews?.length, 0);
});
