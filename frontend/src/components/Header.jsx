import { RefreshIcon } from './Icons.jsx'

// backendOnline is null while checking, then true or false.
function BackendStatus({ backendOnline }) {
  let label = 'Checking backend…'
  let tone = 'checking'
  if (backendOnline === true) {
    label = 'Backend connected'
    tone = 'online'
  } else if (backendOnline === false) {
    label = 'Backend offline'
    tone = 'offline'
  }
  return (
    <span className={`status-pill ${tone}`}>
      <span className="status-dot" />
      {label}
    </span>
  )
}

export default function Header({ backendOnline, loading, lastUpdated, onRefresh }) {
  return (
    <header className="header">
      <div>
        <h1 className="page-title">Work Queue</h1>
        <p className="page-subtitle">
          Vendor emails and bank-change requests under review
          {lastUpdated && <> · Updated {lastUpdated.toLocaleTimeString()}</>}
        </p>
      </div>

      <div className="header-actions">
        <BackendStatus backendOnline={backendOnline} />
        <span className="role-chip" title="Role comes from the dev API key">
          <span className="role-avatar">A</span>
          Accountant · dev
        </span>
        <button type="button" className="button" onClick={onRefresh} disabled={loading}>
          <span className={loading ? 'spin' : ''}>
            <RefreshIcon size={16} />
          </span>
          Refresh
        </button>
      </div>
    </header>
  )
}
