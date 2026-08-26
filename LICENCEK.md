# Licencjegyzék

Állapot: 2026-08-10. Ez fejlesztői nyilvántartás, nem jogi tanács.

Az ellenőrzés a `requirements-render.txt`, a helyi `pyproject.toml`, a Python
csomagmetaadatok és a csomagolt erőforrások alapján készült. A Render-csomag
verziótartományokat rögzít; kiadáskor a ténylegesen feloldott verziókat is
ellenőrizni kell.

## Közvetlen összetevők

| Összetevő | Licenc / szolgáltatási forma | Fizetős? | Megjegyzés |
|---|---|---:|---|
| Python | PSF License | Nem | Kereskedelmi használatra is alkalmazható. |
| FastAPI | MIT | Nem | Webes API keretrendszer. |
| Uvicorn | BSD-3-Clause | Nem | ASGI kiszolgáló. |
| HTTPX | BSD-3-Clause | Nem | Supabase HTTP-kapcsolat. |
| Jinja2 | BSD-3-Clause | Nem | HTML sablonkezelés. |
| openpyxl | MIT | Nem | XLSX/XLSM adatimport és export. |
| python-multipart | Apache-2.0 | Nem | Fájlfeltöltés és űrlapadatok. |
| python-docx | MIT | Nem | Szerkeszthető DOCX dokumentumexport. |
| ReportLab Open Source | BSD | Nem | PDF-export. Nem a kereskedelmi ReportLab PLUS változat. |
| python-dotenv | BSD-3-Clause | Nem | Csak a helyi `inditas.py` `.env`-betöltéséhez kell; a Render futási csomag nem igényli. |
| Supabase Cloud | Hosztolt szolgáltatás | Feltételes | Free csomag elérhető, éles terhelésnél Pro vagy többlethasználati díj lehet. |
| Render Cloud | Hosztolt szolgáltatás | Feltételes | Free web service elérhető tesztelésre; éles használathoz vagy limitek felett fizetős csomag lehet szükséges. |
| PostgreSQL | PostgreSQL License | Nem | A Supabase adatbázismotorja. |

## Közvetett Python-függőségek

| Összetevő | Licenc |
|---|---|
| Starlette | BSD-3-Clause |
| Pydantic, pydantic-core | MIT |
| annotated-doc, annotated-types, typing-inspection | MIT |
| typing-extensions | PSF-2.0 |
| AnyIO | MIT |
| idna | BSD-3-Clause |
| sniffio | MIT vagy Apache-2.0 |
| httpcore | BSD-3-Clause |
| h11 | MIT |
| certifi | MPL-2.0 |
| MarkupSafe | BSD-3-Clause |
| click | BSD-3-Clause |
| et_xmlfile | MIT |
| Pillow | HPND / MIT-CMU megengedő licenc |
| lxml | BSD-3-Clause |
| charset-normalizer | MIT |
| colorama | BSD-3-Clause (platformfüggő kiegészítő) |
| DejaVu Sans betűkészlet | DejaVu Fonts License (Bitstream Vera alapú) |

A PDF-export a projektbe csomagolt `DejaVuSans.ttf` és `DejaVuSans-Bold.ttf`
betűkészleteket használja a teljes magyar karakterkészlethez. A licenc teljes
szövege a `szerver/alkalmazas/eroforrasok/LICENSE_DEJAVU.txt` fájlban található.
Az összetevő ingyenes; külön kereskedelmi licencet nem igényel.

Az ajánlatkérő fejlécgrafikája testreszabható mintadokumentum-fejléc.
A nyílt forrású változat dinamikus vagy generikus fejlécképet használ.

A böngészős felület nem tölt be külső JavaScript-, CSS-, ikon- vagy
betűkészlet-csomagot CDN-ről. Nincs npm-függőség vagy külön frontend licenc.

A bejelentkezési oldal nagy `U` grafikai eleme kizárólag saját HTML/CSS megoldás.
Nem tartalmaz hivatalos vállalati logófájlt, külső képet vagy licencelt arculati
assetet.

## Licenckockázati összegzés

A deploy közvetlen függőségei megengedő MIT, BSD vagy Apache-2.0 licenceket
használnak. A jelenlegi függőségi körben nincs GPL, AGPL, kötelező kereskedelmi
licenc vagy olyan copyleft feltétel, amely az alkalmazás saját forráskódjának
közzétételét követelné meg.

A közvetett `certifi` MPL-2.0 licencű. Ez fájlszintű kötelezettség, nem terjed ki
az alkalmazás saját kódjára; a csomag licenc- és szerzői jogi közleményét
terjesztéskor meg kell őrizni. A DejaVu Sans betűkészlet szintén terjeszthető,
de a saját licencszövegét és névhasználati feltételeit meg kell őrizni.

## Költségjelzés

A forráskódban nincs kötelező fizetős könyvtár. A Supabase és a Render Free
csomagja használható tesztelésre, de az éles terhelés, tárhely, adatforgalom,
üzemidő vagy további szolgáltatások fizetős csomagot igényelhetnek. Az aktuális
költségeket telepítés előtt újra ellenőrizni kell: [Supabase díjszabás](https://supabase.com/pricing),
[Supabase számlázási útmutató](https://supabase.com/docs/guides/platform/billing-on-supabase),
[Render díjszabás](https://render.com/pricing), [Render Free korlátok](https://render.com/docs/free).

A ReportLab nyílt változata BSD-licencű és ingyenes. A ReportLab PLUS külön kereskedelmi termék, ezt a projekt nem használja: [ReportLab licencismertető](https://docs.reportlab.com/developerfaqs/).

## Terjesztési szabály

Telepítő vagy konténer kiadása előtt az adott verziók tényleges csomagmetaadataiból újra kell generálni a harmadik fél értesítéseit. A licencszövegeket és szerzői jogi közleményeket a terjesztési csomagban meg kell őrizni. Supabase előfizetés, egyedi domain, mentés, megfelelőségi funkció és támogatás külön szolgáltatási költséget jelenthet.
