from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.db import get_config, save_config, get_config_versions, delete_config_version

router = APIRouter(prefix="/config")
templates = Jinja2Templates(directory="app/templates")

@router.get("", response_class=HTMLResponse)
def config_get(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="config.html",
        context={"cfg": get_config(), "versions": get_config_versions()}
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
    max_tokens: str = Form(""),
    llm_provider_mode: str = Form("builtin"),
    llm_provider_code: str = Form(""),
    change_note: str = Form("")
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
        "max_tokens": max_tokens,
        "llm_provider_mode": llm_provider_mode,
        "llm_provider_code": llm_provider_code
    }, change_note=change_note)
    return templates.TemplateResponse(
        request=request,
        name="config.html",
        context={"cfg": get_config(), "versions": get_config_versions(), "saved": True}
    )


@router.post("/versions/delete/{version_id}")
def config_version_delete(version_id: int):
    delete_config_version(version_id)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/config?deleted_version=1", status_code=303)
