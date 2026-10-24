import { STATES, STATE_LABELS, displayName, domainOf, formatDate, formatMoney, last4 } from '../format.js'
import { AlertIcon, InboxIcon, RefreshIcon } from './Icons.jsx'

const SEED_COMMAND = 'python -m vouch.run_pipeline --emails data/fixtures/emails_fixture.jsonl --db vouch.db'

function StateBadge({ state }) {
  return <span className={`badge state-${state.toLowerCase()}`}>{STATE_LABELS[state] ?? state}</span>
}

// SPF / DKIM / DMARC results from email.auth, e.g. { spf: 'pass', dkim: 'fail', dmarc: 'pass' }
function AuthChips({ auth }) {
  if (!auth) return <span className="muted">—</span>
  return (
    <div className="auth-chips">
      {['spf', 'dkim', 'dmarc'].map((key) => {
        const result = auth[key]
        const tone = result === 'pass' ? 'pass' : result ? 'fail' : 'unknown'
        return (
          <span key={key} className={`auth-chip ${tone}`} title={`${key.toUpperCase()}: ${result ?? 'not reported'}`}>
            {key.toUpperCase()}
          </span>
        )
      })}
    </div>
  )
}

// Compares the sender and reply-to domains with the vendor's domain on file.
function SenderCell({ item }) {
  const email = item.email ?? {}
  const vendorDomain = item.vendor?.domain?.toLowerCase()
  const fromDomain = domainOf(email.from)
  const replyDomain = domainOf(email.reply_to)
  const offDomain = vendorDomain && fromDomain && fromDomain !== vendorDomain
  const replyDiffers = vendorDomain && replyDomain && replyDomain !== vendorDomain

  return (
    <div className="cell-stack">
      <span className="cell-primary">{displayName(email.from)}</span>
      <span className="cell-secondary">{fromDomain ?? '—'}</span>
      {(offDomain || replyDiffers) && (
        <div className="tag-row">
          {offDomain && <span className="tag warn">Off-domain sender</span>}
          {replyDiffers && <span className="tag warn">Reply-to differs</span>}
        </div>
      )}
    </div>
  )
}

// Bank accounts arrive already masked by the backend; we only show the last 4 digits.
function BankChangeCell({ item }) {
  if (!item.is_bank_change) {
    return <span className="muted">No change</span>
  }
  const current = item.vendor?.bank?.account
  const claimed = item.claim?.claimed_bank?.account
  return (
    <div className="cell-stack">
      <span className="tag danger">Change requested</span>
      <span className="cell-secondary mono">
        ••{last4(current)} → ••{last4(claimed)}
      </span>
    </div>
  )
}

// Shows only what the agent actually wrote (verdict.verdict and verdict.confidence).
function VerdictCell({ verdict }) {
  if (!verdict?.verdict) {
    return <span className="muted">Awaiting agent</span>
  }
  const confidence = typeof verdict.confidence === 'number' ? `${Math.round(verdict.confidence * 100)}% conf.` : null
  return (
    <div className="cell-stack">
      <span className={`badge verdict-${verdict.verdict}`}>{verdict.verdict}</span>
      {confidence && <span className="cell-secondary">{confidence}</span>}
    </div>
  )
}

function FilterBar({ items, filter, onFilterChange, bankOnly, onBankOnlyChange }) {
  const countFor = (state) => items.filter((item) => item.state === state).length
  return (
    <div className="filter-bar">
      <div className="tabs" role="tablist" aria-label="Filter by state">
        <button
          type="button"
          role="tab"
          aria-selected={filter === 'ALL'}
          className={`tab${filter === 'ALL' ? ' active' : ''}`}
          onClick={() => onFilterChange('ALL')}
        >
          All <span className="tab-count">{items.length}</span>
        </button>
        {STATES.map((state) => (
          <button
            key={state}
            type="button"
            role="tab"
            aria-selected={filter === state}
            className={`tab${filter === state ? ' active' : ''}`}
            onClick={() => onFilterChange(state)}
          >
            {STATE_LABELS[state]} <span className="tab-count">{countFor(state)}</span>
          </button>
        ))}
      </div>
      <label className="toggle">
        <input type="checkbox" checked={bankOnly} onChange={(event) => onBankOnlyChange(event.target.checked)} />
        <span className="toggle-track" />
        Bank changes only
      </label>
    </div>
  )
}

function LoadingRows() {
  return (
    <tbody>
      {[1, 2, 3, 4, 5].map((row) => (
        <tr key={row} className="skeleton-row">
          {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((cell) => (
            <td key={cell}>
              <span className="skeleton" />
            </td>
          ))}
        </tr>
      ))}
    </tbody>
  )
}

function Message({ icon, tone, title, children }) {
  return (
    <div className={`message ${tone}`}>
      <div className="message-icon">{icon}</div>
      <h3>{title}</h3>
      {children}
    </div>
  )
}

export default function RequestsTable({ items, loading, error, onRetry, filter, onFilterChange, bankOnly, onBankOnlyChange }) {
  const visibleItems = items.filter(
    (item) => (filter === 'ALL' || item.state === filter) && (!bankOnly || item.is_bank_change),
  )

  let body
  if (error) {
    body = (
      <Message icon={<AlertIcon size={26} />} tone="error" title="Couldn't load work items">
        <p>{error}</p>
        <button type="button" className="button" onClick={onRetry}>
          <RefreshIcon size={16} /> Try again
        </button>
      </Message>
    )
  } else if (!loading && items.length === 0) {
    body = (
      <Message icon={<InboxIcon size={26} />} tone="empty" title="No work items yet">
        <p>The backend is connected, but its database has no vendor emails. Once demo data is loaded, requests appear here.</p>
        <p className="muted">A teammate can load the fixture emails from the repo root (with the API stopped):</p>
        <code className="command">{SEED_COMMAND}</code>
      </Message>
    )
  } else if (!loading && visibleItems.length === 0) {
    body = (
      <Message icon={<InboxIcon size={26} />} tone="empty" title="Nothing matches this filter">
        <p>Try another state or turn off “Bank changes only”.</p>
      </Message>
    )
  }

  return (
    <section className="card">
      <div className="card-header">
        <div>
          <h2 className="card-title">Vendor requests</h2>
          <p className="card-subtitle">Each vendor email becomes a work item that moves through the review workflow.</p>
        </div>
      </div>

      <FilterBar
        items={items}
        filter={filter}
        onFilterChange={onFilterChange}
        bankOnly={bankOnly}
        onBankOnlyChange={onBankOnlyChange}
      />

      {body ?? (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Item</th>
                <th>Vendor</th>
                <th>Sender</th>
                <th>Email auth</th>
                <th className="align-right">Amount</th>
                <th>Bank account</th>
                <th>Agent verdict</th>
                <th>State</th>
                <th>Updated</th>
              </tr>
            </thead>
            {loading ? (
              <LoadingRows />
            ) : (
              <tbody>
                {visibleItems.map((item) => (
                  <tr key={item.id} className={item.is_bank_change ? 'row-flagged' : ''}>
                    <td>
                      <div className="cell-stack">
                        <span className="cell-primary mono">{item.id}</span>
                        <span className="cell-secondary">{item.claim?.invoice_number ?? 'No invoice #'}</span>
                      </div>
                    </td>
                    <td>
                      <div className="cell-stack">
                        <span className="cell-primary">{item.vendor?.name ?? item.vendor_id}</span>
                        <span className="cell-secondary">{item.vendor?.domain ?? '—'}</span>
                      </div>
                    </td>
                    <td>
                      <SenderCell item={item} />
                    </td>
                    <td>
                      <AuthChips auth={item.email?.auth} />
                    </td>
                    <td className="align-right">
                      <span className="cell-primary">{formatMoney(item.claim?.amount, item.claim?.currency)}</span>
                    </td>
                    <td>
                      <BankChangeCell item={item} />
                    </td>
                    <td>
                      <VerdictCell verdict={item.verdict} />
                    </td>
                    <td>
                      <StateBadge state={item.state} />
                    </td>
                    <td className="nowrap muted">{formatDate(item.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            )}
          </table>
        </div>
      )}
    </section>
  )
}
