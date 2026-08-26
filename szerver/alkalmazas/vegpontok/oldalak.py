from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


router = APIRouter(include_in_schema=False)
sablonok = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "sablonok")


@router.get("/", response_class=HTMLResponse)
async def application_shell(request: Request):
    return sablonok.TemplateResponse(request=request, name="kezdolap.html", context={"app_name": "Project Control"})
