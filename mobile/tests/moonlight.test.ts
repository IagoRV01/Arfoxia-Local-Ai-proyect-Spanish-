import assert from 'node:assert/strict';
import test from 'node:test';

import {
  MOONLIGHT_APP_STORE_URL,
  moonlightShortcutUrl,
  normalizeMoonlightPin,
  usableMoonlightHost,
} from '../src/moonlight';

test('builds the documented Apple Shortcuts URL without inventing a Moonlight scheme', () => {
  assert.equal(
    moonlightShortcutUrl(),
    'shortcuts://run-shortcut?name=Abrir%20Moonlight',
  );
  assert.equal(
    moonlightShortcutUrl('Jugar en el PC 🎮'),
    'shortcuts://run-shortcut?name=Jugar%20en%20el%20PC%20%F0%9F%8E%AE',
  );
  assert.match(MOONLIGHT_APP_STORE_URL, /id1000551566$/);
  assert.equal(MOONLIGHT_APP_STORE_URL.includes('moonlight://'), false);
});

test('normalizes the Moonlight PIN to four digits', () => {
  assert.equal(normalizeMoonlightPin('1a 23-45'), '1234');
  assert.equal(normalizeMoonlightPin('abcd'), '');
});

test('prefers MagicDNS and falls back to the Tailscale IPv4 address', () => {
  assert.equal(
    usableMoonlightHost(' pc.tailnet.ts.net ', '100.64.0.2'),
    'pc.tailnet.ts.net',
  );
  assert.equal(usableMoonlightHost('', ' 100.64.0.2 '), '100.64.0.2');
  assert.equal(usableMoonlightHost(undefined, undefined), '');
});
