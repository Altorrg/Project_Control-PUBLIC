# Project Control Render deploy

A GitHub repository gyokere legyen a `github_V2` mappa tartalma. Valodi `.env`
fajl, helyi adatbazis, SQL telepito es gyorsitotar nem kerulhet a repositoryba.

## Javasolt telepites

A repository gyokereben levo `render.yaml` tartalmazza a teljes Render
konfiguraciot. Uj szolgaltatasnal Render Blueprintkent importalhato.

Mar letezo Render Web Service eseten a Settings oldalon ezek legyenek:

- Runtime: `Python 3`
- Root Directory: ures
- Build Command: `pip install -r requirements.txt`
- Start Command: `python -m uvicorn alkalmazas.webszerver:app --app-dir szerver --host 0.0.0.0 --port $PORT`
- Health Check Path: `/api/health`

## Kornyezeti valtozok

A Render feluleten kell megadni a `.env.example` alapjan. A `SUPABASE_KEY`
csak publikus/anon vagy publishable kulcs lehet; service role kulcsot az
alkalmazas nem fogad el.

Az `ALLOWED_ORIGINS` erteke az eles HTTPS-cim legyen. Eles kornyezetben az `APP_ENV=production` es a `COOKIE_SECURE=true` kotelezo.

Az Oracle AI-bekotes nem titkos ertekeit a `render.yaml` tartalmazza. Az
`AI_API_KEY` erteket a Render Environment feluleten kell megadni; ez soha nem
kerulhet GitHubra. Meglevo Web Service eseten ellenorizd, hogy az alabbi valtozok
tenylegesen jelen vannak: `AI_PROVIDER`, `AI_API_BASE_URL`, `AI_API_KEY`,
`AI_MODEL`, `AI_REQUEST_TIMEOUT_SECONDS`. Az Oracle oldali `8000/tcp` portnak a
Render kifele meno kapcsolatai felol is elerhetonek kell lennie.

A `.python-version` a helyben tesztelt Python 3.13 agat valasztja ki a Renderen.

Az adatbazis-sema nem resze ennek a deploy-csomagnak. A mar elo Supabase
adatbazist a Render kornyezeti valtozoi kapcsoljak az alkalmazashoz.

## Teljesitmeny

Meglevo Supabase adatbazisnal egyszer futtasd a forrascsomag
`adatbazis/006_teljesitmeny_indexek.sql` fajljat a Supabase SQL Editorban.
Az indexek adatot nem irnak at, es a szkript tobbszor is biztonsagosan
futtathato.

Az alvallalkozoi ajanlatkerok dokumentumtarahoz futtasd a
`adatbazis/007_alvallalkozoi_dokumentumok.sql` fajlt is. Ez csak a
verziozott dokumentumpiszkozatok uj tablat, RLS-szabalyait es audit triggeret
hozza letre; meglevő projekt- vagy folyamattartalmat nem ir at.

Ezutan ebben a sorrendben futtasd:

1. `adatbazis/008_matrix_datumok.sql`
2. `adatbazis/009_projekt_es_statusz_adatminoseg.sql`
3. `adatbazis/010_ajanlatkero_beallitasok.sql`
4. `adatbazis/011_projekt_idempotencia_es_szerzodes_targya.sql`
5. `adatbazis/012_utemterv_es_merfoldko_bovitesek.sql`
6. `adatbazis/013_megbizhato_projektletrehozas.sql`
7. `adatbazis/014_utemterv_jelkulcsok_es_kapcsolatok.sql`

Az elso a regi matrixoszlopokat datumozott szakaszokhoz koti, a masodik a
projektlista uj metaadatait es az `Elutasitva` ajanlatstatuszt vezeti be.
A harmadik az ajanlatkero kozos projektalapadatait es a ceges kapcsolattartok
projektlistajat hozza letre. A 011-013 a projektletrehozas, valamint az
utemterv es merfoldko kesobbi bovitesek idempotens migracioi. A 013 biztositja,
hogy idempotens ujraprobalkozasnal is letrejojjon a letrehozo projekttagsaga.
A 014 egyetlen, idempotens migracioban hozza letre a globalis utemtervi
jelkulcs-torzset, betolti az ellenorzott `docs/input/Utemterv_jelkulcsok.xlsx`
30 jelkulcsat, majd biztonsagosan kapcsolja az utemtervi sorokhoz, penzugyi
fazisokhoz es alvallalkozoi workflow-khoz. A korabbi 014-016 kulon fajlokat
ne futtasd; a `Kuka` konyvtar csak archivum.
Ezek az SQL-fajlok
szandekosan nem kerulnek a GitHub deploy-csomagba; a forrascsomagbol, a
Supabase SQL Editorban kell futtatni oket.

A Render es a Supabase regioja lehetoseg szerint legyen azonos vagy kozeli.
A valaszok `Server-Timing` fejlece az alkalmazas es a Supabase osszesitett
feldolgozasi idejet, az `X-Supabase-Request-Count` fejlec pedig az upstream
keresek szamat mutatja. Az egy masodpercnel lassabb API-keresek a Render
naplojaba is bekerulnek. Az ingyenes Render csomag alvas utani elso inditasa
ettol meg lassabb lehet; az ismetlodo lassulas a meresi adatokkal kulon
vizsgalhato.
