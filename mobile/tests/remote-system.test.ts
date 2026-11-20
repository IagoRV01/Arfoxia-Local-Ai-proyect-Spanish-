import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import ts from 'typescript';

const source = (name: string) => readFileSync(new URL(`../src/${name}`, import.meta.url), 'utf8');

test('PC section selects a separate remote pane, without mixing Windows AI controls', () => {
  const text = source('SystemScreen.tsx');
  assert.match(text, /label="Este PC"/);
  assert.match(text, /label="BC-250"/);
  assert.match(text, /target === 'local' \? <LocalSystemScreen.*: <RemoteSystemScreen/);
  assert.match(text, /accessibilityState=\{\{ selected: target === 'bc250' \}\}/);
  const remote = source('RemoteSystemScreen.tsx');
  assert.doesNotMatch(remote, /api\.(action|setModelMode|unloadModel|pcStatus|modelStatus)\(/);
});

test('BC-250 API has one fixed authenticated GET route and bounded timeout', () => {
  const file = ts.createSourceFile('api.ts', source('api.ts'), ts.ScriptTarget.Latest, true);
  let method: ts.MethodDeclaration | undefined;
  function visit(node: ts.Node) {
    if (ts.isMethodDeclaration(node) && node.name.getText() === 'bc250Status') method = node;
    ts.forEachChild(node, visit);
  }
  visit(file);
  assert.ok(method);
  assert.match(method.getText(file), /this\.request<RemotePcStatus>\('\/api\/pc\/bc250', \{ timeoutMs: 20_000 \}\)/);
  assert.doesNotMatch(method.getText(file), /authenticated: false|POST|host|command/);
});

test('remote polling only runs while active and cleans up when leaving the pane', () => {
  const text = source('RemoteSystemScreen.tsx');
  assert.match(text, /pending \|\| AppState\.currentState !== 'active'/);
  assert.match(text, /setInterval\(.*20_000\)/);
  assert.match(text, /clearInterval\(timer\)/);
  assert.match(text, /subscription\.remove\(\)/);
  assert.match(text, /mounted = false/);
  assert.match(text, /setSnapshot\(null\)/);
  assert.match(text, /if \(mounted\)/);
  assert.match(text, /RefreshControl/);
});

test('remote readings disclose missing sensors, data filesystem and SoC power scope', () => {
  const text = source('RemoteSystemScreen.tsx');
  assert.match(text, /Number\.isFinite\(value\)/);
  assert.match(text, /No disponible/);
  assert.match(text, /pc\.disk_path/);
  assert.match(text, /Potencia SoC \(puede incluir CPU\)/);
  assert.match(text, /no se suma a la RAM/);
  assert.match(text, /snapshot\?\.online \? snapshot.status : null/);
  for (const field of ['cpu_percent', 'memory_percent', 'disk_free_gb', 'temperature_c', 'soc_power_w', 'memory_total_mb']) {
    assert.ok(text.includes(field));
  }
});
