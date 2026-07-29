import type { Credentials } from './types';

export const ARFOXIA_HOST = 'pciagorv.tail122075.ts.net';
export const ARFOXIA_LOCAL_HOST = 'pciagorv';
export const ARFOXIA_LOCAL_PORT = '8742';

const TOKEN_PATTERN = /^[A-Za-z0-9_-]{32,128}$/;

export class PairingError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PairingError';
  }
}

export function parsePairingCode(rawValue: string): Credentials {
  const raw = rawValue.trim();
  if (!raw) {
    throw new PairingError('El código está vacío.');
  }

  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new PairingError('El QR no contiene un enlace válido de Arfoxia.');
  }

  if (url.protocol === 'exp:' || url.protocol === 'exps:') {
    throw new PairingError(
      'Ese es el QR de Expo Go. Ahora escanea el QR que aparece al pulsar «Emparejar iPhone» en Arfoxia.',
    );
  }
  if (url.username || url.password || url.pathname !== '/') {
    throw new PairingError('Este QR no pertenece a tu PC de Arfoxia.');
  }

  const fragment = new URLSearchParams(url.hash.startsWith('#') ? url.hash.slice(1) : url.hash);
  const token = fragment.get('token')?.trim() ?? '';
  if (!TOKEN_PATTERN.test(token)) {
    throw new PairingError('El QR no incluye una clave de emparejamiento válida.');
  }

  const hostname = url.hostname.toLowerCase();
  const isPrivateHttps =
    url.protocol === 'https:' && hostname === ARFOXIA_HOST && !url.port;
  const isExactLocalFallback =
    url.protocol === 'http:' &&
    hostname === ARFOXIA_LOCAL_HOST &&
    url.port === ARFOXIA_LOCAL_PORT;
  if (!isPrivateHttps && !isExactLocalFallback) {
    throw new PairingError(
      'Este QR no coincide con la conexión privada de tu PC de Arfoxia.',
    );
  }

  return {
    version: 1,
    // Even if the desktop had to show its exact local fallback URL, the
    // iPhone always talks to the pinned Tailscale HTTPS endpoint.
    baseUrl: `https://${ARFOXIA_HOST}`,
    token,
  };
}

export function isSafeSourceUrl(value: string): boolean {
  if (
    !value ||
    [...value].some(
      (character) =>
        character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127,
    )
  ) {
    return false;
  }
  try {
    const url = new URL(value);
    return (
      url.protocol === 'https:' &&
      Boolean(url.hostname) &&
      !url.username &&
      !url.password
    );
  } catch {
    return false;
  }
}
