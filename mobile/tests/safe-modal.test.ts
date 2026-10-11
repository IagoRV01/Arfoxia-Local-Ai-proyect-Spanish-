import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import ts from 'typescript';

const root = path.resolve(import.meta.dirname, '..');
function source(relative: string) {
  return ts.createSourceFile(
    relative,
    readFileSync(path.join(root, relative), 'utf8'),
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
}
function elements(node: ts.Node, name: string): ts.JsxElement[] {
  const found: ts.JsxElement[] = [];
  function visit(current: ts.Node) {
    if (
      ts.isJsxElement(current) &&
      current.openingElement.tagName.getText() === name
    )
      found.push(current);
    ts.forEachChild(current, visit);
  }
  visit(node);
  return found;
}
function attributes(element: ts.JsxElement | ts.JsxSelfClosingElement) {
  return ts.isJsxElement(element)
    ? element.openingElement.attributes
    : element.attributes;
}
function attribute(
  element: ts.JsxElement | ts.JsxSelfClosingElement,
  name: string,
) {
  return attributes(element).properties.find(
    (p): p is ts.JsxAttribute =>
      ts.isJsxAttribute(p) && p.name.getText() === name,
  );
}
function prop(element: ts.JsxElement | ts.JsxSelfClosingElement, name: string) {
  const value = attribute(element, name)?.initializer;
  return value && ts.isJsxExpression(value)
    ? value.expression?.getText()
    : value?.getText();
}

test('native modal owns its provider and protects all four system edges', () => {
  const modal = elements(source('src/SafeModal.tsx'), 'Modal');
  assert.equal(modal.length, 1);
  const providers = elements(modal[0], 'SafeAreaProvider');
  assert.equal(providers.length, 1);
  const areas = elements(providers[0], 'SafeAreaView');
  assert.equal(areas.length, 1);
  const edges = attribute(areas[0], 'edges')?.initializer;
  assert.ok(
    edges &&
      ts.isJsxExpression(edges) &&
      edges.expression &&
      ts.isArrayLiteralExpression(edges.expression),
  );
  assert.deepEqual(
    edges.expression.elements.map((e) => (e as ts.StringLiteral).text),
    ['top', 'right', 'bottom', 'left'],
  );
  assert.ok(
    areas[0].children.some(
      (child) =>
        ts.isJsxExpression(child) && child.expression?.getText() === 'children',
    ),
  );
});

test('remounting modal measures fresh insets instead of seeding old window metrics', () => {
  const parsed = source('src/SafeModal.tsx');
  const provider = elements(parsed, 'SafeAreaProvider')[0];
  assert.equal(attribute(provider, 'initialMetrics'), undefined);
  assert.equal(attribute(provider, 'initialSafeAreaInsets'), undefined);
  assert.equal(elements(parsed, 'ScrollView').length, 0);
  assert.equal(
    prop(elements(parsed, 'SafeAreaView')[0], 'style'),
    '[styles.content, safeAreaStyle]',
  );
  const fn = parsed.statements.find(
    (s) => ts.isFunctionDeclaration(s) && s.name?.text === 'SafeModal',
  ) as ts.FunctionDeclaration;
  const parameter = fn.parameters[0].name;
  assert.ok(ts.isObjectBindingPattern(parameter));
  const presentation = parameter.elements.find(
    (e) => e.name.getText() === 'presentationStyle',
  );
  assert.equal(
    presentation?.initializer?.getText(),
    "transparent ? 'overFullScreen' : 'fullScreen'",
  );
});

test('every existing app overlay uses the protected shared modal', () => {
  const expected = {
    'src/ProjectViewer.tsx': 1,
    'src/ui.tsx': 1,
    'src/ConversationListModal.tsx': 2,
    'src/GamingLauncher.tsx': 1,
  };
  for (const [relative, count] of Object.entries(expected)) {
    const parsed = source(relative);
    assert.equal(elements(parsed, 'SafeModal').length, count, relative);
    assert.equal(elements(parsed, 'Modal').length, 0, relative);
  }
  // A future overlay must not reintroduce an unprotected native root.
  for (const file of readdirSync(path.join(root, 'src')).filter(
    (f) => f.endsWith('.tsx') && f !== 'SafeModal.tsx',
  )) {
    assert.equal(elements(source(`src/${file}`), 'Modal').length, 0, file);
  }
});

test('viewer gives the project title and action buttons independent rows', () => {
  const parsed = source('src/ProjectViewer.tsx');
  const header = elements(parsed, 'View').find(
    (e) => prop(e, 'style') === 'styles.header',
  );
  assert.ok(header);
  const title = elements(header, 'Text')[0];
  const actions = elements(header, 'View').find(
    (e) => prop(e, 'style') === 'styles.actions',
  );
  assert.ok(actions);
  assert.equal(prop(title, 'numberOfLines'), '1');
  assert.equal(elements(actions, 'Text').length, 0);
  const buttons = actions.children.filter(
    (c): c is ts.JsxSelfClosingElement =>
      ts.isJsxSelfClosingElement(c) && c.tagName.getText() === 'Button',
  );
  assert.deepEqual(
    buttons.map((b) => prop(b, 'label')),
    ['"Recargar"', '"Cerrar"'],
  );
});

test('web view does not add a second set of automatic content insets', () => {
  const parsed = source('src/ProjectViewer.tsx');
  let webview: ts.JsxSelfClosingElement | undefined;
  function visit(node: ts.Node) {
    if (
      ts.isJsxSelfClosingElement(node) &&
      node.tagName.getText() === 'WebView'
    )
      webview = node;
    ts.forEachChild(node, visit);
  }
  visit(parsed);
  assert.ok(webview);
  assert.equal(prop(webview, 'contentInsetAdjustmentBehavior'), '"never"');
  assert.equal(prop(webview, 'automaticallyAdjustContentInsets'), 'false');
  const src = attribute(webview, 'source')?.initializer;
  assert.ok(
    src &&
      ts.isJsxExpression(src) &&
      src.expression &&
      ts.isObjectLiteralExpression(src.expression),
  );
  assert.equal(src.expression.properties.length, 1); // Still no owner-auth headers.
  const uri = src.expression.properties[0];
  assert.ok(ts.isPropertyAssignment(uri));
  assert.equal(uri.name.getText(), 'uri');
  assert.equal(uri.initializer.getText(), 'url');
});

test('main app also protects side edges without nesting modal padding in its root', () => {
  const parsed = source('App.tsx');
  const area = elements(parsed, 'SafeAreaView')[0];
  const edges = attribute(area, 'edges')?.initializer;
  assert.ok(
    edges &&
      ts.isJsxExpression(edges) &&
      edges.expression &&
      ts.isArrayLiteralExpression(edges.expression),
  );
  assert.deepEqual(
    edges.expression.elements.map((e) => (e as ts.StringLiteral).text),
    ['top', 'right', 'bottom', 'left'],
  );
});
