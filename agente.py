import uvicorn

if __name__ == "__main__":
    print("Iniciando o Agente Rotava...")

    # Este comando substitui o antigo 'uvicorn app.main:app --reload'
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False
    )