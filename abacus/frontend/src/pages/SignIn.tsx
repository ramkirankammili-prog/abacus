import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowRight, Leaf, LockKeyhole, Mail, ShieldCheck, Snowflake } from 'lucide-react'
import { supabase, isSupabaseConfigured } from '../supabaseClient'
import './SignIn.css'

export default function SignIn() {
  const navigate = useNavigate()
  const [lightOn, setLightOn] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      const { error: authError } = await supabase.auth.signInWithPassword({ email: email.trim(), password })
      if (authError) {
        setError(authError.message)
        return
      }
      // Keep the existing Abacus app and route unchanged after a successful sign-in.
      navigate('/', { replace: true })
    } catch (err: any) {
      setError(err?.message || 'Unable to reach Supabase. Check your connection and try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className={`fr-login ${lightOn ? 'fr-login--light-on' : ''}`}>
      <div className="fr-login__room-glow" aria-hidden="true" />
      <div className="fr-login__lamp-area">
        <div className="fr-login__lamp-wire" />
        <div className="fr-login__lamp-shade">
          <div className="fr-login__shade-top" />
          <div className="fr-login__lamp-bulb" />
        </div>
        <div className="fr-login__lamp-beam" />
        <button
          type="button"
          className="fr-login__lamp-cord"
          onClick={() => setLightOn(current => !current)}
          aria-label={lightOn ? 'Turn the light off' : 'Turn the light on to reveal the sign-in form'}
          title="Click the thread to turn the light on or off"
        >
          <span className="fr-login__thread-line" />
          <span className="fr-login__thread-handle" />
        </button>
      </div>

      <div className="fr-login__layout">
        <section className="fr-login__brand-content" aria-label="FrostRoute AI introduction">
          <div className="fr-login__brand-logo">
            <span className="fr-login__logo-symbol"><Snowflake size={25} /></span>
            <span>FrostRoute <b>AI</b></span>
          </div>

          <div className="fr-login__brand-copy">
            <span className="fr-login__eyebrow">SMART LOGISTICS · FRESHER FUTURES</span>
            <h1>Every route.<br /><span>Smarter and fresher.</span></h1>
            <p>Intelligent routing for perishable food supply chains. Reduce delivery time, prevent food waste, and protect product freshness.</p>
            <div className="fr-login__feature-list">
              <div><span>✓</span> Shelf-life aware routing</div>
              <div><span>✓</span> Multi-depot fleet planning</div>
              <div><span>✓</span> Cold-chain visibility</div>
            </div>
          </div>

          <div className="fr-login__brand-bottom"><Leaf size={14} /> Intelligent supply chain management</div>
        </section>

        <section className="fr-login__card-wrap" aria-label="Sign in">
          <div className="fr-login__card">
            <div className="fr-login__card-top-icon"><Snowflake size={26} /></div>
            <span className="fr-login__eyebrow">WELCOME BACK</span>
            <h2>Sign in to continue</h2>
            <p className="fr-login__subtitle">Access your FrostRoute AI workspace.</p>

            {!isSupabaseConfigured && (
              <div role="alert" className="fr-login__config-warning">
                Supabase is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_PUBLIC_KEY in frontend/.env, then restart the frontend.
              </div>
            )}

            <form onSubmit={onSubmit}>
              <label htmlFor="signin-email">Email address</label>
              <div className="fr-login__input-wrap">
                <Mail size={17} aria-hidden="true" />
                <input
                  id="signin-email"
                  type="email"
                  autoComplete="email"
                  placeholder="Enter your email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  required
                />
              </div>

              <label htmlFor="signin-password">Password</label>
              <div className="fr-login__input-wrap">
                <LockKeyhole size={17} aria-hidden="true" />
                <input
                  id="signin-password"
                  type="password"
                  autoComplete="current-password"
                  placeholder="Enter your password"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  required
                />
              </div>

              {error && <p role="alert" className="fr-login__error">{error}</p>}

              <button className="fr-login__submit" type="submit" disabled={busy}>
                <span>{busy ? 'Signing in…' : 'Sign in'}</span>
                <ArrowRight size={19} />
              </button>
            </form>

            <p className="fr-login__signup">New to FrostRoute AI? <Link to="/signup">Create an account</Link></p>
            <p className="fr-login__security"><ShieldCheck size={13} /> Secure sign-in · Protected workspace</p>
          </div>
        </section>
      </div>

      <p className="fr-login__bottom-note">FrostRoute AI <span>·</span> Intelligent cold-chain logistics <span>·</span> Built for fresher futures</p>
    </main>
  )
}
