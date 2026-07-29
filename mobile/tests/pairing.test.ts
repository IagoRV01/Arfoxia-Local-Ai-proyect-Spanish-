import assert from 'node:assert/strict';
import test from 'node:test';

import {
  ARFOXIA_HOST,
  ARFOXIA_LOCAL_HOST,
  ARFOXIA_LOCAL_PORT,
  isSafeSourceUrl,
  parsePairingCode,
} from '../src/pairing';

const TOKEN = 'A'.repeat(43);
const validUrl = `https://${ARFOXIA_HOST}/?ui=8#token=${TOKEN}`;

test('parses the existing Arfoxia desktop QR without retaining its fragment', () => {
  const result = parsePairingCode(validUrl);

  assert.deepEqual(result, {
    version: 1,
    baseUrl: `https://${ARFOXIA_HOST}`,
    token: TOKEN,
  });
  assert.equal(result.baseUrl.includes('token'), false);
});

test('accepts URL-safe token characters and unrelated safe fragment fields', () => {
  const token = `${'a'.repeat(40)}_-9`;
  const result = parsePairingCode(
    `https://${ARFOXIA_HOST}/#screen=mobile&token=${token}&ui=8`,
  );

  assert.equal(result.token, token);
});

test('upgrades the exact desktop LAN fallback to the pinned Tailscale HTTPS host', () => {
  const result = parsePairingCode(
    `http://${ARFOXIA_LOCAL_HOST}:${ARFOXIA_LOCAL_PORT}/?ui=8#token=${TOKEN}`,
  );

  assert.deepEqual(result, {
    version: 1,
    baseUrl: `https://${ARFOXIA_HOST}`,
    token: TOKEN,
  });
});

test('explains when the Expo Go launch QR is scanned a second time', () => {
  assert.throws(
    () => parsePairingCode('exp://100.96.94.52:8081'),
    /QR de Expo Go/,
  );
});

for (const [name, value] of [
  ['plain HTTP', `http://${ARFOXIA_HOST}/#token=${TOKEN}`],
  ['a different LAN host', `http://other-pc:${ARFOXIA_LOCAL_PORT}/#token=${TOKEN}`],
  ['a different LAN port', `http://${ARFOXIA_LOCAL_HOST}:9999/#token=${TOKEN}`],
  ['a different tailnet host', `https://other.tail000000.ts.net/#token=${TOKEN}`],
  ['a deceptive host suffix', `https://${ARFOXIA_HOST}.example.com/#token=${TOKEN}`],
  ['a custom port', `https://${ARFOXIA_HOST}:8443/#token=${TOKEN}`],
  ['embedded credentials', `https://user:pass@${ARFOXIA_HOST}/#token=${TOKEN}`],
  ['a different path', `https://${ARFOXIA_HOST}/admin#token=${TOKEN}`],
  ['a query-string token', `https://${ARFOXIA_HOST}/?token=${TOKEN}`],
  ['a short fragment token', `https://${ARFOXIA_HOST}/#token=short`],
] as const) {
  test(`rejects ${name}`, () => {
    assert.throws(() => parsePairingCode(value));
  });
}

test('only treats HTTPS links as safe external sources', () => {
  assert.equal(isSafeSourceUrl('https://example.com/report'), true);
  assert.equal(isSafeSourceUrl('https://example.com/report?q=uno'), true);
  assert.equal(isSafeSourceUrl('http://example.com/report'), false);
  assert.equal(isSafeSourceUrl('https://user:pass@example.com/report'), false);
  assert.equal(isSafeSourceUrl('javascript:alert(1)'), false);
  assert.equal(isSafeSourceUrl('data:text/html,payload'), false);
  assert.equal(isSafeSourceUrl('file:///C:/Windows/win.ini'), false);
  assert.equal(isSafeSourceUrl('/api/state'), false);
  assert.equal(isSafeSourceUrl('//example.com/report'), false);
  assert.equal(isSafeSourceUrl('https://example.com/\nreport'), false);
  assert.equal(isSafeSourceUrl('not a URL'), false);
});
