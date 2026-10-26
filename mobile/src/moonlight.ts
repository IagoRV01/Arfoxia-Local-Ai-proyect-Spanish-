import type { GameStreamingTarget } from './types';

export const MOONLIGHT_SHORTCUT_NAME = 'Abrir Moonlight';
export const MOONLIGHT_APP_STORE_URL =
  'https://apps.apple.com/es/app/moonlight-game-streaming/id1000551566';

export function moonlightShortcutUrl(
  shortcutName = MOONLIGHT_SHORTCUT_NAME,
): string {
  return `shortcuts://run-shortcut?name=${encodeURIComponent(shortcutName)}`;
}

export function normalizeMoonlightPin(value: string): string {
  return value.replace(/\D/g, '').slice(0, 4);
}

export function usableMoonlightHost(
  host: string | null | undefined,
  tailscaleIp: string | null | undefined,
): string {
  return host?.trim() || tailscaleIp?.trim() || '';
}

export function checkedStreamingTarget<T extends { target?: GameStreamingTarget }>(value: T, target: GameStreamingTarget): T {
  if ((value.target ?? 'local') !== target) throw new Error('La respuesta corresponde a otro equipo. Vuelve a comprobar el destino.');
  return value;
}

export function gameStreamingPath(operation: 'status' | 'prepare', target: GameStreamingTarget): string {
  if (target !== 'local' && target !== 'bc250') throw new Error('Destino de Sunshine no válido.');
  return `/api/gaming/${operation}${target === 'local' ? '' : '?target=bc250'}`;
}

export function gameStreamingPairBody(pin: string, name: string, target: GameStreamingTarget) {
  if (target !== 'local' && target !== 'bc250') throw new Error('Destino de Sunshine no válido.');
  if (!/^[0-9]{4}$/.test(pin)) throw new Error('El PIN debe tener cuatro cifras.');
  return { pin, name, ...(target === 'bc250' ? { target } : {}) };
}
