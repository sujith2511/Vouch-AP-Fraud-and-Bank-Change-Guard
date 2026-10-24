// Simple inline SVG icons (no icon library needed).
// They use currentColor, so they take the text color of their parent.

function Icon({ children, size = 18 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  )
}

export function ShieldIcon(props) {
  return (
    <Icon {...props}>
      <path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6l8-3z" />
      <path d="M8.5 12l2.5 2.5 4.5-5" />
    </Icon>
  )
}

export function InboxIcon(props) {
  return (
    <Icon {...props}>
      <path d="M3 13h5l1.5 3h5L16 13h5" />
      <path d="M5 5h14l2 8v6H3v-6l2-8z" />
    </Icon>
  )
}

export function ListIcon(props) {
  return (
    <Icon {...props}>
      <path d="M9 6h11M9 12h11M9 18h11" />
      <path d="M4 6h.01M4 12h.01M4 18h.01" />
    </Icon>
  )
}

export function BuildingIcon(props) {
  return (
    <Icon {...props}>
      <path d="M3 21h18M5 21V10M19 21V10M9 21v-6h6v6" />
      <path d="M2 10l10-6 10 6" />
    </Icon>
  )
}

export function BankIcon(props) {
  return (
    <Icon {...props}>
      <path d="M3 10l9-6 9 6" />
      <path d="M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 21h18" />
    </Icon>
  )
}

export function UserCheckIcon(props) {
  return (
    <Icon {...props}>
      <circle cx="9" cy="8" r="4" />
      <path d="M2 21c0-3.9 3.1-7 7-7s7 3.1 7 7" />
      <path d="M16 11l2 2 4-4" />
    </Icon>
  )
}

export function CheckCircleIcon(props) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M8 12l3 3 5-6" />
    </Icon>
  )
}

export function BanIcon(props) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M5.6 5.6l12.8 12.8" />
    </Icon>
  )
}

export function RefreshIcon(props) {
  return (
    <Icon {...props}>
      <path d="M20 11a8 8 0 0 0-14.9-3.9L4 9" />
      <path d="M4 4v5h5" />
      <path d="M4 13a8 8 0 0 0 14.9 3.9L20 15" />
      <path d="M20 20v-5h-5" />
    </Icon>
  )
}

export function AlertIcon(props) {
  return (
    <Icon {...props}>
      <path d="M12 3l10 18H2L12 3z" />
      <path d="M12 10v4M12 17.5h.01" />
    </Icon>
  )
}
