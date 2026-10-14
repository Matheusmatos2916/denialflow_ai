const base = (import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000').replace(/\/$/, '')
const staticToken = import.meta.env.VITE_API_ACCESS_TOKEN || ''

function formatErrorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map(issue => {
      if (!issue || typeof issue !== 'object') return String(issue)
      const item = issue as { loc?: unknown[]; msg?: unknown }
      const location = Array.isArray(item.loc)
        ? item.loc.filter(part => part !== 'body').map(String).join('.')
        : ''
      const message = typeof item.msg === 'string' ? item.msg : 'Invalid request'
      return location ? `${location}: ${message}` : message
    }).join('; ')
  }
  if (detail && typeof detail === 'object') return JSON.stringify(detail)
  return fallback
}

export async function apiRequest<T>(method: string, path: string, options: { body?: BodyInit; json?: unknown; timeout?: number } = {}): Promise<T> {
  const sessionToken = localStorage.getItem('authToken') || staticToken
  const headers: Record<string, string> = sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {}
  let body = options.body
  if (options.json !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(options.json) }
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), options.timeout ?? 30000)
  try {
    const response = await fetch(`${base}${path}`, { method, headers, body, signal: controller.signal })
    const text = await response.text()
    let data: any = text
    try { data = text ? JSON.parse(text) : null } catch { /* plain error */ }
    if (!response.ok) {
      const message = formatErrorDetail(data?.detail, `HTTP ${response.status}`)
      if (response.status === 404 && path.match(/^\/v1\/workflows\/[^/]+$/)) {
        localStorage.removeItem('lastRunId')
      }
      if (response.status === 401) localStorage.removeItem('authToken')
      throw new Error(response.status === 401 ? 'Session expired. Please log in again.' : message)
    }
    return data as T
  } finally { clearTimeout(timer) }
}
export const api = {
  get: <T>(path:string) => apiRequest<T>('GET', path),
  post: <T>(path:string, json?:unknown, timeout?:number) => apiRequest<T>('POST', path, { json, timeout }),
  patch: <T>(path:string, json?:unknown) => apiRequest<T>('PATCH', path, { json }),
  put: <T>(path:string, body:BodyInit) => apiRequest<T>('PUT', path, { body }),
  delete: <T=unknown>(path:string) => apiRequest<T>('DELETE', path),
}
export const apiBase = base
