"""Camada web / UI (FastAPI + Jinja2).

A fábrica :func:`create_app` compõe a aplicação (injeção do ``ContextoApp`` e
registro dos routers). Os routers de configuração (tarefa 11.1) e de histórico
(tarefa 11.2) já estão ligados. Esta camada delega toda a regra de negócio ao
núcleo.
"""

from notificacoes_ru.web.app import create_app
from notificacoes_ru.web.dependencias import ContextoApp, construir_contexto

__all__ = ["create_app", "ContextoApp", "construir_contexto"]
