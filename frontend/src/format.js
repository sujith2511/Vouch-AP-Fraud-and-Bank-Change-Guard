// Helpers that turn raw backend fields into display text.

// The work-item states defined in vouch/core.py (STATES), in workflow order.
export const STATES = ['NEW', 'PROPOSED', 'NEEDS_INFO', 'APPROVED', 'REJECTED', 'POSTED']

export const STATE_LABELS = {
  NEW: 'New',
  PROPOSED: 'Proposed',
  NEEDS_INFO: 'Needs info',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
  POSTED: 'Posted',
}

// "Priya Castillo <priya@acme.example>" -> "acme.example"
export function domainOf(address) {
  if (!address) return null
  const match = String(address).match(/@([^>\s]+)/)
  return match ? match[1].toLowerCase() : null
}

// "Priya Castillo <priya@acme.example>" -> "Priya Castillo"
export function displayName(address) {
  if (!address) return '—'
  const name = String(address).split('<')[0].trim()
  return name || String(address)
}

export function formatMoney(amount, currency = 'USD') {
  if (amount == null) return '—'
  try {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(amount)
  } catch {
    return `${amount} ${currency}`
  }
}

// The backend already masks account numbers ("******1234"); show the last 4.
export function last4(account) {
  if (!account) return '????'
  return String(account).slice(-4)
}

export function formatDate(isoString) {
  if (!isoString) return '—'
  const date = new Date(isoString)
  if (Number.isNaN(date.getTime())) return isoString
  return date.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}
