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
