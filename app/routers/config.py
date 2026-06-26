from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.db import get_config, save_config

router = APIRouter(prefix="/config")
templates = Jinja2Templates(directory="app/templates")

@router.get("", response_class=HTMLResponse)
def config_get(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="config.html",
        context={"cfg": get_config()}
    )

@router.post("", response_class=HTMLResponse)
def config_post(
    request: Request,
    api_provider: str = Form(...),  # NOVO CAMPO DA API
    api_base: str = Form(...),
    deployment_id: str = Form(...),
    api_version: str = Form(...),
    api_key: str = Form(""),
    ca_cert: str = Form(""),
    maestro_api_token: str = Form(""),
    temperature: str = Form("0.2"),
    max_tokens: str = Form("")
):
    save_config({
        "api_provider": api_provider,
        "api_base": api_base,
        "deployment_id": deployment_id,
        "api_version": api_version,
        "api_key": api_key,
        "ca_cert": ca_cert,
        "maestro_api_token": maestro_api_token,
        "temperature": temperature,
        "max_tokens": max_tokens
    })
    return templates.TemplateResponse(
        request=request,
        name="config.html",
        context={"cfg": get_config(), "saved": True}
    )
