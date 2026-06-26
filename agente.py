import uvicorn

if __name__ == "__main__":
    print("Iniciando o Agente Rotava...")

    # Este comando substitui o antigo 'uvicorn app.main:app --reload'
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8081,
        reload=False
    )
