import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, ClipboardList, LogOut, RefreshCw, Snowflake, Truck } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { get, post } from '../services/api'

type DriverOrder = { id: string; customer: string; address?: string; product_id: string; quantity: number; window_start?: string; window_end?: string; status: string; driver_note?: string; assigned_vehicle_id?: string }
type DriverPayload = { driver: { id: string; name: string; vehicle_id?: string; status?: string }; orders: DriverOrder[]; fetched_at?: string }

function DriverSkeleton() {
  return <div className="driver-skeleton" aria-label="Loading driver workspace">
    <div className="driver-skeleton__hero"><span className="skeleton-line skeleton-line--short"/><span className="skeleton-line"/><span className="skeleton-line skeleton-line--medium"/></div>
    {[1, 2, 3].map(n => <div className="driver-skeleton__row" key={n}><span className="skeleton-circle"/><div><span className="skeleton-line"/><span className="skeleton-line skeleton-line--medium"/></div><span className="skeleton-line skeleton-line--button"/></div>)}
  </div>
}

export default function DriverHome() {
  const { user, signOut } = useAuth()
  const [payload, setPayload] = useState<DriverPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [savingId, setSavingId] = useState('')
  const [error, setError] = useState('')
  const [toast, setToast] = useState('')
  const [issueNotes, setIssueNotes] = useState<Record<string, string>>({})

  const refresh = useCallback(async () => {
    setError('')
    try { setPayload(await get<DriverPayload>('/api/driver/dashboard')) }
    catch (e: any) { setError(e?.response?.data?.detail || 'Cannot connect to the driver workspace. Check your internet connection and backend.') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => { if (!toast) return; const t = window.setTimeout(() => setToast(''), 3200); return () => window.clearTimeout(t) }, [toast])

  async function updateStatus(order: DriverOrder, status: string) {
    setSavingId(order.id); setError('')
    try {
      await post(`/api/driver/orders/${order.id}/status`, { status, note: issueNotes[order.id] || '' })
      await refresh()
      setToast(`${order.id} updated to ${status}`)
    } catch (e: any) { setError(e?.response?.data?.detail || 'Unable to update this order. Check the connection and try again.') }
    finally { setSavingId('') }
  }

  const orders = payload?.orders || []
  const pending = orders.filter(o => !['Delivered', 'Cancelled'].includes(o.status)).length
  return <div className="driver-shell">
    <header className="driver-topbar"><div className="driver-brand"><span><Snowflake size={22}/></span><div><b>FrostRoute AI</b><small>DRIVER WORKSPACE</small></div></div><div className="driver-account"><span>{user?.email}</span><button className="icon-button" title="Sign out" onClick={signOut}><LogOut size={17}/></button></div></header>
    <main className="driver-main">
      {loading ? <DriverSkeleton /> : <>
        <section className="driver-welcome"><div><div className="eyebrow">MY DELIVERY ROUTES</div><h1>Hello, {payload?.driver?.name || 'Driver'}</h1><p>Assigned deliveries, delivery windows, and status updates.</p></div><button className="btn secondary" onClick={() => { setLoading(true); void refresh() }}><RefreshCw size={15}/> Refresh</button></section>
        {error && <div className="error-banner" role="alert"><AlertTriangle size={17}/><span>{error}</span><button onClick={() => setError('')}>×</button></div>}
        {!payload && error && <div className="driver-card driver-help"><b>Need access?</b><p>If you just received a driver account, ask the manager to link your Supabase user ID to a Drivers record. Your account ID is:</p><code>{user?.id}</code></div>}
        {payload && <>
          <div className="driver-kpis"><div className="driver-kpi"><ClipboardList/><small>Assigned orders</small><b>{orders.length}</b></div><div className="driver-kpi"><Truck/><small>Active deliveries</small><b>{pending}</b></div><div className="driver-kpi"><CheckCircle2/><small>Delivered</small><b>{orders.filter(o => o.status === 'Delivered').length}</b></div></div>
          <div className="driver-card driver-meta"><div><small>Driver ID</small><b>{payload.driver.id}</b></div><div><small>Assigned vehicle</small><b>{payload.driver.vehicle_id || 'Ask manager to assign'}</b></div><div><small>Availability</small><b>{payload.driver.status || 'Available'}</b></div></div>
          <section className="driver-orders"><div className="driver-section-heading"><div><h2>My orders</h2><p>Update the status as each delivery progresses.</p></div></div>
            {orders.length === 0 ? <div className="driver-card driver-empty"><ClipboardList size={28}/><b>No orders assigned yet</b><p>Your manager's route plan will appear here after orders are assigned to you.</p></div> : orders.map(order => <article className="driver-card driver-order" key={order.id}>
              <div className="driver-order-head"><div><span className="driver-order-id">{order.id}</span><h3>{order.customer}</h3><p>{order.address || 'Delivery address not provided'}</p></div><span className={'status-tag '+order.status.toLowerCase().replace(/[^a-z]/g, '-')}>{order.status}</span></div>
              <div className="driver-order-details"><div><small>Product</small><b>{order.product_id}</b></div><div><small>Quantity</small><b>{order.quantity}</b></div><div><small>Delivery window</small><b>{order.window_start || '08:00'} – {order.window_end || '17:00'}</b></div></div>
              {order.driver_note && <div className="driver-inline-note"><AlertTriangle size={15}/>{order.driver_note}</div>}
              {order.status !== 'Delivered' && order.status !== 'Cancelled' && <div className="driver-order-actions">
                {order.status === 'Pending' && <button className="btn secondary" disabled={savingId === order.id} onClick={() => void updateStatus(order, 'Picked up')}>Mark picked up</button>}
                {order.status === 'Issue' && <button className="btn secondary" disabled={savingId === order.id} onClick={() => void updateStatus(order, 'In transit')}>Resume delivery</button>}
                {['Pending', 'Picked up'].includes(order.status) && <button className="btn primary" disabled={savingId === order.id} onClick={() => void updateStatus(order, 'In transit')}>Start delivery</button>}
                {['Picked up', 'In transit'].includes(order.status) && <button className="btn primary" disabled={savingId === order.id} onClick={() => void updateStatus(order, 'Delivered')}>Mark delivered</button>}
                <div className="driver-issue-form"><input aria-label={`Issue note for ${order.id}`} placeholder="Issue note (optional)" value={issueNotes[order.id] || ''} onChange={e => setIssueNotes({ ...issueNotes, [order.id]: e.target.value })}/><button className="btn danger" disabled={savingId === order.id} onClick={() => void updateStatus(order, 'Issue')}>Report issue</button></div>
              </div>}
            </article>)}
          </section>
        </>}
      </>}
    </main>
    {toast && <div className="toast"><CheckCircle2 size={17}/>{toast}</div>}
  </div>
}
