from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from threading import Timer
import webbrowser


ALKALMAZAS_GYOKER = Path(__file__).resolve().parent
SZERVER_MAPPA = ALKALMAZAS_GYOKER / "szerver"


def elokeszit_import_utvonalat() -> None:
    szerver_utvonal = str(SZERVER_MAPPA)
    if szerver_utvonal not in sys.path:
        sys.path.insert(0, szerver_utvonal)


def argumentumok() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A Project Control webalkalmazás helyi indítása.")
    parser.add_argument("--host", default="127.0.0.1", help="Figyelési cím. Alapérték: 127.0.0.1")
    parser.add_argument("--port", type=int, default=8000, help="Helyi port. Alapérték: 8000")
    parser.add_argument("--ujratoltes", action="store_true", help="Automatikus újratöltés fejlesztés közben.")
    parser.add_argument("--nincs-bongeszo", action="store_true", help="Ne nyissa meg automatikusan a böngészőt.")
    return parser


def betolt_kornyezetet() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise RuntimeError(
            "Hiányzik a python-dotenv csomag. Futtasd a webalkalmazás mappájában: "
            "python -m pip install -e ."
        ) from exc

    # A fájlt kizárólag futáskor tölti be; a titkos értékeket nem írja ki és nem naplózza.
    # Helyi indításkor mindig az alkalmazás melletti konfiguráció legyen mérvadó.
    load_dotenv(ALKALMAZAS_GYOKER / ".env", encoding="utf-8-sig", override=True)


def ellenoriz_beallitasokat() -> None:
    elokeszit_import_utvonalat()
    from alkalmazas.beallitasok import ConfigurationError, Settings

    try:
        Settings.from_environment()
    except ConfigurationError as exc:
        raise RuntimeError(
            f"{exc} Hozd létre vagy egészítsd ki a webalkalmazás mappájában lévő .env fájlt."
        ) from exc


def megnyit_bongeszot(url: str) -> None:
    Timer(1.2, lambda: webbrowser.open(url)).start()


def main(argv: list[str] | None = None) -> int:
    args = argumentumok().parse_args(argv)
    if not 1 <= args.port <= 65535:
        print("Hiba: a portnak 1 és 65535 közé kell esnie.", file=sys.stderr)
        return 2

    try:
        betolt_kornyezetet()
        ellenoriz_beallitasokat()
        import uvicorn
    except (ImportError, RuntimeError) as exc:
        print(f"Indítási hiba: {exc}", file=sys.stderr)
        return 1

    url_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
    url = f"http://{url_host}:{args.port}"
    print("Project Control webalkalmazás")
    print(f"Helyi cím: {url}")
    print("Leállítás: Ctrl+C")

    if not args.nincs_bongeszo:
        megnyit_bongeszot(url)

    os.chdir(ALKALMAZAS_GYOKER)
    uvicorn.run(
        "alkalmazas.webszerver:app",
        host=args.host,
        port=args.port,
        reload=args.ujratoltes,
        reload_dirs=[str(SZERVER_MAPPA)] if args.ujratoltes else None,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
