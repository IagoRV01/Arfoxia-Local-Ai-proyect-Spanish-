import type { Credentials, PreviewSession, ProjectPreview } from './types';

function validPreview(p: any): p is ProjectPreview {
  return Boolean(p) && typeof p === 'object' &&
    typeof p.id === 'string' && /^[a-f0-9]{32}$/.test(p.id) &&
    typeof p.title === 'string' && typeof p.entry === 'string' &&
    ['html', 'image', 'pdf', 'text'].includes(p.kind);
}

export function validatedPreviews(value: unknown): ProjectPreview[] {
  if (!Array.isArray(value)) return [];
  return value.filter(validPreview).slice(0, 200).map(p => {
    const {entries, ...project} = p;
    return Array.isArray(entries) ? {...project,
      entries: entries.filter(validPreview).slice(0, 100).map(({entries: _nested, ...entry}) => entry),
    } : project;
  });
}

export function previewUrl(credentials: Credentials, session: PreviewSession): string {
  // Never attach the owner Bearer token to generated HTML, its URL or WebView.
  if (!/^\/project-preview\/[A-Za-z0-9_-]{40,64}\/[^?#]+$/.test(session.path) ||
      session.path.split('/').slice(3).some(part => {
        try {const decoded = decodeURIComponent(part); return !decoded || ['.', '..'].includes(decoded) || /[\\/:\0]/.test(decoded);}
        catch {return true;}
      })) throw new Error('Arfoxia devolvió un enlace de visualización no válido.');
  const base = new URL(credentials.baseUrl);
  if (base.protocol !== 'https:' || base.username || base.password) throw new Error('El visualizador requiere el HTTPS privado de Tailscale.');
  const url = new URL(session.path, base);
  if (url.origin !== base.origin) throw new Error('La vista debe permanecer en tu PC.');
  return url.toString();
}

export function previewNavigationAllowed(url: string, initial: string): boolean {
  if (url === 'about:blank') return true;
  try {
    const target = new URL(url), source = new URL(initial);
    const prefix = source.pathname.slice(0, source.pathname.lastIndexOf('/') + 1);
    return target.origin === source.origin && target.pathname.startsWith(prefix) &&
      target.protocol === 'https:' && !target.username && !target.password;
  } catch { return false; }
}
