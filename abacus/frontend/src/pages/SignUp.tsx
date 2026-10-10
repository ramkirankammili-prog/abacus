import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { supabase } from '../supabaseClient'
import AuthLayout, { buttonClass, inputClass } from '../components/AuthLayout'

export default function SignUp() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(''); setInfo('')
    if (password.length < 6) { setError('Password must be at least 6 characters.'); return }
    if (password !== confirm) { setError('Passwords do not match.'); return }
    setBusy(true)
    try {
      const { data, error: authError } = await supabase.auth.signUp({ email: email.trim(), password })
      if (authError) { setError(authError.message); return }
      // Supabase hides "already registered" by returning a user with no identities.
      if (data.user && data.user.identities && data.user.identities.length === 0) {
        setError('This email is already registered. Please sign in instead.')
        return
      }
      if (data.session) { navigate('/', { replace: true }); return }
      // Email confirmation is switched on in Supabase: no session until the email is confirmed.
      setInfo('Account created. Check your inbox and confirm your email, then sign in.')
    } catch (err: any) {
      setError(err?.message || 'Unable to reach Supabase. Check your connection and try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout title="Create your account" subtitle="Start routing perishable goods smarter." footer={<>Already have an account? <Link to="/signin" className="font-semibold text-[#3bdcc1] no-underline hover:underline">Sign in</Link></>}>
      <form onSubmit={onSubmit}>
        <label className="mb-4 block text-sm font-medium text-[#c4d0e0]">Email
          <input className={inputClass} type="email" autoComplete="email" required placeholder="you@company.com" value={email} onChange={e => setEmail(e.target.value)} />
        </label>
        <label className="mb-4 block text-sm font-medium text-[#c4d0e0]">Password
          <input className={inputClass} type="password" autoComplete="new-password" required minLength={6} placeholder="At least 6 characters" value={password} onChange={e => setPassword(e.target.value)} />
        </label>
        <label className="mb-4 block text-sm font-medium text-[#c4d0e0]">Confirm password
          <input className={inputClass} type="password" autoComplete="new-password" required placeholder="Repeat your password" value={confirm} onChange={e => setConfirm(e.target.value)} />
        </label>
        <button className={buttonClass} type="submit" disabled={busy}>{busy ? 'Creating account…' : 'Sign up'}</button>
        {error && <p role="alert" className="mb-0 mt-3 text-sm text-rose-400">{error}</p>}
        {info && <p role="status" className="mb-0 mt-3 text-sm text-[#3bdcc1]">{info}</p>}
      </form>
    </AuthLayout>
  )
}
