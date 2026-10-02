const BASE = process.env.NEXT_PUBLIC_API_URL || '';
export const apiUrl = (p: string) => {
  const base = BASE.replace(/\/$/, '');
  // if BASE empty, use same origin (relative) — works when frontend proxy not set
  if (!base) return p;
  return `${base}${p}`;
};
export async function apiFetch(path: string, opts: RequestInit = {}) {
  const url = apiUrl(path);
  const res = await fetch(url, { ...opts, headers: { 'Content-Type': 'application/json', ...(opts.headers as any) } });
  const text = await res.text();
  let data: any;
  try { data = JSON.parse(text); } catch { data = { raw: text }; }
  if (!res.ok) throw new Error(data.detail || data.message || text || `HTTP ${res.status}`);
  return data;
}
