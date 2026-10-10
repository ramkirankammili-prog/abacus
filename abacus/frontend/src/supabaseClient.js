import { createClient } from '@supabase/supabase-js'

// Used ONLY for Supabase Auth (sign up / sign in / session) and realtime change notifications.
// All table data is fetched through the FastAPI backend, which keeps its own copy of the keys.
// The public (publishable) key is designed to be visible to browsers; it is read from the
// environment (frontend/.env) instead of being hard-coded, and Row Level Security protects the data.
const rawUrl = import.meta.env.VITE_SUPABASE_URL || ''
// Accept either the project URL or the REST URL (…/rest/v1/).
const supabaseUrl = rawUrl.trim().replace(/\/+$/, '').replace(/\/rest\/v1$/, '')
const supabasePublicKey = (import.meta.env.VITE_SUPABASE_PUBLIC_KEY || '').trim()

export const isSupabaseConfigured = Boolean(supabaseUrl && supabasePublicKey)

if (!isSupabaseConfigured) {
  console.error('Supabase is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_PUBLIC_KEY in frontend/.env')
}

// Placeholders keep the app from crashing on load when the env file is missing.
export const supabase = createClient(
  supabaseUrl || 'http://localhost:54321',
  supabasePublicKey || 'missing-key',
)

export default supabase
