"""Camada de persistência (SQLite).

Expõe o esquema SQLite e a inicialização idempotente do banco (tarefa 3.1).
As implementações concretas de ``nucleo.HistoricoRepo`` e ``nucleo.ConfigRepo``
serão adicionadas nas tarefas 3.2 e 3.7.
"""

from notificacoes_ru.persistencia.config_repo import (
    ConfigRepoSQLite,
    ErroValidacaoConfig,
    LIMITE_PRATOS,
    TAMANHO_MAX_PRATO,
    TAMANHO_MIN_PRATO,
)
from notificacoes_ru.persistencia.esquema import (
    CAMINHO_BANCO_PADRAO,
    VERSAO_ESQUEMA,
    conectar,
    inicializar_banco,
)
from notificacoes_ru.persistencia.historico import (
    MESES_RETENCAO,
    HistoricoSQLite,
)

__all__ = [
    "CAMINHO_BANCO_PADRAO",
    "VERSAO_ESQUEMA",
    "conectar",
    "inicializar_banco",
    "ConfigRepoSQLite",
    "ErroValidacaoConfig",
    "LIMITE_PRATOS",
    "TAMANHO_MAX_PRATO",
    "TAMANHO_MIN_PRATO",
    "HistoricoSQLite",
    "MESES_RETENCAO",
]
