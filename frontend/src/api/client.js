const TOKEN_KEY = 'greentrace.token'

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    // storage unavailable (private mode); session will just not persist
  }
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(formatDetail(detail))
    this.status = status
    this.detail = detail
  }
}

// FastAPI returns either a string or a list of {loc, msg} validation errors.
function formatDetail(detail) {
  if (typeof detail === 'string') return detail
  if (detail && typeof detail.message === 'string') return detail.message
  if (Array.isArray(detail)) {
    return detail.map((d) => `${d.loc.slice(1).join('.')}: ${d.msg}`).join('; ')
  }
  return 'Request failed'
}

// For <iframe>/<a> targets that can't send an Authorization header (e.g. the bill PDF).
export async function fetchBlobUrl(path) {
  const res = await fetch(`/api${path}`, { headers: { Authorization: `Bearer ${getToken()}` } })
  if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => null))?.detail)
  return URL.createObjectURL(await res.blob())
}

// A rendered bill page (PNG) plus the server's page count and snippet-highlight status.
export async function fetchPage(billId, page, highlight = true) {
  const res = await fetch(`/api/bills/${billId}/pages/${page}?highlight=${highlight}`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  })
  if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => null))?.detail)
  return {
    url: URL.createObjectURL(await res.blob()),
    pageCount: Number(res.headers.get('X-Page-Count') || 1),
    highlight: res.headers.get('X-Highlight'),
  }
}

export async function api(path, { method = 'GET', body, params } = {}) {
  const url = new URL(`/api${path}`, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v)
    })
  }
  const headers = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  // FormData sets its own multipart Content-Type (with boundary).
  const isForm = body instanceof FormData
  if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json'

  const res = await fetch(url, {
    method,
    headers,
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  })
  if (res.status === 401 && token) {
    setToken(null)
    window.dispatchEvent(new Event('greentrace:logout'))
  }
  const data = res.status === 204 ? null : await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, data?.detail)
  return data
}
