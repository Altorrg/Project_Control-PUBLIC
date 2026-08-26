# Project Control webalkalmazás

Ez a mappa a V9 asztali alkalmazástól elkülönített, Supabase-alapú webes változatot tartalmazza. A felhasználói felület magyar, a forrásfájlok neve magyar és ékezet nélküli.

## Könyvtárfelépítés

```text
webalkalmazas/
|-- adatbazis/                 Supabase/PostgreSQL telepítő SQL-ek
|-- eszkozok/                  telepítési SQL összeállító
|-- szerver/
|   |-- alkalmazas/
|   |   |-- adatmodellek/      bemeneti és kimeneti adatmodellek
|   |   |-- sablonok/          HTML alkalmazáskeret
|   |   |-- statikus/          magyar böngészős felület és megjelenés
|   |   |-- szolgaltatasok/    ütemezés, pénzügy, import és export
|   |   `-- vegpontok/         hitelesített API-végpontok modulonként
|   `-- tesztek/               automatikus üzleti és biztonsági tesztek
|-- LICENCEK.md
|-- UTMUTATO.md
`-- pyproject.toml
```

A Python által kötelezően elvárt `__init__.py`, valamint a csomagkezelő által elvárt `pyproject.toml` szabványos nevű maradt.

## Adatbázis telepítése

### Ajánlott: tiszta, egyfájlos telepítő

A Supabase SQL Editorban futtasd az alábbi fájl teljes tartalmát:

```text
adatbazis/000_tiszta_telepites.sql
```

Ez tartalmazza a teljes sémát, RLS-szabályokat, RPC-ket, törzsadatokat és a rendszerellenőrzést. Korábbi projektadatot nem tölt be. Egyetlen tranzakcióban fut, ezért hiba esetén nem marad félkész adatbázis.

### Meglévő séma javítása

Ha a séma már létezik, önállóan futtasd az alábbi idempotens javítást:

```text
adatbazis/004_rendszerellenorzes_es_javitas.sql
```

Ez pótolja a hiányzó Auth-profilokat, minden nem admin profilt `editor` szerepkörre állít, a két helyi adminprofilt aktiválja, és ellenőrzi a kritikus táblákat, jogosultságokat és projekt CRUD RPC-ket. Projektadatot nem módosít és nem hoz létre.

### Külön fájlonként

A Supabase SQL Editorban ebben a sorrendben kell futtatni:

1. `adatbazis/001_adatbazis_sema.sql`
2. `adatbazis/002_biztonsag_es_logika.sql`
3. `adatbazis/003_torzsadatok.sql`
4. `adatbazis/004_rendszerellenorzes_es_javitas.sql`
5. `adatbazis/005_globalis_szerkesztoi_hozzaferes.sql`
6. `adatbazis/006_teljesitmeny_indexek.sql`
7. `adatbazis/007_alvallalkozoi_dokumentumok.sql`
8. `adatbazis/008_matrix_datumok.sql`
9. `adatbazis/009_projekt_es_statusz_adatminoseg.sql`

A `008` migráció a régi, dátum nélküli kifizetésimátrix-oszlopokat dátumozott
szerződéses szakaszokhoz köti, majd kötelezővé teszi a szakaszdátumot. A `009`
migráció hozzáadja a lobby munkaszám- és felelős cég mezőit, valamint a régi
`Késik` ajánlatstátuszt `Elutasítva` értékre cseréli. Mindkét fájl idempotens,
ezért megszakítás után biztonságosan újrafuttatható.

Üres projektlistát is érvényes állapotnak tekint, mert minden új üzleti adatot
már a webalkalmazásban kell létrehozni.

## Felhasználói szerepkörök és belépés

A rendszer két belépési módot támogat:
1. **Vendég belépés (Sign in as guest)**: 1 kattintásos azonnali belépés normál felhasználói (`editor`) jogosultsággal. Látja az összes projektet és normál modult, projektet hozhat létre, valamint a projekt adatait szerkesztheti.
2. **Adminisztrátori belépés**: Supabase Auth felhasználónévvel és jelszóval. Teljes hozzáférést biztosít az Admin panelhez, felhasználók jogosultságaihoz, globális törzsadatokhoz és projekt törléséhez.

## Helyi futtatás

Első alkalommal telepítsd a függőségeket:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Ezután a webalkalmazás mappájából közvetlenül indítható:

```powershell
python inditas.py
```

Az indító a saját mappájához igazítja az importútvonalat, futáskor betölti az ugyanott található `.env` fájlt, ellenőrzi a kötelező beállításokat, elindítja a szervert, majd megnyitja a `http://127.0.0.1:8000` címet. Nem szükséges előtte `PYTHONPATH` értéket beállítani. Fejlesztői automatikus újratöltéshez használható a `python inditas.py --ujratoltes`; automatikus böngészőnyitás nélkül a `python inditas.py --nincs-bongeszo` parancs.

Az alkalmazás az alábbi környezeti változókat várja:

```text
SUPABASE_URL
SUPABASE_ANON_KEY        vagy SUPABASE_PUBLISHABLE_KEY / SUPABASE_PUBLIC_KEY
ALLOWED_ORIGINS          opcionális
COOKIE_SECURE            éles környezetben true
MAX_UPLOAD_BYTES         alapérték: 20971520
REQUEST_TIMEOUT_SECONDS  alapérték: 30
APP_ENV                  development vagy production
```

Az indítás egységesen a `python inditas.py` paranccsal történik. A környezeti fájl nincs a forráskódba kötve, tartalmát a fejlesztés nem olvassa és nem naplózza. A böngészőbe kizárólag az anon/publishable kulcs kerülhet; `service_role` kulcsot tilos kliensoldalon használni.

A public kulcs elfogadott változónevei: `SUPABASE_ANON_KEY`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_PUBLIC_KEY`, `SUPABASE_KEY`, továbbá a gyakori `NEXT_PUBLIC_...` és `VITE_...` anon/publishable változatok. A program az első nem üres értéket használja, magát a kulcsot soha nem írja ki a konzolra.

## Engedélyezési modul

Az engedélyezési rész tartalmazza a projektszintű dashboardot, súlyozott készültséget, szakági bontást, keresést és szűrést, ügylistát, dupla kattintásos szerkesztőablakot, korlátlan folyamatkört, körönként kötelező státuszt, közös partneradatbázist, partner létrehozási/módosítási/törlési kérelmeket, admin döntési felületet, csatolmányfeltöltést, Excel-importot és -exportot, PDF-riportot, auditot és értesítéseket.

Az Excel-kompatibilis export az első tíz kört lapítja oszlopokba, az adatbázisban nincs tízkörös korlát. Az XLSM-import nem futtat makrót vagy képletet; méret-, típus- és ZIP-szerkezeti ellenőrzést végez.

## További modulok

A webes felület a projektlétrehozást, a szakági napi adatrögzítést, a Gantt-fázisok létrehozását és szerkesztését, az alvállalkozói folyamatok kezelését, valamint a pénzügyi tranzakciók rögzítését is tartalmazza. Az írási műveletek csak megfelelő szerepkörrel jelennek meg, és a szerveroldali jogosultságellenőrzés minden esetben megismétli az ellenőrzést.

## Biztonság

- A hitelesítést a Supabase Auth végzi; a webalkalmazás HTTP-only munkamenetsütit használ.
- Minden írás CSRF-tokenhez kötött, a szerver minden végponton külön jogosultságot ellenőriz.
- A Supabase-kérések a bejelentkezett felhasználó JWT-jével futnak, ezért az RLS nem kerülhető meg szerverkulccsal.
- Projektadatot csak tagság, megfelelő szerepkör és műveleti engedély birtokában lehet elérni.
- A partner véglegesítése és törlése csak szerveroldali approval függvényen keresztül történhet.
- A belépést, importot, fájlfeltöltést és admin döntéseket alkalmazásszintű sebességkorlát védi; élesben ezt proxy- vagy platformszintű korláttal is ki kell egészíteni.
- A kritikus módosításokat audit trigger és célzott naplóbejegyzés rögzíti.
- A csatolmánytároló privát; az RLS az ügy projektjogosultságát és a tárolási útvonalat is ellenőrzi.
- Biztonsági fejlécek: CSP, frame tiltás, MIME sniffing tiltás, korlátozott böngészőjogosultságok.
- Éles környezetben kötelező a HTTPS, `COOKIE_SECURE=true`, szűk `ALLOWED_ORIGINS`, biztonságos secret-kezelés és rendszeres mentés.

Maradék üzemeltetési kockázat: a Supabase projekt-, Auth-, SMTP-, mentési és naplómegőrzési beállításai környezetfüggők. Élesítés előtt külön RLS-integrációs és jogosultsági próbát kell futtatni a valódi Supabase projekten.

## Teljesítmény és pénzügyi diagnosztika

Minden API-válasz `Server-Timing` fejlécben mutatja az alkalmazás és a Supabase
összesített idejét. Az `X-Supabase-Request-Count` fejléc az adott kéréshez
tartozó Supabase-hívások számát tartalmazza. A böngésző konzolja a lobby,
modulok és dokumentumpanel betöltési idejét, API-kérésszámát és a szerver
mérési adatait külön csoportokban írja ki.

A pénzügyi összesítő, a mátrixszinkron és a kifizetésmódosítás naplózza a
bemeneti összegeket, százalékos részeredményeket és kerekítési adatokat.
Érzékeny hitelesítési adatot ezek a naplók nem tartalmaznak. A diagnosztika a
meglévő számítási képleteket nem módosítja.

## Tesztelés

```powershell
$env:PYTHONPATH = "szerver"
python -m unittest discover -s szerver\tesztek -v
```

A PDF-teszt csak telepített ReportLab mellett fut. Az `.env` tartalmát a tesztek nem igénylik; az API-szerződést tesztbeállítással ellenőrzik.

## Telepítő újraépítése

A tiszta, egyfájlos telepítő újra összeállítható:

```powershell
python eszkozok\telepitesi_sql_osszeallitasa.py
```
