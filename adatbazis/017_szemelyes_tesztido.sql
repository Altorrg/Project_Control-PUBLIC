begin;

-- Az adminisztratori tesztido szemelyes: mas felhasznalo datumara nem hat.
-- A regi globalis kulcsokat nem toroljuk, csak a datumfuggveny nem hasznalja oket.
create or replace function public.app_today()
returns date
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    current_profile_id uuid := auth.uid();
    offset_days integer := 0;
    force_first boolean := false;
    result_date date := current_date;
begin
    if current_profile_id is null or not exists (
        select 1
        from public.profiles profile
        where profile.id = current_profile_id
          and profile.active
          and profile.role = 'admin'
    ) then
        return current_date;
    end if;

    select coalesce((setting_value #>> '{}')::integer, 0)
      into offset_days
      from public.app_settings
     where setting_key = 'time_offset_days:' || current_profile_id::text;

    select coalesce((setting_value #>> '{}')::boolean, false)
      into force_first
      from public.app_settings
     where setting_key = 'force_first_of_month:' || current_profile_id::text;

    result_date := current_date + coalesce(offset_days, 0);
    if coalesce(force_first, false) then
        result_date := date_trunc('month', result_date)::date;
    end if;
    return result_date;
exception when others then
    return current_date;
end;
$$;

revoke all on function public.app_today() from public, anon;
grant execute on function public.app_today() to authenticated;

notify pgrst, 'reload schema';

commit;

select public.app_today() as current_profile_application_date;
