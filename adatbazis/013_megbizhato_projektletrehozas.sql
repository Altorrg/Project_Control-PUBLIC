-- 013 - Megbizhato, idempotens projektletrehozas.
-- A create_project RPC minden sikeres valasz elott biztositja a letrehozo
-- project_memberships rekordjat. A muvelet egyetlen PostgreSQL tranzakcio.

begin;

create or replace function public.create_project(payload jsonb)
returns public.projects
language plpgsql
security definer
set search_path = ''
as $$
declare
    result public.projects;
    current_profile_id uuid;
    request_key text;
    request_fingerprint text;
    project_name text;
    project_work_number text;
    project_responsible_company text;
    project_contract_value numeric(18,2);
    project_contract_subject text;
    project_customer text;
    project_main_customer text;
    project_status text;
    canonical_payload jsonb;
    contract_value_text text;
begin
    if not public.has_permission('project_create') then
        raise exception 'permission denied';
    end if;

    current_profile_id := auth.uid();
    if current_profile_id is null then
        raise exception 'permission denied';
    end if;

    request_key := nullif(trim(payload ->> 'idempotency_key'), '');
    project_name := nullif(trim(payload ->> 'name'), '');
    if project_name is null then
        raise exception using
            errcode = '22023',
            message = 'A projekt neve kotelezo.';
    end if;

    project_work_number := coalesce(payload ->> 'work_number', '');
    project_responsible_company := coalesce(payload ->> 'responsible_company', '');
    contract_value_text := nullif(trim(payload ->> 'contract_value'), '');
    if contract_value_text is not null and contract_value_text !~ '^[0-9]+(\.[0-9]{1,2})?$' then
        raise exception using
            errcode = '22023',
            message = 'A szerzodeses ertek nem ervenyes szam.';
    end if;
    project_contract_value := contract_value_text::numeric;
    project_contract_subject := coalesce(payload ->> 'contract_subject', '');
    project_customer := coalesce(payload ->> 'customer', '');
    project_main_customer := coalesce(payload ->> 'main_customer', '');
    project_status := coalesce(nullif(payload ->> 'status', ''), 'Aktív');

    canonical_payload := jsonb_build_object(
        'name', project_name,
        'work_number', project_work_number,
        'responsible_company', project_responsible_company,
        'contract_value', project_contract_value,
        'contract_subject', project_contract_subject,
        'customer', project_customer,
        'main_customer', project_main_customer,
        'status', project_status
    );
    -- Ket MD5 erteket fuzunk ossze a mar letezo 64 karakteres oszlophoz.
    -- Ez idempotencia-azonosito, nem jelszo vagy biztonsagi titok; igy a
    -- projektletrehozas nem fugg a pgcrypto kiterjesztestol.
    request_fingerprint := md5(canonical_payload::text)
        || md5('project-control:' || canonical_payload::text);

    if request_key is not null then
        select p.*
        into result
        from public.projects p
        where p.created_by = current_profile_id
          and p.creation_idempotency_key = request_key;

        if result.id is not null
           and result.creation_request_fingerprint <> request_fingerprint then
            raise exception using
                errcode = '23505',
                message = 'Az idempotenciakulcs mar egy masik projektkereshez tartozik.';
        end if;
    end if;

    if result.id is null then
        insert into public.projects(
            name,
            work_number,
            responsible_company,
            contract_value,
            contract_subject,
            customer,
            main_customer,
            status,
            created_by,
            creation_idempotency_key,
            creation_request_fingerprint
        )
        values (
            project_name,
            project_work_number,
            project_responsible_company,
            project_contract_value,
            project_contract_subject,
            project_customer,
            project_main_customer,
            project_status,
            current_profile_id,
            request_key,
            case when request_key is null then null else request_fingerprint end
        )
        on conflict (created_by, creation_idempotency_key)
            where creation_idempotency_key is not null
            do nothing
        returning * into result;

        if result.id is null then
            select p.*
            into result
            from public.projects p
            where p.created_by = current_profile_id
              and p.creation_idempotency_key = request_key;

            if result.id is null then
                raise exception 'A projekt letrehozasa nem sikerult.';
            end if;
            if result.creation_request_fingerprint <> request_fingerprint then
                raise exception using
                    errcode = '23505',
                    message = 'Az idempotenciakulcs mar egy masik projektkereshez tartozik.';
            end if;
        end if;
    end if;

    -- Ujraprobalkozasnal is helyreallitja a hianyzo letrehozoi kapcsolatot.
    -- Hiba eseten a friss projektbeszuras ugyanebben a tranzakcioban visszagordul.
    insert into public.project_memberships(profile_id, project_id, can_write)
    values (current_profile_id, result.id, true)
    on conflict (profile_id, project_id) do nothing;

    return result;
end;
$$;

commit;
