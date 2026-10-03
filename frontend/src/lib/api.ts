const BASE = process.env.NEXT_PUBLIC_API_URL || '';
export const apiUrl = (p: string) => {
  const base = BASE.replace(/\/$/, '');
  return base ? `${base}${p}` : p;
};
export const wsUrl = (p: string) => {
  const base = BASE.replace(/\/$/, '');
  if (base) return base.replace(/^http/, 'ws') + p;
  if (typeof window === 'undefined') return p;
  return `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}${p}`;
};
export async function apiFetch(path: string, opts: RequestInit = {}) {
  const res = await fetch(apiUrl(path), { ...opts, headers: { 'Content-Type': 'application/json', ...(opts.headers as any) } });
  const text = await res.text();
  let data: any;
  try { data = JSON.parse(text); } catch { data = { raw: text }; }
  if (!res.ok) throw new Error(data.detail || data.message || text || `HTTP ${res.status}`);
  return data;
}
export const get = (path: string) => apiFetch(path);
export const post = (path: string, body?: any) => apiFetch(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });
