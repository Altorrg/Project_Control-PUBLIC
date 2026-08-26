-- Project Control - globalis szerkesztoi projekthozzaferes javitasa
-- Meglevo projektadatot nem torol es nem modosit.

begin;

-- Csak ket alkalmazasi szerep marad: admin es editor.
alter table public.profiles drop constraint if exists profiles_role_check;

update public.profiles
set role = 'editor', updated_at = now()
where role <> 'admin';

alter table public.profiles alter column role set default 'editor';
alter table public.profiles
    add constraint profiles_role_check check (role in ('admin', 'editor'));

-- Minden uj Supabase Auth felhasznalo aktiv szerkesztoi profilt kap.
create or replace function public.handle_new_auth_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    insert into public.profiles(id, display_name, role, active)
    values (
        new.id,
        coalesce(nullif(new.raw_user_meta_data ->> 'display_name', ''), new.email, 'Felhasznalo'),
        'editor',
        true
    )
    on conflict (id) do update
    set
        display_name = case
            when trim(public.profiles.display_name) = '' then excluded.display_name
            else public.profiles.display_name
        end,
        role = case when public.profiles.role = 'admin' then 'admin' else 'editor' end,
        updated_at = now();
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_auth_user();

insert into public.permissions(permission_key, description) values
    ('projects_all', 'Osszes projekt megtekintese'),
    ('project_create', 'Projekt letrehozasa'),
    ('project_write', 'Projektadatok modositasa'),
    ('project_delete', 'Projekt archivalasa'),
    ('admin_panel', 'Admin kozpont hasznalata'),
    ('arbevetel', 'Ceges arbevetel es cash-flow'),
    ('module_szakagak', 'Szakag napi adatok modul'),
    ('module_utemterv', 'Gantt utemterv modul'),
    ('module_alvallalkozo', 'Alvallalkozo es szerzodes modul'),
    ('module_penzugy', 'Penzugyi modul'),
    ('module_beallitasok', 'Projektbeallitasok modul'),
    ('module_engedelyek', 'Engedelyezesi modul'),
    ('discipline_write', 'Szakagi adatok szerkesztese'),
    ('schedule_write', 'Utemterv szerkesztese'),
    ('subcontractor_write', 'Alvallalkozoi adatok szerkesztese'),
    ('finance_write', 'Penzugyi adatok szerkesztese'),
    ('eng_write', 'Engedelyezesi adatok szerkesztese'),
    ('eng_admin', 'Engedelyezesi admin jovahagyas'),
    ('master_data_admin', 'Globalis torzsadatok kezelese')
on conflict (permission_key) do update set description = excluded.description;

insert into public.role_permissions(role, permission_key, allowed)
select 'editor', permission_key, true
from unnest(array[
    'projects_all', 'project_create', 'project_write', 'arbevetel',
    'module_szakagak', 'module_utemterv', 'module_alvallalkozo',
    'module_penzugy', 'module_beallitasok', 'module_engedelyek',
    'discipline_write', 'schedule_write', 'subcontractor_write',
    'finance_write', 'eng_write'
]) permission_list(permission_key)
on conflict (role, permission_key) do update set allowed = true;

delete from public.role_permissions
where role not in ('admin', 'editor');

create or replace function public.current_role()
returns text
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce((
        select profile.role
        from public.profiles profile
        where profile.id = auth.uid() and profile.active
    ), 'anonymous');
$$;

create or replace function public.has_permission(permission_key text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select case
        when auth.uid() is null then false
        when public.current_role() = 'admin' then true
        else coalesce((
            select role_permission.allowed
            from public.role_permissions role_permission
            where role_permission.role = public.current_role()
              and role_permission.permission_key = $1
        ), false)
    end;
$$;

-- A projekt-hozzaferes szandekosan nem fugg project_memberships rekordtol.
-- Minden aktiv admin es editor minden projektet lat; az irasi jogot az
-- endpointok kulon, muveletszintu permission ellenorzese korlatozza.
create or replace function public.can_access_project(
    target_project_id bigint,
    write_access boolean default false
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select auth.uid() is not null
       and exists (
            select 1
            from public.profiles profile
            where profile.id = auth.uid()
              and profile.active
              and profile.role in ('admin', 'editor')
       );
$$;

alter table public.projects enable row level security;

drop policy if exists projects_read on public.projects;
create policy projects_read on public.projects for select to authenticated
using (not is_deleted and public.can_access_project(id, false));

drop policy if exists projects_insert on public.projects;
create policy projects_insert on public.projects for insert to authenticated
with check (public.has_permission('project_create'));

drop policy if exists projects_update on public.projects;
create policy projects_update on public.projects for update to authenticated
using (public.can_access_project(id, true) and public.has_permission('project_write'))
with check (public.can_access_project(id, true) and public.has_permission('project_write'));

revoke all on function public.current_role() from public, anon;
revoke all on function public.has_permission(text) from public, anon;
revoke all on function public.can_access_project(bigint, boolean) from public, anon;
grant execute on function public.current_role() to authenticated;
grant execute on function public.has_permission(text) to authenticated;
grant execute on function public.can_access_project(bigint, boolean) to authenticated;

do $verification$
begin
    if exists (
        select 1 from public.profiles where role not in ('admin', 'editor')
    ) then
        raise exception 'Ervenytelen profil szerepkor maradt az adatbazisban.';
    end if;

    if not exists (
        select 1 from public.role_permissions
        where role = 'editor' and permission_key = 'projects_all' and allowed
    ) then
        raise exception 'Hianyzik az editor projects_all jogosultsaga.';
    end if;

    if position(
        'project_memberships' in pg_get_functiondef(
            'public.can_access_project(bigint,boolean)'::regprocedure
        )
    ) > 0 then
        raise exception 'A projekthozzaferes meg mindig tagsaghoz kotott.';
    end if;
end;
$verification$;

commit;

select
    role,
    active,
    count(*) as profilok
from public.profiles
group by role, active
order by role, active desc;

