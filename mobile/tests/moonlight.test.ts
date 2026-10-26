import assert from 'node:assert/strict';
import test from 'node:test';

import {
  MOONLIGHT_APP_STORE_URL,
  moonlightShortcutUrl,
  normalizeMoonlightPin,
  usableMoonlightHost,
  gameStreamingPath,
  gameStreamingPairBody,
  checkedStreamingTarget,
} from '../src/moonlight';

test('remote PIN uses an explicit BC-250 target without changing the local API contract', () => {
  assert.equal(gameStreamingPath('status', 'local'), '/api/gaming/status');
  assert.equal(gameStreamingPath('prepare', 'bc250'), '/api/gaming/prepare?target=bc250');
  assert.deepEqual(gameStreamingPairBody('0032', 'Phone', 'local'), { pin: '0032', name: 'Phone' });
  assert.deepEqual(gameStreamingPairBody('0032', 'Phone', 'bc250'), { pin: '0032', name: 'Phone', target: 'bc250' });
});

test('PIN requests cannot select an arbitrary host or include non-ASCII PINs', () => {
  assert.throws(() => gameStreamingPath('status', 'evil' as never));
  assert.throws(() => gameStreamingPairBody('１２３４', 'Phone', 'bc250'));
  assert.throws(() => gameStreamingPairBody('1234', 'Phone', 'https://evil' as never));
});

test('a local or stale backend response cannot masquerade as the selected BC-250', () => {
  assert.deepEqual(checkedStreamingTarget({}, 'local'), {});
  assert.equal(checkedStreamingTarget({ target: 'bc250' }, 'bc250').target, 'bc250');
  assert.throws(() => checkedStreamingTarget({}, 'bc250'));
  assert.throws(() => checkedStreamingTarget({ target: 'local' }, 'bc250'));
  assert.throws(() => checkedStreamingTarget({ target: 'bc250' }, 'local'));
});

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
