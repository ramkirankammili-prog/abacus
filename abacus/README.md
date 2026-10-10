# FrostRoute AI — Intelligent Perishable Food Supply Chain & Cold-Chain Routing Optimizer

Everything you see in the app is read live from **Supabase** (PostgreSQL). Users sign in with **Supabase Auth**, and changes made in Supabase or the app appear on screen in real time. Existing manager workflows are preserved; these additions introduce pre-dispatch checks, linked driver accounts, external-condition integrations, and clearer loading/error states.

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React + TypeScript, Vite, Tailwind CSS (auth pages), Recharts, React-Leaflet + OpenStreetMap, React Router |
| Backend | Python + FastAPI, Pydantic, Pandas + NumPy (analytics) |
| Database / Auth / Realtime | Supabase PostgreSQL, Supabase Auth, Supabase Realtime, Supabase Python client |
| Optimization & routing | Google OR-Tools, OSRM (road distance + travel time, with a labelled haversine fallback) |
| AI explanations | Google Gemini API (optional, deterministic fallback included) |
| Deployment | Vercel (frontend), Render (backend), Supabase Cloud (database) |
| Collaboration | Git + GitHub (CI workflow in `.github/workflows/ci.yml`) |

## How data and keys flow

```
Browser ──(user JWT)──▶ FastAPI backend ──(user JWT + Supabase public key)──▶ Supabase PostgreSQL
   │                       keys live in backend/.env                              ▲ RLS enforced
   └── Supabase Auth + Realtime (public key from frontend/.env) ─────────────────┘
```

* **Data never comes from the browser straight to the tables.** The frontend calls the FastAPI backend, which verifies the user's Supabase session, then queries Supabase using the keys stored in `backend/.env`. Row Level Security still applies because the backend runs each query as the signed-in user.
* **The frontend needs only the *public* (publishable) key**, solely for Supabase Auth (sign in / sign up) and realtime change notifications. It is read from `frontend/.env` (never hard-coded) and is designed to be visible in browsers; RLS is what protects the data. **Never put a `secret` / `service_role` key in the frontend.**
* `.env` files are git-ignored. Do not commit or share them.

## Setup

### 1. Supabase (one time)
1. Open your project → **SQL Editor** → paste `database/schema.sql` → **Run**. This creates the tables, enables Row Level Security (only signed-in users can read/write) and turns on Realtime.
2. (Optional) **Authentication → Providers → Email**: turn off *Confirm email* if you want sign-up to log users in immediately. With confirmation on, users must click the email link before signing in.
3. Re-run this updated SQL migration when updating an existing Abacus/FrostRoute installation. It adds the driver/profile/decision-report columns and changes RLS from shared write access to manager/driver policies without dropping operational rows. Existing Auth users are backfilled as managers; new sign-ups default to driver for least privilege. For a fresh install, promote the first manager account in the SQL Editor after sign-up (replace the UUID): `update public.profiles set role = 'manager' where id = 'YOUR-SUPABASE-AUTH-USER-UUID';`

### 2. Backend
```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # then enter your Supabase project URL + publishable/public key
uvicorn main:app --reload
```
API docs: http://127.0.0.1:8000/docs (data endpoints require a signed-in user's token).

### 3. Frontend (new terminal)
```powershell
cd frontend
npm install
copy .env.example .env   # already provided as .env
npm run dev
```
Open http://localhost:5173 → sign in with a manager account → Home (`/`). Open **Settings → Load sample data** only if you intentionally want to replace all operational rows with the Hyderabad sample dataset. Otherwise, add your own depots, inventory, vehicles, and drivers.

## Pages & routes
* `/signin` — `supabase.auth.signInWithPassword({ email, password })`, then redirects to `/`.
* `/signup` — `supabase.auth.signUp({ email, password })`, then redirects to `/`.
* `/` — Home (dashboard, depots, inventory, orders, vehicles, optimization, monitoring, alerts, simulator, history, AI assistant). Requires sign-in.
* Errors from Supabase are shown in a small message under the form.
* The Supabase client lives in `frontend/src/supabaseClient.js`.

## Live data
* One call (`GET /api/snapshot`) reads every table from Supabase and returns the numbers behind the dashboard, chart (Pandas analytics), tables, map and alerts.
* The browser subscribes to Supabase Realtime; any insert/update/delete in any table triggers a refresh. A 30-second poll is a safety net.
* Optimization runs are saved to the `optimization_runs` table and appear in history instantly.

## Added pre-dispatch checks, integrations, and driver workspace

- **Pre-decision validation:** `POST /api/decisions/check` checks active depots, available drivers/vehicles, product stock and expiry, current recorded temperature, refrigeration range, warehouse capacity, assigned resources, rough delivery-window fit, and the order budget. `POST /api/optimization/run` runs these checks before routing, excludes blocked orders, and saves the report with the optimization run. Use this as decision support; a dispatcher must review warnings before releasing a shipment.
- **External conditions:** optional providers add Google Maps traffic, OpenWeather destination conditions, and a configurable road-restriction endpoint. Unconfigured/failed providers show a warning rather than pretending that data was checked. The generic road-restriction endpoint must return JSON like `{"blocked": false, "reason": "No restrictions reported"}` and should be a provider you trust.
- **API keys:** set optional keys in `backend/.env` only. `GOOGLE_MAPS_API_KEY` enables traffic checks (make sure the Distance Matrix API/billing/quotas are enabled in Google Cloud); `OPENWEATHER_API_KEY` enables destination weather; `ROAD_RESTRICTIONS_API_URL` points to your own compatible endpoint; `GEMINI_API_KEY` enables AI explanations. `OSRM_URL` supplies road-distance and travel-time estimates but does **not** supply live traffic. Keys are never returned in `/api/snapshot` or sent as `VITE_*` values to the browser. `backend/.env.example` contains placeholders, not working credentials; obtain keys from the respective providers.
- **Drivers:** existing route assignments and manually assigned order rows appear in the driver workspace once `assigned_driver_id` matches a driver record. The `user_id` field on the Drivers page must be the worker's UUID from Supabase Authentication → Users (or their Driver Workspace's access-help panel). Set that user's profile role to `driver`; new sign-ups get this role by default. Successful optimization saves the chosen driver and vehicle to the associated Supabase orders.
- **Order foreign keys:** pick a product using the Inventory dropdown when creating an order. A product typed manually but absent from Inventory cannot be linked. Stock and the selected driver/vehicle are validated before save. If deleting an object that other rows use, reassign/update those linked rows first; the app uses a modal for relation conflicts and inline messages for form-specific validation.
- **Loading/feedback:** initial dashboard, auth and driver data use skeleton placeholders. Routine confirmations and recoverable errors use toast notifications, field/save errors are inline, and destructive linked-record errors use a modal.

### Optional provider keys

Add these lines in the **server-side** `backend/.env` and replace placeholders with actual credentials. Restart FastAPI after changing them:

```dotenv
GEMINI_API_KEY=your_actual_gemini_key
GOOGLE_MAPS_API_KEY=your_actual_google_maps_key
OPENWEATHER_API_KEY=your_actual_openweather_key
ROAD_RESTRICTIONS_API_URL=https://your-provider.example/check
```

Never paste private API keys into source code, screenshots, the frontend `.env`, or GitHub. If keys have already been shared publicly, revoke and rotate them at the provider before deployment.

## Deployment
* **Backend → Render**: use `render.yaml`; set `SUPABASE_URL`, `SUPABASE_PUBLIC_KEY`, `FRONTEND_ORIGIN` (your Vercel URL) in the Render dashboard.
* **Frontend → Vercel**: root directory `frontend`; set `VITE_API_URL` (your Render URL), `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLIC_KEY`. `vercel.json` handles `/signin` and `/signup` refreshes.

## Notes and limitations
* Managers use the operations dashboard; driver-role accounts use the separate Driver Workspace. Existing accounts are backfilled as managers when the migration runs, while fresh sign-ups receive the least-privilege driver role. Managers can link a driver record to the signed-in worker by saving that user's Supabase Auth UUID in the Drivers page.
* To make a newly registered account a manager, use the Supabase SQL Editor (trusted project administrator only): `update public.profiles set role = 'manager' where id = 'YOUR-SUPABASE-AUTH-USER-UUID';`. Do not add self-service role promotion to the public UI. Anyone can create an account unless you restrict sign-ups in Supabase Auth settings.
* OSRM uses the public demo server by default; use your own OSRM instance for production. If it is unreachable, routes fall back to straight-line × 1.3 estimates and say so in the result.
* Temperature rows marked `SIMULATED` are sample values until a real sensor source posts to `POST /api/monitoring/temperatures`.
* Shelf-life risk is a transparent heuristic, not a validated spoilage model.
