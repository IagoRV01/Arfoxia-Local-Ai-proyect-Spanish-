import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import ts from 'typescript';

const root = path.resolve(import.meta.dirname, '..');
function source(file: string) {
  return ts.createSourceFile(file, readFileSync(path.join(root, file), 'utf8'),
    ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
}
function elements(node: ts.Node, tag: string) {
  const result: Array<ts.JsxElement | ts.JsxSelfClosingElement> = [];
  function visit(child: ts.Node) {
    if ((ts.isJsxElement(child) && child.openingElement.tagName.getText() === tag)
      || (ts.isJsxSelfClosingElement(child) && child.tagName.getText() === tag)) result.push(child);
    ts.forEachChild(child, visit);
  }
  visit(node);
  return result;
}
function prop(node: ts.JsxElement | ts.JsxSelfClosingElement, name: string) {
  const attrs = ts.isJsxElement(node) ? node.openingElement.attributes : node.attributes;
  return attrs.properties.find((a): a is ts.JsxAttribute =>
    ts.isJsxAttribute(a) && a.name.getText() === name)?.initializer?.getText();
}

test('main window has one keyboard owner and uses the real safe-area origin', () => {
  const layout = source('src/KeyboardLayout.tsx');
  const avoiders = elements(layout, 'KeyboardAvoidingView');
  assert.equal(avoiders.length, 1);
  assert.equal(prop(avoiders[0], 'behavior'), '"padding"');
  assert.equal(prop(avoiders[0], 'keyboardVerticalOffset'), '{insets.top}');
  assert.match(layout.text, /const insets = useSafeAreaInsets\(\)/);
  const app = source('App.tsx');
  const main = elements(app, 'MainKeyboardLayout');
  assert.equal(main.length, 1);
  assert.equal(elements(main[0], 'ChatScreen').length, 1);
  assert.equal(elements(source('src/ChatScreen.tsx'), 'KeyboardAvoidingView').length, 0);
});

test('keyboard events include third-party keyboards and clean up on unmount', () => {
  const layout = source('src/KeyboardLayout.tsx').text;
  assert.match(layout, /Keyboard\.isVisible\(\)/);
  for (const event of ['keyboardWillShow', 'keyboardDidShow', 'keyboardWillHide', 'keyboardDidHide']) {
    assert.ok(layout.includes(event));
  }
  assert.match(layout, /show\.remove\(\)/);
  assert.match(layout, /hide\.remove\(\)/);
  assert.match(layout, /footer\(keyboardVisible\)/);
});

test('typing hides navigation but keeps the Moonlight PIN modal mounted', () => {
  const app = source('App.tsx');
  const launcher = elements(app, 'GamingLauncher');
  assert.equal(launcher.length, 1);
  assert.equal(prop(launcher[0], 'hideLauncher'), '{keyboardVisible}');
  assert.match(app.text, /!keyboardVisible && <BottomNavigation/);
  const gaming = source('src/GamingLauncher.tsx');
  assert.match(gaming.text, /hideLauncher && \{ display: 'none' \}/);
  assert.equal(elements(gaming, 'SafeModal').length, 1);
});

test('chat history shrinks instead of pushing the multiline composer under the keyboard', () => {
  const chat = source('src/ChatScreen.tsx');
  const history = elements(chat, 'FlatList')[0];
  assert.equal(prop(history, 'style'), '{styles.history}');
  assert.equal(prop(history, 'keyboardShouldPersistTaps'), '"handled"');
  assert.match(prop(history, 'keyboardDismissMode')!, /interactive.*on-drag/);
  const input = elements(chat, 'TextInput')[0];
  assert.equal(prop(input, 'accessibilityLabel'), '"Mensaje para Arfoxia"');
  assert.ok(input && ts.isJsxSelfClosingElement(input));
  assert.ok(input.attributes.properties.some(a => ts.isJsxAttribute(a) && a.name.getText() === 'multiline'));
  assert.ok(input.attributes.properties.some(a => ts.isJsxAttribute(a) && a.name.getText() === 'scrollEnabled'));
  assert.match(chat.text, /history:\s*\{\s*flex: 1,\s*minHeight: 0/);
  assert.match(chat.text, /composer:\s*\{\s*flexShrink: 0/);
});
