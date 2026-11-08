"""Composição e injeção de dependências da camada web (Tarefa 11).

Centraliza a construção dos objetos de núcleo usados pelos endpoints —
``ConfigRepoSQLite``, ``CofreCredenciaisFernet`` e o ``HistoricoRepo`` — a
partir de um contêiner de aplicação (:class:`ContextoApp`). A fábrica
``create_app`` injeta um único ``ContextoApp`` em ``app.state`` e os routers
obtêm os repositórios por meio das funções ``obter_*`` abaixo (padrão
``Depends`` do FastAPI).

Manter o wiring isolado aqui permite que os routers de configuração (11.1) e,
mais tarde, de histórico (11.2) compartilhem a mesma fonte de conexão/segredo
sem duplicar lógica de construção, e facilita a substituição por um banco em
memória nos testes.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from fastapi import Request

from notificacoes_ru.persistencia.config_repo import ConfigRepoSQLite
from notificacoes_ru.persistencia.esquema import (
    CAMINHO_BANCO_PADRAO,
    inicializar_banco,
)
from notificacoes_ru.persistencia.historico import HistoricoSQLite
from notificacoes_ru.seguranca.cofre import (
    CofreCredenciaisFernet,
    carregar_ou_criar_chave,
    gerar_chave,
)


def abrir_conexao_web(
    caminho_banco: Union[str, Path, None] = None,
) -> sqlite3.Connection:
    """Abre uma conexão SQLite adequada à aplicação web.

    O FastAPI executa os endpoints síncronos em um *threadpool*, então a mesma
    conexão pode ser acessada por threads diferentes ao longo da vida da
    aplicação. Por isso usamos ``check_same_thread=False``. A aplicação é de
    usuário único e baixa concorrência (um único processo/instância, conforme o
    design), o que torna o compartilhamento da conexão seguro na prática.

    A ``row_factory`` é :class:`sqlite3.Row` (acesso por nome de coluna) e as
    chaves estrangeiras ficam ativas (necessário para ``ON DELETE CASCADE``),
    espelhando ``persistencia.esquema.conectar``.
    """
    alvo = str(caminho_banco or CAMINHO_BANCO_PADRAO)
    con = sqlite3.connect(alvo, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON;")
    return con


@dataclass
class ContextoApp:
    """Contêiner de dependências vivas da aplicação web.

    Agrupa a conexão SQLite já inicializada e os repositórios/serviços de
    núcleo construídos sobre ela. É criado uma única vez por aplicação (na
    fábrica ``create_app``) e guardado em ``app.state.contexto``.
    """

    conexao: sqlite3.Connection
    config_repo: ConfigRepoSQLite
    cofre: CofreCredenciaisFernet
    historico_repo: HistoricoSQLite


def construir_contexto(
    *,
    conexao: sqlite3.Connection | None = None,
    caminho_banco: Union[str, Path, None] = None,
    chave_fernet: bytes | None = None,
    caminho_chave: Union[str, Path, None] = None,
) -> ContextoApp:
    """Constrói o :class:`ContextoApp` a partir das opções fornecidas.

    Pode receber uma ``conexao`` já aberta (ideal para testes com SQLite em
    memória) ou um ``caminho_banco`` de arquivo. A chave Fernet do cofre pode
    ser passada diretamente (``chave_fernet``), carregada/criada de um arquivo
    (``caminho_chave``) ou, como último recurso em testes, gerada em memória.
    """
    if conexao is not None:
        # Conexão fornecida (ex.: testes com SQLite em memória) — o chamador é
        # responsável por abri-la com ``check_same_thread=False`` se for
        # compartilhada entre threads (ver ``abrir_conexao_web``).
        con = inicializar_banco(conexao=conexao)
    else:
        con = abrir_conexao_web(caminho_banco)
        inicializar_banco(conexao=con)

    if chave_fernet is not None:
        chave = chave_fernet
    elif caminho_chave is not None:
        chave = carregar_ou_criar_chave(caminho_chave)
    else:
        # Sem fonte de chave persistente: gera uma chave efêmera. Em produção
        # deve-se fornecer ``caminho_chave`` para preservar a credencial entre
        # reinícios; em testes a chave efêmera é suficiente.
        chave = gerar_chave()

    return ContextoApp(
        conexao=con,
        config_repo=ConfigRepoSQLite(con),
        cofre=CofreCredenciaisFernet(con, chave),
        historico_repo=HistoricoSQLite(con),
    )


# ---------------------------------------------------------------------------
# Provedores de dependência (FastAPI ``Depends``)
# ---------------------------------------------------------------------------


def obter_contexto(request: Request) -> ContextoApp:
    """Recupera o :class:`ContextoApp` guardado em ``app.state``."""
    return request.app.state.contexto


def obter_config_repo(request: Request) -> ConfigRepoSQLite:
    """Dependência: o ``ConfigRepoSQLite`` da aplicação."""
    return obter_contexto(request).config_repo


def obter_cofre(request: Request) -> CofreCredenciaisFernet:
    """Dependência: o ``CofreCredenciaisFernet`` da aplicação."""
    return obter_contexto(request).cofre


def obter_historico_repo(request: Request) -> HistoricoSQLite:
    """Dependência: o ``HistoricoSQLite`` da aplicação."""
    return obter_contexto(request).historico_repo
