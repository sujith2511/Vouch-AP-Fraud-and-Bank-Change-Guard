// Small helper for talking to the Vouch FastAPI backend.
//
// Requests go to /api/... and the Vite dev server forwards them to
// http://127.0.0.1:8000 (see vite.config.js).

const API_BASE = '/api'

// Comes from frontend/.env.development. Vite exposes VITE_* variables to the
// browser, so this must only ever be a development key, never a real secret.
const API_KEY = import.meta.env.VITE_VOUCH_API_KEY

async function request(path, { auth = true } = {}) {
  const headers = auth ? { 'X-API-Key': API_KEY ?? '' } : {}

  let response
  try {
    response = await fetch(API_BASE + path, { headers })
  } catch {
    throw new Error('Could not reach the Vouch backend. Is it running on port 8000?')
  }

  if (response.status === 401) {
    throw new Error('The backend rejected the API key. Check VITE_VOUCH_API_KEY in frontend/.env.development.')
  }
  // When the backend is down, the Vite proxy answers with a 5xx error itself.
  if (response.status >= 500) {
    throw new Error(`The backend returned an error (${response.status}). Make sure it is running on port 8000.`)
  }
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`)
  }
  return response.json()
}

// GET /healthz -> { ok: true }. No API key needed.
export async function checkHealth() {
  try {
    const data = await request('/healthz', { auth: false })
    return data.ok === true
  } catch {
    return false
  }
}

// GET /items -> list of work items (the backend caps limit at 500).
// Each item has: id, state, vendor_id, vendor, email, claim, verdict,
// evidence, question, answer, is_bank_change, version, created_at, updated_at.
export function fetchItems() {
  return request('/items?limit=500')
}
