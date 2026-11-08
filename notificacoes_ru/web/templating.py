"""Configuração compartilhada de templates Jinja2 (Tarefa 11).

Expõe uma única instância de :class:`fastapi.templating.Jinja2Templates`
apontando para ``notificacoes_ru/web/templates``. Centralizar aqui evita que
cada router recrie o ambiente Jinja2 e garante que os routers de configuração
(11.1) e de histórico (11.2) renderizem com o mesmo conjunto de templates e
filtros.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

# Diretório físico dos templates, relativo a este arquivo (robusto ao cwd).
DIRETORIO_TEMPLATES = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=str(DIRETORIO_TEMPLATES))
