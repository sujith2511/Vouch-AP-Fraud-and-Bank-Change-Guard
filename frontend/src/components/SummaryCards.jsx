import { BankIcon, BanIcon, CheckCircleIcon, InboxIcon, UserCheckIcon } from './Icons.jsx'

// Every number here is counted from the items returned by GET /items.
function countSummary(items) {
  const inState = (...states) => items.filter((item) => states.includes(item.state)).length
  return {
    total: items.length,
    bankChanges: items.filter((item) => item.is_bank_change).length,
    needsReview: inState('PROPOSED', 'NEEDS_INFO'),
    cleared: inState('APPROVED', 'POSTED'),
    rejected: inState('REJECTED'),
  }
}

export default function SummaryCards({ items, loading }) {
  const summary = countSummary(items)

  const cards = [
    { label: 'Work items', value: summary.total, hint: 'Vendor emails received', icon: InboxIcon, tone: 'navy' },
    { label: 'Bank-change requests', value: summary.bankChanges, hint: 'Ask to pay a different account', icon: BankIcon, tone: 'amber' },
    { label: 'Awaiting human review', value: summary.needsReview, hint: 'Proposed or needs info', icon: UserCheckIcon, tone: 'indigo' },
    { label: 'Approved / posted', value: summary.cleared, hint: 'Cleared by a human or policy', icon: CheckCircleIcon, tone: 'teal' },
    { label: 'Rejected', value: summary.rejected, hint: 'Blocked from payment', icon: BanIcon, tone: 'red' },
  ]

  return (
    <section className="summary-grid" aria-label="Summary">
      {cards.map(({ label, value, hint, icon: CardIcon, tone }) => (
        <div key={label} className="summary-card">
          <div className={`summary-icon ${tone}`}>
            <CardIcon size={20} />
          </div>
          <div>
            <p className="summary-label">{label}</p>
            <p className="summary-value">{loading ? <span className="skeleton skeleton-number" /> : value}</p>
            <p className="summary-hint">{hint}</p>
          </div>
        </div>
      ))}
    </section>
  )
}
