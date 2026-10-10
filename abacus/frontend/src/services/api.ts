import axios from 'axios'
import { supabase } from '../supabaseClient'

// The browser only talks to our FastAPI backend for data. The backend holds the Supabase keys,
// checks the user's session token and then reads/writes Supabase on their behalf.
export const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000', timeout: 30000 })

api.interceptors.request.use(async config => {
  const { data } = await supabase.auth.getSession()
  if (data.session?.access_token) config.headers.set('Authorization', `Bearer ${data.session.access_token}`)
  return config
})

api.interceptors.response.use(r => r, async error => {
  // Expired / invalid session: sign out so the route guard sends the user to /signin.
  if (error?.response?.status === 401) await supabase.auth.signOut()
  return Promise.reject(error)
})

export async function get<T=any>(path:string):Promise<T>{ return (await api.get(path)).data }
export async function post<T=any>(path:string, body?:any):Promise<T>{ return (await api.post(path,body ?? {})).data }
