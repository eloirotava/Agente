from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.core import processar_orquestracao

router = APIRouter(prefix="/chat")
templates = Jinja2Templates(directory="app/templates")

@router.get("", response_class=HTMLResponse)
def chat_get(request: Request):
    return templates.TemplateResponse(request=request, name="chat.html", context={})

@router.post("", response_class=HTMLResponse)
async def chat_post(request: Request, message: str = Form(...)):
    # A MÁGICA: O Chat não tem mais cérebro. Ele consome o serviço do Maestro!
    resultado = await processar_orquestracao(mensagem=message, origem="Chat")

    return templates.TemplateResponse(
        request=request,
        name="chat.html",
        context={
            "message": message,
            "answer": resultado["resposta_final"],
            "logs": resultado["logs"]
        }
    )
