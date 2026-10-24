import { BuildingIcon, InboxIcon, ListIcon, ShieldIcon } from './Icons.jsx'

// Only the Work Queue exists in Stage 1. The others are placeholders.
const NAV_ITEMS = [
  { label: 'Work Queue', icon: InboxIcon, active: true },
  { label: 'Audit Log', icon: ListIcon, soon: true },
  { label: 'Vendors', icon: BuildingIcon, soon: true },
]

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">
          <ShieldIcon size={22} />
        </div>
        <div className="brand-text">
          <span className="brand-name">Vouch</span>
          <span className="brand-tagline">AP Fraud &amp; Bank Change Guard</span>
        </div>
      </div>

      <nav className="nav">
        <span className="nav-heading">Workspace</span>
        {NAV_ITEMS.map(({ label, icon: NavIcon, active, soon }) => (
          <a
            key={label}
            href="#"
            className={`nav-link${active ? ' active' : ''}${soon ? ' disabled' : ''}`}
            aria-current={active ? 'page' : undefined}
            aria-disabled={soon ? 'true' : undefined}
            onClick={(event) => event.preventDefault()}
          >
            <NavIcon />
            <span className="nav-label">{label}</span>
            {soon && <span className="nav-soon">Soon</span>}
          </a>
        ))}
      </nav>

      <div className="sidebar-footer">
        <p className="sidebar-note">
          The agent can only <strong>propose</strong>. Moving money requires a human approval and the gateway.
        </p>
      </div>
    </aside>
  )
}
