import type { ReactNode } from 'react'
import { Leaf } from 'lucide-react'
import { isSupabaseConfigured } from '../supabaseClient'

export default function AuthLayout({ title, subtitle, children, footer }: { title: string, subtitle: string, children: ReactNode, footer: ReactNode }) {
  return (
    <div className="relative grid min-h-screen place-items-center overflow-hidden bg-[#081321] px-4 py-10 text-[#e8eef7]">
      <div className="pointer-events-none absolute -top-40 left-1/2 h-96 w-[42rem] -translate-x-1/2 rounded-full bg-[#3bdcc1]/10 blur-3xl" />
      <div className="relative w-full max-w-md">
        <div className="mb-7 flex items-center justify-center gap-3">
          <div className="grid h-11 w-11 place-items-center rounded-xl bg-gradient-to-br from-[#3ce0c1] to-[#158e93] text-[#05252b] shadow-lg shadow-[#20cdb3]/20"><Leaf size={24} /></div>
          <div>
            <div className="text-xl font-extrabold tracking-tight text-[#f4f8ff]">FrostRoute<span className="text-[#3bdcc1]"> AI</span></div>
            <div className="text-[9px] tracking-[0.18em] text-[#72839b]">INTELLIGENT COLD CHAIN</div>
          </div>
        </div>
        <div className="rounded-2xl border border-solid border-[#213148] bg-[#0b1727] p-7 shadow-2xl shadow-black/40">
          <h1 className="m-0 text-2xl font-bold text-[#f4f8ff]">{title}</h1>
          <p className="mb-6 mt-1 text-sm text-[#8d9bad]">{subtitle}</p>
          {!isSupabaseConfigured && (
            <div role="alert" className="mb-4 rounded-lg border border-solid border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-200">
              Supabase is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_PUBLIC_KEY in frontend/.env and restart the dev server.
            </div>
          )}
          {children}
        </div>
        <p className="mt-5 text-center text-sm text-[#8d9bad]">{footer}</p>
      </div>
    </div>
  )
}

export const inputClass = 'mt-1.5 block w-full rounded-lg border border-solid border-[#26374f] bg-[#101f31] px-3 py-2.5 text-sm text-[#e8eef7] outline-none placeholder:text-[#5d6e85] focus:border-[#3bdcc1] focus:ring-2 focus:ring-[#3bdcc1]/25'
export const buttonClass = 'mt-2 w-full rounded-lg border-0 bg-[#3bdcc1] px-4 py-2.5 text-sm font-bold text-[#05252b] transition hover:bg-[#5ce6cf] disabled:cursor-wait disabled:opacity-60'
