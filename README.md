# Project Control Web - Nyilvános Demó Minta

Modern, mérnöki és vállalati projektirányítási, Gantt ütemtervezési, alvállalkozói szerződéskezelési és engedélyezési webalkalmazás.

## Online kipróbálás

**[Project Control – nyilvános demó megnyitása](https://project-control-public.onrender.com/)**

A belépőoldalon válaszd a **„Belépés vendégként (1 kattintás)”** gombot. Regisztráció nélkül megtekinthetők és kipróbálhatók a mintaadatokra épülő funkciók.

Ez egy közös, szerkeszthető bemutatókörnyezet, nem vállalati éles rendszer. Kizárólag kitalált mintaadatokat használj benne; valós ügyféladatot, személyes adatot vagy üzleti dokumentumot ne tölts fel. Az ingyenes hosztolás inaktivitás után elalszik, ezért az első betöltés egy percig vagy tovább is tarthat; az adatbázis időnként külön újraindítást igényelhet. Az opcionális AI-szolgáltatás elérhetősége külön beállítástól függ.

AI támogatásával fejlesztett projekt Sebestény Máté infrastruktúra-tervezési és projektkoordinációs tapasztalatára építve. További referenciák: [CadAgent MCP bemutató](https://github.com/Altorrg/cadagent-mcp-showcase) · [Smart Redactor](https://github.com/Altorrg/smart_redactor).

Ez a repozitórium egy **teljes értékű, nyílt forrású minta és bemutató verzió**, amely azonnal kipróbálható helyileg vagy tetszőleges felhőszolgáltatón (pl. Render, Railway, Fly.io) a csatolt tiszta Supabase adatbázis-telepítővel.

---

## Főbb Funkciók

- **Gantt Ütemterv és Mérföldkövek**: Interaktív, számított fázis- és mérföldkő-idővonalak, kritikus út, eltolások és Excel exportálás (`.xlsx`).
- **Alvállalkozói Munkafolyamatok**: Ajánlatkérések, szerződések, szerződésmódosítások és jóváhagyási lépések nyilvántartása.
- **Automatikus Dokumentumgenerálás**: Egykattintásos szerkeszthető Word (`.docx`) és nyomtatóbarát PDF (`.pdf`) árajánlatkérő kiadás.
- **Engedélyezési Mátrix és Napi Teendők**: Hatósági eljárások, közmű- és tulajdonosi hozzájárulások határidő-követése, státuszkezelés és mai teendőlista.
- **Szakági Munkaidő és Napló**: Erőforrás- és munkaórák rögzítése, éves napidíjak és költségbecslés.
- **Pénzügyi és Cash-Flow Nyilvántartás**: Részszámlák, fizetési ütemezés és mérföldkő-alapú pénzügyi elszámolások.
- **Beépített AI Asszisztens**: Választható OpenAI, Anthropic Claude, Google Gemini, Groq vagy OpenRouter integráció mérnöki elemzésekhez.

---

## Kettős Belépési Rendszer (Guest & Admin)

A nyilvános demó céljaira az alkalmazás kétféle belépési módot támogat:

1. **Vendég Belépés (1 kattintás)**:
   - A bejelentkező képernyőn a **„Belépés vendégként (1 kattintás)”** gomb azonnali hozzáférést ad normál szerkesztői (`editor`) jogosultsággal.
   - Nincs szükség regisztrációra vagy jelszóra.
   - Lehetővé teszi projektek létrehozását, szerkesztését, ütemtervek és dokumentumok kipróbálását.

2. **Adminisztrátori Belépés**:
   - Supabase Auth e-mail cím és jelszó párossal történő belépés.
   - Teljes adminisztrációs felület: felhasználói szerepkörök kezelése, globális törzsadatok és jelkulcsok szerkesztése, projektek végleges törlése.

---

## Architektúra és Technológiai Stack

- **Backend**: Python 3.11+ / 3.13, **FastAPI**, **Starlette**, **Pydantic v2**, **ReportLab** (PDF), **python-docx** (DOCX), **openpyxl** (XLSX).
- **Frontend**: Natív, ultra-gyors modern Vanilla JavaScript (ES2022) és reszponzív CSS3.
  - **Zero npm, Zero CDN**: Nincsenek külső npm csomagok vagy CDN-függőségek; az alkalmazás offline vagy zárt vállalati hálózatban is azonnal fut.
- **Adatbázis**: **PostgreSQL** / **Supabase** Row Level Security (RLS) szabályokkal, tárolt eljárásokkal (RPC) és audit naplózással.

---

## Gyors Telepítés és Indítás

### 1. Adatbázis létrehozása (Supabase)

1. Hozz létre egy ingyenes projektet a [Supabase.com](https://supabase.com) oldalon.
2. Nyisd meg a Supabase vezérlőpultján az **SQL Editor** menüpontot.
3. Másold be és futtasd le az [`adatbazis/000_tiszta_telepites.sql`](adatbazis/000_tiszta_telepites.sql) fájl tartalmát.
   - *Ez egyetlen lépésben létrehozza a táblákat, biztonsági szabályokat, tárolt eljárásokat és betölti az induló minta projektet.*

### 2. Környezeti változók beállítása

Másold le a `.env.example` fájlt `.env` néven a gyökérkönyvtárba:

```bash
cp .env.example .env
```

Töltsd ki a Supabase kapcsolati adataidat:

```text
SUPABASE_URL=https://<a-te-projekted>.supabase.co
SUPABASE_KEY=<a-te-anon-vagy-publishable-kulcsod>
APP_ENV=development
```

*(Opcionális)* Ha használni szeretnéd az AI asszisztenst, add meg a szolgáltató adatait (pl. `AI_PROVIDER=openai`, `AI_API_KEY=...`).

### 3. Függőségek telepítése és alkalmazás indítása

Ajánlott virtuális környezet használata:

```powershell
# Virtuális környezet létrehozása és aktiválása (Windows PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Csomagok telepítése
pip install -e .

# Webalkalmazás elindítása
python inditas.py
```

Linux / macOS környezetben:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python3 inditas.py
```

Az indító script automatikusan ellenőrzi a környezetet és megnyitja az alkalmazást a böngésződben: **`http://127.0.0.1:8000`**.

---

## Tesztek futtatása

A teljes tesztcsomag (140 automatizált egység- és integrációs teszt) futtatása:

```bash
pytest szerver/tesztek -o pythonpath=szerver
```

---

## Projekt Struktúra

```text
├── adatbazis/
│   ├── 000_tiszta_telepites.sql       # Teljes, egybefüggő Supabase adatbázis-telepítő
│   └── 001_... - 018_...sql           # Moduláris migrációs fájlok
├── szerver/
│   ├── alkalmazas/
│   │   ├── adatmodellek/              # Pydantic v2 validációs modellek
│   │   ├── eroforrasok/               # Betűtípusok és képi minták
│   │   ├── sablonok/                  # HTML5 Jinja sablonok
│   │   ├── statikus/                  # alkalmazas.js, megjelenes.css
│   │   ├── szolgaltatasok/            # PDF, DOCX, XLSX export és AI motor
│   │   └── vegpontok/                 # FastAPI REST API útvonalak
│   └── tesztek/                       # Pytest tesztcsomag (140 teszt)
├── eszkozok/                          # Telepítő- és segédszkriptek
├── inditas.py                         # Helyi alkalmazásindító
├── pyproject.toml                     # Python projektkonfiguráció
├── .env.example                       # Környezeti minta konfiguráció
└── README.md                          # Dokumentáció
```

---

## Licenc és Biztonság

- A forráskód nyílt forrású MIT / BSD licencű komponensekre épül. Részletek: [`LICENCEK.md`](LICENCEK.md).
- A repozitórium **nem tartalmaz valós személyes adatokat, védett cégneveket vagy éles API kulcsokat**.
