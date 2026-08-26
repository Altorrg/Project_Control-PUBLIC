-- Project Control Web - required master data
-- Futtatási sorrend: 002_biztonsag_es_logika.sql után.

begin;

insert into public.permissions(permission_key, description) values
    ('admin_panel', 'Admin kozpont hasznalata'),
    ('projects_all', 'Osszes projekt megtekintese'),
    ('project_create', 'Projekt letrehozasa'),
    ('project_write', 'Projektadatok modositasa'),
    ('project_delete', 'Projekt archivalasa'),
    ('arbevetel', 'Cegvezetoi arbevetel modul'),
    ('module_szakagak', 'Szakag napi adatok modul'),
    ('module_utemterv', 'Gantt utemterv modul'),
    ('module_alvallalkozo', 'Alvallalkozo es szerzodes modul'),
    ('module_penzugy', 'Penzugyi vezetoi modul'),
    ('module_beallitasok', 'Projekt beallitasok modul'),
    ('module_engedelyek', 'Engedelyek es hozzajarulasok modul'),
    ('discipline_write', 'Szakagi napi adatok szerkesztese'),
    ('schedule_write', 'Utemterv szerkesztese'),
    ('subcontractor_write', 'Alvallalkozoi folyamat szerkesztese'),
    ('finance_write', 'Penzugyi adatok szerkesztese'),
    ('eng_write', 'Engedelyezesi ugyek es partnerjavaslatok kezelese'),
    ('eng_admin', 'Engedelyezesi admin approval'),
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
on conflict (role, permission_key) do update set allowed = excluded.allowed;

delete from public.role_permissions where role <> 'editor';

insert into public.app_settings(setting_key, setting_value) values
    ('time_offset_days', '0'::jsonb),
    ('force_first_of_month', 'false'::jsonb),
    ('engagement_warning_days', '14'::jsonb),
    ('subcontractor_stall_days', '10'::jsonb),
    ('engagement_stall_days', '25'::jsonb)
on conflict (setting_key) do nothing;

insert into public.customer_options(name) values
    ('Minta Megrendelő Zrt. (Építtető)'),
    ('Minta Beruházási Ügynökség'),
    ('Minta Város Önkormányzata'),
    ('Minta Fővállalkozó Zrt.')
on conflict (name) do nothing;

insert into public.project_status_options(name) values
    ('Generáltervező'), ('Konzorciumi vezető'), ('Konzorciumi tag'), ('Alvállalkozó')
on conflict (name) do nothing;

insert into public.eng_statuses(code, name, color, icon, priority, is_closed, warn) values
    ('✓', 'Megvan / elintézve', '#2ecc71', '✓', 10, true, false),
    ('○', 'Folyamatban / elindítva', '#3498db', '○', 20, false, false),
    ('!', 'Nincs elindítva', '#f39c12', '!', 30, false, true),
    ('⮾', 'Elutasítva', '#e74c3c', '⮾', 40, false, true),
    ('H', 'Hiánypótlás kell', '#9b59b6', 'H', 50, false, true),
    ('X', 'Lejárt', '#c0392b', 'X', 60, false, true),
    ('II', 'Szüneteltetés', '#7f8c8d', 'II', 70, false, false)
on conflict (code) do update set
    name = excluded.name, color = excluded.color, icon = excluded.icon,
    priority = excluded.priority, is_closed = excluded.is_closed, warn = excluded.warn;

insert into public.eng_tasks(name, weight, active, sort_order, description) values
    ('üzemeltetői hozzájárulás', 1, true, 10, 'Üzemeltetői hozzájárulás beszerzése'),
    ('közműnyilatkozat', 1, true, 20, 'Közműnyilatkozat beszerzése'),
    ('vasútüzemeltetői hozzájárulás', 1, true, 30, ''),
    ('járatüzemeltetői hozzájárulás', 1, true, 40, ''),
    ('közútkezelői hozzájárulás', 1, true, 50, ''),
    ('tulajdonosi hozzájárulás', 1, true, 60, ''),
    ('lehatárolási terv elfogadása', 1, true, 70, ''),
    ('vízfolyáskezelői hozzájárulás', 1, true, 80, ''),
    ('vagyonkezelői hozzájárulás', 1, true, 90, ''),
    ('befogadói nyilatkozat', 1, true, 100, ''),
    ('VOR - objektumazonosítás', 1, true, 110, ''),
    ('szakkérdés vizsgálata', 1, true, 120, ''),
    ('szakhatósági hozzájárulás', 1, true, 130, ''),
    ('építtetői nyilatkozat', 1, true, 140, ''),
    ('vízjogi létesítési engedély', 1, true, 150, ''),
    ('útépítési engedély', 1, true, 160, ''),
    ('hídépítési engedély', 1, true, 170, '')
on conflict (name) do update set
    weight = excluded.weight, active = excluded.active,
    sort_order = excluded.sort_order, description = excluded.description;

insert into public.eng_intervention_types(name) values
    ('Kiküldés'), ('Beérkezés'), ('Hiánypótlás'), ('Szüneteltetés'), ('Elutasítás'), ('Javítás')
on conflict (name) do update set active = true;

insert into public.subcontractor_categories(display_order, name, code) values
    (1, 'Animáció', 'Ani'), (2, 'Anyagnyerő és depóniahelyek', 'O2'),
    (3, 'Burkolattechnológia', 'Bt'), (4, 'Behajlásmérés, feltárás', 'Bm'),
    (5, 'Döntés-előkészítő', 'DT'), (6, 'Előzetes vizsgálat', 'EVD'),
    (7, 'Érintésvédelem', 'G8'), (8, 'Értékelemzés', 'VE'),
    (9, 'Forgalmi vizsgálat', 'C0'), (10, 'Forgalomtechnika', 'C1-C4'),
    (11, 'Forgalomtechnika (Ideiglenes)', 'C9'), (12, 'Forgalomtechnika (Rávezető)', 'C8'),
    (13, 'Geodézia', 'P0'), (14, 'Geotechnikai feltárás', 'Hf'),
    (15, 'Geotechnikai szakvélemény', 'Hsz'), (16, 'Geotechnikai terv', 'H1'),
    (17, 'Helybiztosítási terv', 'HT'), (18, 'Hírközlés', 'G1'),
    (19, 'Humuszgazdálkodás', 'O1'), (20, 'Kis/középfeszültség', 'G2'),
    (21, 'Környezetvédelem', 'E1-Ex'), (22, 'Közmű genplan', 'G0'),
    (23, 'Közmű tanulmány', 'G'), (24, 'Látványterv', 'Lt'),
    (25, 'Magasépítés-Építészet', 'JE'), (26, 'Műtárgyak', 'B1-Bx'),
    (27, 'Nagyfeszültség', 'G3'), (28, 'Növénytelepítés', 'F1-Fx'),
    (29, 'Rekultiváció', 'RE'), (30, 'Szénhidrogén vezetékek', 'G5'),
    (31, 'Talajtani szakvélemény', 'Ts'), (32, 'Útépítés', 'A1-Ax'),
    (33, 'Üzemi hírközlés', 'G9'), (34, 'Vasútépítés', 'N1-Nx'),
    (35, 'Vasúti biztosító', 'G7'), (36, 'Vízellátás, csatornázás', 'G4'),
    (37, 'Vízépítés', 'D1-Dx'), (38, 'Vasút - Felsővezeték', 'P11'),
    (39, 'Tervellenőrzés', 'ELL')
on conflict (name, code) do update set display_order = excluded.display_order;

insert into public.subcontractors(display_order, name, category, code) values
    (1, 'Minta Útépítő Tervező Kft.', 'Útépítés', 'A1-Ax'),
    (2, 'Minta Híd- és Műtárgytervező Zrt.', 'Műtárgyak', 'B1-Bx'),
    (3, 'Minta Forgalomtechnikai Iroda Kft.', 'Forgalomtechnika', 'C1-C4'),
    (4, 'Minta Környezetvédelmi Mérnökiroda', 'Környezetvédelem', 'E1-Ex'),
    (5, 'Minta Hírközlési és Közmű Kft.', 'Hírközlés', 'G1'),
    (6, 'Minta Geotechnikai Szakértő Kft.', 'Geotechnikai szakvélemény', 'Hsz')
on conflict (name, category, code) do update set display_order = excluded.display_order, active = true;

commit;
