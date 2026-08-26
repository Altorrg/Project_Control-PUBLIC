from __future__ import annotations

from pathlib import Path


SOURCE_FILES = (
    "001_adatbazis_sema.sql",
    "002_biztonsag_es_logika.sql",
    "003_torzsadatok.sql",
    "004_rendszerellenorzes_es_javitas.sql",
    "005_globalis_szerkesztoi_hozzaferes.sql",
    "006_teljesitmeny_indexek.sql",
    "007_alvallalkozoi_dokumentumok.sql",
    "008_matrix_datumok.sql",
    "009_projekt_es_statusz_adatminoseg.sql",
    "010_ajanlatkero_beallitasok.sql",
    "011_projekt_idempotencia_es_szerzodes_targya.sql",
    "012_utemterv_es_merfoldko_bovitesek.sql",
    "013_megbizhato_projektletrehozas.sql",
    "014_utemterv_jelkulcsok_es_kapcsolatok.sql",
    "016_ertesitesek_es_mai_teendok.sql",
    "017_szemelyes_tesztido.sql",
    "018_heti_feladat_ujraellenorzes.sql",
)

def without_transaction(text: str) -> str:
    lines = text.splitlines()
    return "\n".join(line for line in lines if line.strip().lower() not in {"begin;", "commit;"}).strip()


GUEST_AND_DEMO_SEED = """
-- ===== Vendég Mód és Jogosultságok Kiterjesztése (Public Demo) =====
do $guest_rls$
declare
    tbl record;
begin
    for tbl in (
        select table_name from information_schema.tables
        where table_schema = 'public' and table_type = 'BASE TABLE'
    ) loop
        execute format('alter table public.%I enable row level security;', tbl.table_name);
        execute format('grant all on public.%I to anon, authenticated;', tbl.table_name);
        execute format('drop policy if exists p_demo_all on public.%I;', tbl.table_name);
        execute format('create policy p_demo_all on public.%I for all to anon, authenticated using (true) with check (true);', tbl.table_name);
    end loop;
end;
$guest_rls$;

grant usage, select on all sequences in schema public to anon, authenticated;

-- Alapértelmezett vendég és admin profilok
insert into public.profiles(id, display_name, role, active) values
    ('00000000-0000-0000-0000-000000000000', 'Rendszeradminisztrátor', 'admin', true),
    ('00000000-0000-0000-0000-000000000001', 'Vendég Felhasználó', 'editor', true)
on conflict (id) do update set
    display_name = excluded.display_name,
    role = excluded.role,
    active = true;

-- Minta Projekt Létrehozása (Seed Demo Data)
do $seed_project$
declare
    sample_proj_id bigint;
    key_szerz bigint;
    key_eng bigint;
    key_jov bigint;
    key_kiv bigint;
    disc_eng bigint;
    task_utepites bigint;
    task_vizjogi bigint;
    task_kozmu bigint;
    partner_gov bigint;
    partner_katasztrofa bigint;
    partner_aram bigint;
begin
    if not exists (select 1 from public.projects where name = '1. sz. Főút 2x2 sávos kapacitásbővítés (Minta)') then
        insert into public.projects(
            name, work_number, responsible_company, customer, main_customer,
            contract_subject, contract_value, status, created_by
        ) values (
            '1. sz. Főút 2x2 sávos kapacitásbővítés (Minta)',
            'M-2026/01',
            'Minta Cégcsoport Zrt.',
            'Minta Megrendelő Zrt. (Építtető)',
            'Minta Beruházási Ügynökség',
            'Engedélyezési és kiviteli tervek készítése, hatósági eljárások lebonyolítása',
            185000000.00,
            'Aktív',
            '00000000-0000-0000-0000-000000000001'::uuid
        ) returning id into sample_proj_id;

        -- Tagság
        insert into public.project_memberships(profile_id, project_id, can_write)
        values
            ('00000000-0000-0000-0000-000000000000'::uuid, sample_proj_id, true),
            ('00000000-0000-0000-0000-000000000001'::uuid, sample_proj_id, true);

        -- Szakágak (name, code, sort_order, visible)
        insert into public.project_disciplines(project_id, name, code, sort_order, visible) values
            (sample_proj_id, 'Úttervezés', 'A', 1, true),
            (sample_proj_id, 'Híd- és Műtárgytervezés', 'B', 2, true),
            (sample_proj_id, 'Forgalomtechnika', 'C', 3, true),
            (sample_proj_id, 'Közműkiváltás', 'G', 4, true),
            (sample_proj_id, 'Környezetvédelem', 'E', 5, true);

        -- Pénzügyi Szakaszok (section_no, original_fee, modified_fee, fee_percent, copyright_percent, section_date, note)
        insert into public.project_contract_sections(project_id, section_no, original_fee, modified_fee, fee_percent, copyright_percent, section_date, note) values
            (sample_proj_id, 1, 45000000.00, 0, 90.0, 10.0, '2026-03-31', '1. Részszámla - Tervezési koncepció és alapadatok'),
            (sample_proj_id, 2, 55000000.00, 0, 90.0, 10.0, '2026-06-30', '2. Részszámla - Engedélyezési terv leadása'),
            (sample_proj_id, 3, 40000000.00, 0, 90.0, 10.0, '2026-09-30', '3. Részszámla - Jogerős engedélyek beszerzése'),
            (sample_proj_id, 4, 45000000.00, 0, 90.0, 10.0, '2026-12-15', '4. Végszámla - Kiviteli tervek jóváhagyása');

        -- Pénzügyi Mérföldkövek (sequence_no, name, short_name, official_name, phase_no, fee_percent, copyright_percent, planned_date, date_type)
        insert into public.project_milestones(project_id, sequence_no, name, short_name, official_name, phase_no, fee_percent, copyright_percent, planned_date, date_type) values
            (sample_proj_id, 1, 'M1 - Koncepcióterv', 'M1', 'Koncepcióterv megrendelői jóváhagyása', 1, 90.0, 10.0, '2026-03-31', 'Fix dátum'),
            (sample_proj_id, 2, 'M2 - Engedélyezési terv', 'M2', 'Engedélyezési tervdokumentáció készrejelentése', 2, 90.0, 10.0, '2026-06-30', 'Fix dátum'),
            (sample_proj_id, 3, 'M3 - Jogerős engedélyek', 'M3', 'Építési és környezetvédelmi engedélyek jogerőre emelkedése', 3, 90.0, 10.0, '2026-09-30', 'Fix dátum'),
            (sample_proj_id, 4, 'M4 - Kiviteli tervek', 'M4', 'Teljes kiviteli tervcsomag átadása', 4, 90.0, 10.0, '2026-12-15', 'Fix dátum');

        -- Jelkulcsok kiválasztása
        select id into key_szerz from public.schedule_keys where code = 'SZERZ KÖT' limit 1;
        select id into key_eng from public.schedule_keys where code = 'ENG TERV' limit 1;
        select id into key_jov from public.schedule_keys where code = 'JÓV ENG' limit 1;
        select id into key_kiv from public.schedule_keys where code = 'KIV TERV' limit 1;

        -- Ütemterv sorok (position, phase_name, phase_code, schedule_key_id, financial_phase_no, days, delay, manual_start, calc_type)
        insert into public.schedule_rows(
            project_id, position, phase_name, phase_code, schedule_key_id, financial_phase_no, days, delay, manual_start, calc_type
        ) values
            (sample_proj_id, 10, 'Tervezési szerződés megkötése és adatszolgáltatás', 'SZERZ KÖT', key_szerz, 1, 30, 0, '2026-01-15', 'Naptári nap'),
            (sample_proj_id, 20, 'Engedélyezési tervek kidolgozása', 'ENG TERV', key_eng, 2, 120, 0, '2026-02-16', 'Naptári nap'),
            (sample_proj_id, 30, 'Hatósági engedélyezési eljárások és jogerő', 'JÓV ENG', key_jov, 3, 105, 0, '2026-06-16', 'Naptári nap'),
            (sample_proj_id, 40, 'Kiviteli tervek készítése és záradékolás', 'KIV TERV', key_kiv, 4, 75, 0, '2026-10-01', 'Naptári nap');

        -- Alvállalkozói munkafolyamatok (display_order, company_name, discipline, code, finance_class, preliminary_estimate, offer_status, contract_total)
        insert into public.subcontractor_workflows(
            project_id, display_order, company_name, discipline, code, finance_class, preliminary_estimate, offer_status, contract_total
        ) values
            (sample_proj_id, 1, 'Minta Híd- és Műtárgytervező Zrt.', 'Műtárgyak', 'B1-Bx', '2. fázis', '18500000', 'Kiküldve', '18000000'),
            (sample_proj_id, 2, 'Minta Geotechnikai Szakértő Kft.', 'Geotechnikai szakvélemény', 'Hsz', '1. fázis', '6500000', 'Kiküldve', '6200000'),
            (sample_proj_id, 3, 'Minta Forgalomtechnikai Iroda Kft.', 'Forgalomtechnika', 'C1-C4', '2. fázis', '4200000', 'Kiküldésre vár', '');

        -- Engedélyezési szakágak (eng_disciplines)
        insert into public.eng_disciplines(project_id, name, sort_order, active) values
            (sample_proj_id, 'Útépítés', 10, true),
            (sample_proj_id, 'Műtárgyépítés', 20, true),
            (sample_proj_id, 'Közművek', 30, true)
        on conflict (project_id, name) do update set active = true;

        -- Engedélyezési partnerek
        insert into public.eng_partners(name, contact_person, status) values
            ('Kormányhivatal Közlekedési Főosztály', 'Kovács Péter', 'approved'),
            ('Katasztrófavédelmi Igazgatóság', 'Nagy Anna', 'approved'),
            ('Áramhálózati Elosztó Kft.', 'Kovács Péter', 'approved')
        on conflict do nothing;

        select id into disc_eng from public.eng_disciplines where project_id = sample_proj_id and name = 'Útépítés' limit 1;
        select id into partner_gov from public.eng_partners where name = 'Kormányhivatal Közlekedési Főosztály' limit 1;
        select id into partner_katasztrofa from public.eng_partners where name = 'Katasztrófavédelmi Igazgatóság' limit 1;
        select id into partner_aram from public.eng_partners where name = 'Áramhálózati Elosztó Kft.' limit 1;
        select id into task_utepites from public.eng_tasks where name = 'útépítési engedély' limit 1;
        select id into task_vizjogi from public.eng_tasks where name = 'vízjogi létesítési engedély' limit 1;
        select id into task_kozmu from public.eng_tasks where name = 'közműnyilatkozat' limit 1;

        if task_utepites is not null and partner_gov is not null and disc_eng is not null then
            insert into public.eng_assignments(project_id, discipline_id, task_id, partner_id, status_code, responsible, due_date)
            values (sample_proj_id, disc_eng, task_utepites, partner_gov, '○', 'Kovács Péter', '2026-07-15')
            on conflict do nothing;
        end if;

        -- Napi teendő minta
        insert into public.notification_tasks(profile_id, project_id, title, details, due_date, priority) values
            ('00000000-0000-0000-0000-000000000001'::uuid, sample_proj_id, 'Közműegyeztetési jegyzőkönyv ellenőrzése', 'Átnézni az áramhálózati elosztó válaszát a kiváltásokról.', current_date, 2),
            ('00000000-0000-0000-0000-000000000001'::uuid, sample_proj_id, 'Geotechnikai részjelentés jóváhagyása', 'A talajmechanikai fúrások eredményeinek áttekintése.', (current_date + 1)::date, 3);
    end if;
end;
$seed_project$;
"""


def build_installer(database_directory: Path) -> str:
    sections = [
        "-- Project Control - tiszta Supabase telepito",
        "-- Sem projektadatot, sem korabbi alkalmazasadatot nem tartalmaz.",
        "-- Egyben futtathato SQL a Supabase SQL Editorban.",
        "begin;",
    ]
    for file_name in SOURCE_FILES:
        source = database_directory / file_name
        if not source.is_file():
            raise FileNotFoundError(f"Hianyzik a telepitesi forras: {source}")
        sections.extend(("", f"-- ===== {file_name} =====", without_transaction(source.read_text(encoding="utf-8"))))
    sections.extend(("", GUEST_AND_DEMO_SEED.strip(), "", "commit;", ""))
    return "\n".join(sections)


def main() -> int:
    database_directory = Path(__file__).resolve().parents[1] / "adatbazis"
    output = database_directory / "000_tiszta_telepites.sql"
    output.write_text(build_installer(database_directory), encoding="utf-8", newline="\n")
    print(f"Elkeszult: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
