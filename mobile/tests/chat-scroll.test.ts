import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import ts from 'typescript';

import { isNearLatest, newestFirst } from '../src/chatScroll';
import { mergeMessages } from '../src/conversations';
import type { ChatMessage } from '../src/types';

const text = readFileSync(new URL('../src/ChatScreen.tsx', import.meta.url), 'utf8');
const file = ts.createSourceFile('ChatScreen.tsx', text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
function prop(name: string) {
  let value: string | undefined;
  function visit(node: ts.Node) {
    if (ts.isJsxSelfClosingElement(node) && node.tagName.getText(file) === 'FlatList') {
      const attribute = node.attributes.properties.find((a): a is ts.JsxAttribute =>
        ts.isJsxAttribute(a) && a.name.getText(file) === name);
      if (attribute) value = attribute.initializer?.getText(file) ?? 'true';
    }
    ts.forEachChild(node, visit);
  }
  visit(file);
  return value;
}

function message(id: string): ChatMessage {
  return { id, role: 'user', content: id, conversation_id: 'chat', origin: 'api',
    created_at: '2026-11-25T12:00:00Z', metadata: {}, attachments: [] };
}

test('inverted history starts at the latest item without guessing variable message heights', () => {
  const canonical = Object.freeze(Array.from({ length: 100 }, (_, index) => ({
    id: index, text: 'Long Markdown '.repeat(index * 100),
  })));
  const display = newestFirst(canonical);
  assert.equal(display[0].id, 99);
  assert.equal(display.at(-1)?.id, 0);
  assert.equal(canonical[0].id, 0);
  assert.notEqual(display, canonical);
  assert.deepEqual(newestFirst([]), []);
  assert.equal(prop('inverted'), 'true');
  assert.equal(prop('data'), '{displayedEntries}');
  assert.doesNotMatch(text, /scrollToEnd\(/);
  assert.match(text, /scrollToOffset\(\{ offset: 0, animated: false \}\)/);
  assert.match(text, /messages:\s*\{\s*flexGrow: 1,\s*justifyContent: 'flex-start'/);
});

test('older pages stay above the latest message and preserve canonical order', () => {
  const current = [message('3'), message('4')];
  const merged = mergeMessages(current, [message('1'), message('2')], 'prepend');
  assert.deepEqual(newestFirst(merged).map(row => row.id), ['4', '3', '2', '1']);
  assert.deepEqual(current.map(row => row.id), ['3', '4']);
  assert.match(prop('ListFooterComponent')!, /Cargar mensajes anteriores/);
  assert.equal(prop('ListHeaderComponent'), undefined);
  assert.equal(prop('maintainVisibleContentPosition'), '{{ minIndexForVisible: 0, autoscrollToTopThreshold: 64 }}');
});

test('new messages occupy the exact bottom offset including optimistic sends', () => {
  const current = [message('1'), message('2')];
  const merged = mergeMessages(current, [message('3')], 'append');
  assert.deepEqual(newestFirst(merged).map(row => row.id), ['3', '2', '1']);
  assert.deepEqual(newestFirst([...merged, message('local')]).map(row => row.id), ['local', '3', '2', '1']);
});

test('manual reading disables tail following but iOS bounce remains near the latest', () => {
  assert.equal(isNearLatest(-30), true);
  assert.equal(isNearLatest(0), true);
  assert.equal(isNearLatest(64), true);
  assert.equal(isNearLatest(65), false);
  assert.equal(isNearLatest(1500), false);
  assert.equal(isNearLatest(NaN), false);
  assert.equal(isNearLatest(Infinity), false);
  assert.match(prop('onScrollBeginDrag')!, /followLatest.current = false/);
  assert.match(prop('onScrollBeginDrag')!, /cancelAnimationFrame/);
  assert.match(prop('onScroll')!, /isNearLatest\(nativeEvent.contentOffset.y\)/);
  assert.match(prop('onScroll')!, /if \(readingHistory.current\)/);
  assert.match(text, /if \(!active \|\| !followLatest.current\) return/);
  assert.match(text, /followLatest.current = false;\s*setLoadingOlder\(true\)/);
});

test('layout and delayed image sizes retry the exact bottom while following', () => {
  assert.equal(prop('onLayout'), '{scrollToLatest}');
  assert.equal(prop('onContentSizeChange'), '{scrollToLatest}');
  assert.match(text, /latestFrame.current = requestAnimationFrame/);
  assert.match(text, /if \(followLatest.current\) \{\s*list.current\?\.scrollToOffset/);
  assert.match(text, /return \(\) => \{\s*if \(latestFrame.current !== null\) cancelAnimationFrame/);
});

test('entering the chat or resuming Expo returns to the latest, polling does not reset reading', () => {
  assert.match(text, /if \(active\) \{\s*readingHistory.current = false;\s*followLatest.current = true;\s*scrollToLatest\(\)/);
  assert.match(text, /if \(next === 'active'\) \{\s*readingHistory.current = false;\s*followLatest.current = true;\s*scrollToLatest\(\);\s*sync\(\)/);
  const syncBody = text.slice(text.indexOf('const sync = () => {'), text.indexOf('const timer = setInterval(sync'));
  assert.doesNotMatch(syncBody, /followLatest.current = true|scrollToLatest/);
  assert.doesNotMatch(text, /followLatest.current = stillSelected/);
});
