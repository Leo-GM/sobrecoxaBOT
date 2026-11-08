"""Fábrica da aplicação web FastAPI (Tarefa 11).

``create_app`` compõe a aplicação injetando um :class:`ContextoApp` em
``app.state.contexto`` e registrando os routers. Hoje registra o router de
**configuração** (tarefa 11.1); o router de **histórico** (tarefa 11.2) será
adicionado aqui da mesma forma, sem alterar o wiring existente.

O layout em fábrica + routers mantém a aplicação testável (basta passar uma
conexão SQLite em memória e uma chave Fernet efêmera) e extensível (novos
routers são incluídos com ``app.include_router``).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from notificacoes_ru.web.dependencias import ContextoApp, construir_contexto
from notificacoes_ru.web.routers import configuracao


def create_app(
    *,
    conexao: sqlite3.Connection | None = None,
    caminho_banco: Union[str, Path, None] = None,
    chave_fernet: bytes | None = None,
    caminho_chave: Union[str, Path, None] = None,
    contexto: ContextoApp | None = None,
) -> FastAPI:
    """Cria e configura a aplicação FastAPI do Marimbondos Informes RU.

    Pode receber um :class:`ContextoApp` pronto (ideal para testes que querem
    inspecionar diretamente os repositórios) ou as opções de construção
    (``conexao``/``caminho_banco`` e a fonte da chave Fernet), que são
    repassadas a :func:`construir_contexto`.
    """
    if contexto is None:
        contexto = construir_contexto(
            conexao=conexao,
            caminho_banco=caminho_banco,
            chave_fernet=chave_fernet,
            caminho_chave=caminho_chave,
        )

    app = FastAPI(title="Marimbondos Informes RU", version="0.1.0")
    app.state.contexto = contexto

    app.include_router(configuracao.router)

    @app.get("/", include_in_schema=False)
    def raiz() -> RedirectResponse:
        """Redireciona a raiz para a tela de configuração."""
        return RedirectResponse(url="/configuracao", status_code=303)

    return app
