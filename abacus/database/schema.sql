-- FrostRoute AI — additive Supabase schema / migration.
-- Run the WHOLE file in Supabase Dashboard -> SQL Editor. Existing operational data is not dropped.

create table if not exists depots (
  id text primary key,
  name text not null,
  address text default '',
  lat double precision not null check (lat between -90 and 90),
  lng double precision not null check (lng between -180 and 180),
  operating_start text default '06:00',
  operating_end text default '20:00',
  storage_capacity numeric not null default 1000 check (storage_capacity > 0),
  status text default 'Active',
  created_at timestamptz default now()
);

create table if not exists inventory (
  id text primary key,
  name text not null,
  category text default 'General',
  depot_id text not null references depots(id),
  quantity numeric not null check (quantity >= 0),
  unit text default 'units',
  expiry_date date not null,
  min_temp double precision not null default 2,
  max_temp double precision not null default 8,
  priority text default 'Medium',
  created_at timestamptz default now()
);

create table if not exists vehicles (
  id text primary key,
  name text not null,
  capacity numeric not null check (capacity > 0),
  unit text default 'units',
  refrigerated boolean default true,
  min_temp double precision default 1,
  max_temp double precision default 8,
  lat double precision not null,
  lng double precision not null,
  cost_per_km numeric default 18,
  max_route_hours numeric default 8,
  status text default 'Available',
  created_at timestamptz default now()
);

-- App role mapping is separate from Supabase Auth. Never let users self-promote their role.
create table if not exists profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  role text not null default 'driver' check (role in ('manager','driver')),
  created_at timestamptz default now()
);

create table if not exists drivers (
  id text primary key,
  user_id uuid unique references auth.users(id) on delete set null,
  name text not null,
  phone text default '',
  license_number text default '',
  vehicle_id text references vehicles(id) on delete set null,
  status text default 'Available',
  created_at timestamptz default now()
);

create table if not exists orders (
  id text primary key,
  customer text not null,
  address text default '',
  lat double precision not null,
  lng double precision not null,
  product_id text not null references inventory(id),
  quantity numeric not null check (quantity > 0),
  window_start text default '08:00',
  window_end text default '17:00',
  priority text default 'Medium',
  status text default 'Pending',
  budget numeric check (budget is null or budget >= 0),
  assigned_driver_id text references drivers(id) on delete set null,
  assigned_vehicle_id text references vehicles(id) on delete set null,
  driver_note text default '',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists optimization_runs (
  id text primary key,
  created_at timestamptz default now(),
  status text not null,
  engine text,
  message text,
  summary jsonb default '{}'::jsonb,
  routes jsonb default '[]'::jsonb,
  unserved_orders jsonb default '[]'::jsonb,
  reasons jsonb default '[]'::jsonb,
  decision_report jsonb default '{}'::jsonb
);

create table if not exists temperature_readings (
  id text primary key,
  product_id text,
  product text,
  location text,
  temperature numeric not null,
  min_temp numeric,
  max_temp numeric,
  "timestamp" timestamptz default now(),
  mode text default 'SIMULATED'
);

create table if not exists alerts (
  id text primary key,
  type text not null,
  severity text not null,
  entity text,
  reason text,
  status text default 'Open',
  created_at timestamptz default now()
);

-- Add new columns to installations created from an older version of the schema.
alter table depots add column if not exists storage_capacity numeric not null default 1000;
alter table orders add column if not exists budget numeric;
alter table orders add column if not exists assigned_driver_id text;
alter table orders add column if not exists assigned_vehicle_id text;
alter table orders add column if not exists driver_note text default '';
alter table orders add column if not exists updated_at timestamptz default now();
alter table optimization_runs add column if not exists decision_report jsonb default '{}'::jsonb;

do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'orders_assigned_driver_id_fkey') then
    alter table orders add constraint orders_assigned_driver_id_fkey foreign key (assigned_driver_id) references drivers(id) on delete set null;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'orders_assigned_vehicle_id_fkey') then
    alter table orders add constraint orders_assigned_vehicle_id_fkey foreign key (assigned_vehicle_id) references vehicles(id) on delete set null;
  end if;
end $$;

create index if not exists idx_orders_status on orders(status);
create index if not exists idx_orders_driver on orders(assigned_driver_id);
create index if not exists idx_inventory_expiry on inventory(expiry_date);
create index if not exists idx_alerts_status on alerts(status);
create index if not exists idx_drivers_user_id on drivers(user_id);

-- Existing accounts retain manager access so the current project keeps working after migration.
insert into profiles (id, role)
select id, 'manager' from auth.users
on conflict (id) do nothing;

create or replace function public.frostroute_new_profile()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, role) values (new.id, 'driver') on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists frostroute_auth_user_created on auth.users;
create trigger frostroute_auth_user_created
after insert on auth.users for each row execute procedure public.frostroute_new_profile();

create or replace function public.frostroute_has_role(required_role text)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.profiles p where p.id = auth.uid() and p.role = required_role);
$$;
revoke all on function public.frostroute_has_role(text) from public;
grant execute on function public.frostroute_has_role(text) to authenticated;

-- Profiles are readable only by the matching account; only trusted SQL/admin actions set roles.
alter table profiles enable row level security;
drop policy if exists "profile owner read" on profiles;
create policy "profile owner read" on profiles for select to authenticated using (id = auth.uid());

-- Manager operations. Drivers can only read their own driver record and the orders assigned to them.
do $$
declare t text;
begin
  foreach t in array array['depots','inventory','vehicles','drivers','orders','optimization_runs','temperature_readings','alerts']
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists "authenticated full access" on public.%I', t);
    execute format('drop policy if exists "managers full access" on public.%I', t);
    execute format('create policy "managers full access" on public.%I for all to authenticated using (public.frostroute_has_role(''manager'')) with check (public.frostroute_has_role(''manager''))', t);
  end loop;
end $$;

drop policy if exists "driver reads own driver record" on drivers;
create policy "driver reads own driver record" on drivers for select to authenticated using (user_id = auth.uid());

drop policy if exists "drivers read assigned orders" on orders;
create policy "drivers read assigned orders" on orders for select to authenticated using (
  exists (select 1 from drivers d where d.id = orders.assigned_driver_id and d.user_id = auth.uid())
);
drop policy if exists "drivers update assigned order status" on orders;
create policy "drivers update assigned order status" on orders for update to authenticated using (
  exists (select 1 from drivers d where d.id = orders.assigned_driver_id and d.user_id = auth.uid())
) with check (
  exists (select 1 from drivers d where d.id = orders.assigned_driver_id and d.user_id = auth.uid())
);

-- Keep the browser's Supabase realtime refresh working for manager-facing tables.
do $$
declare t text;
begin
  foreach t in array array['depots','inventory','vehicles','drivers','orders','optimization_runs','temperature_readings','alerts']
  loop
    begin
      execute format('alter publication supabase_realtime add table public.%I', t);
    exception when duplicate_object then null;
    end;
  end loop;
end $$;
