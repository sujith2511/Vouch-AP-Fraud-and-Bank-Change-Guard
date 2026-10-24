import { useEffect, useState } from 'react'
import { checkHealth, fetchItems } from './api.js'
import Header from './components/Header.jsx'
import RequestsTable from './components/RequestsTable.jsx'
import Sidebar from './components/Sidebar.jsx'
import SummaryCards from './components/SummaryCards.jsx'

function App() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [backendOnline, setBackendOnline] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)

  // Table filters. They only change what is shown, not what is fetched.
  const [filter, setFilter] = useState('ALL')
  const [bankOnly, setBankOnly] = useState(false)

  // Bumping this number makes the effect below fetch again (used by Refresh).
  const [reloadKey, setReloadKey] = useState(0)

  // Fetch the health check and the work items when the page opens and on every refresh.
  useEffect(() => {
    let cancelled = false // ignore a response that arrives after a newer refresh started

    Promise.all([
      checkHealth(),
      fetchItems().then(
        (data) => ({ data }),
        (err) => ({ err }),
      ),
    ]).then(([online, result]) => {
      if (cancelled) return
      setBackendOnline(online)
      if (result.err) {
        setError(result.err.message)
      } else {
        setItems(result.data)
        setError(null)
        setLastUpdated(new Date())
      }
      setLoading(false)
    })

    return () => {
      cancelled = true
    }
  }, [reloadKey])

  function handleRefresh() {
    setLoading(true)
    setError(null)
    setReloadKey((key) => key + 1)
  }

  return (
    <div className="app">
      <Sidebar />
      <main className="main">
        <Header backendOnline={backendOnline} loading={loading} lastUpdated={lastUpdated} onRefresh={handleRefresh} />
        <div className="content">
          <SummaryCards items={items} loading={loading} />
          <RequestsTable
            items={items}
            loading={loading}
            error={error}
            onRetry={handleRefresh}
            filter={filter}
            onFilterChange={setFilter}
            bankOnly={bankOnly}
            onBankOnlyChange={setBankOnly}
          />
        </div>
      </main>
    </div>
  )
}

export default App
