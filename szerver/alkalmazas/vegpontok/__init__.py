from fastapi import APIRouter

from . import (
    adminisztracio,
    ai_asszisztens,
    alvallalkozok,
    beallitasok,
    engedelyezes,
    ertesitesek,
    hitelesites,
    oldalak,
    penzugy,
    projektek,
    rendszerallapot,
    szakagak,
    utemterv,
)


api_router = APIRouter()
api_router.include_router(rendszerallapot.router)
api_router.include_router(hitelesites.router)
api_router.include_router(ai_asszisztens.router)
api_router.include_router(projektek.router)
api_router.include_router(szakagak.router)
api_router.include_router(utemterv.router)
api_router.include_router(alvallalkozok.router)
api_router.include_router(beallitasok.router)
api_router.include_router(penzugy.router)
api_router.include_router(engedelyezes.router)
api_router.include_router(ertesitesek.router)
api_router.include_router(adminisztracio.router)
