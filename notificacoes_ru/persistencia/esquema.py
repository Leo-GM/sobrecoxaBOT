"""Esquema SQLite e inicialização do banco (Tarefa 3.1).

Define o esquema relacional que dá suporte às entidades do design (seção *Data
Models*) e uma rotina de inicialização **idempotente** — todas as tabelas são
criadas com ``CREATE TABLE IF NOT EXISTS``, de modo que chamar
:func:`inicializar_banco` repetidamente sobre a mesma conexão é seguro e não
destrói dados existentes.

Mapeamento entidade → tabela:

* ``Cardapio_Semanal``   → ``cardapios`` (restaurante, data_coleta, semana_ano)
* ``ItemCardapio``       → ``itens_cardapio`` (dia_semana, refeicao, texto_item)
* ``Prato_Monitorado``   → ``pratos_monitorados`` (nome_original, nome_normalizado)
* ``Ocorrencia``         → ``ocorrencias`` (dia_semana, refeicao, restaurante, data_coleta)
* ``Configuracao``       → ``configuracao`` (linha única: canal, contato, horário, fuso)
* ``Credencial_Unicamp`` → ``credencial`` (linha única: login, senha_criptografada)

A camada de repositórios (tarefas 3.2 e 3.7) usa este esquema; aqui tratamos
apenas da forma do dado e da criação/migração das tabelas.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union

# Caminho padrão do arquivo de banco quando nenhum é informado.
CAMINHO_BANCO_PADRAO = Path("notificacoes_ru.db")

# Versão do esquema. Incrementar quando houver migrações estruturais; usado pelo
# PRAGMA user_version para permitir migrações idempotentes no futuro.
VERSAO_ESQUEMA = 1

# ---------------------------------------------------------------------------
# Definições DDL (idempotentes)
# ---------------------------------------------------------------------------

# Cada ``Cardapio_Semanal`` é único por (restaurante, data_coleta). Guarda a
# semana do ano para consultas e retenção (Req 1.3, 5.1, 5.7).
_DDL_CARDAPIOS = """
CREATE TABLE IF NOT EXISTS cardapios (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    restaurante  TEXT NOT NULL,
    data_coleta  TEXT NOT NULL,
    semana_ano   INTEGER NOT NULL,
    UNIQUE (restaurante, data_coleta)
);
"""

# Itens de um cardápio indexados por (dia_semana, refeicao). ON DELETE CASCADE
# garante que remover um cardápio remove seus itens.
_DDL_ITENS_CARDAPIO = """
CREATE TABLE IF NOT EXISTS itens_cardapio (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cardapio_id INTEGER NOT NULL,
    dia_semana  TEXT NOT NULL,
    refeicao    TEXT NOT NULL,
    texto_item  TEXT NOT NULL,
    FOREIGN KEY (cardapio_id) REFERENCES cardapios (id) ON DELETE CASCADE
);
"""

# Pratos monitorados; ``nome_normalizado`` é chave de unicidade (Req 2.7).
_DDL_PRATOS_MONITORADOS = """
CREATE TABLE IF NOT EXISTS pratos_monitorados (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    nome_original    TEXT NOT NULL,
    nome_normalizado TEXT NOT NULL UNIQUE
);
"""

# Ocorrências detectadas; vinculadas ao prato que as gerou (Req 3.2, 3.3).
_DDL_OCORRENCIAS = """
CREATE TABLE IF NOT EXISTS ocorrencias (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    prato_id    INTEGER NOT NULL,
    dia_semana  TEXT NOT NULL,
    refeicao    TEXT NOT NULL,
    restaurante TEXT NOT NULL,
    data_coleta TEXT NOT NULL,
    FOREIGN KEY (prato_id) REFERENCES pratos_monitorados (id) ON DELETE CASCADE
);
"""

# Configuração do Usuario em linha única (id fixo = 1): canal, contato, horário
# e fuso (Req 4.3, 1.7).
_DDL_CONFIGURACAO = """
CREATE TABLE IF NOT EXISTS configuracao (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    canal          TEXT,
    contato        TEXT,
    horario_coleta TEXT,
    fuso           TEXT NOT NULL DEFAULT 'America/Sao_Paulo'
);
"""

# Credencial em linha única (id fixo = 1): senha sempre criptografada em repouso
# (Req 6.2, 6.4, 6.5). ``senha_criptografada`` é BLOB (bytes).
_DDL_CREDENCIAL = """
CREATE TABLE IF NOT EXISTS credencial (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    login               TEXT NOT NULL,
    senha_criptografada BLOB NOT NULL
);
"""

# Índices para acelerar consultas de histórico (intervalo, busca e ranking).
_DDL_INDICES = (
    "CREATE INDEX IF NOT EXISTS idx_cardapios_data ON cardapios (data_coleta);",
    "CREATE INDEX IF NOT EXISTS idx_itens_cardapio_id ON itens_cardapio (cardapio_id);",
    "CREATE INDEX IF NOT EXISTS idx_ocorrencias_prato ON ocorrencias (prato_id);",
    "CREATE INDEX IF NOT EXISTS idx_ocorrencias_data ON ocorrencias (data_coleta);",
)

# Ordem importa: tabelas referenciadas antes das que as referenciam.
_DDL_TABELAS = (
    _DDL_CARDAPIOS,
    _DDL_ITENS_CARDAPIO,
    _DDL_PRATOS_MONITORADOS,
    _DDL_OCORRENCIAS,
    _DDL_CONFIGURACAO,
    _DDL_CREDENCIAL,
)


def conectar(caminho: Union[str, Path, None] = None) -> sqlite3.Connection:
    """Abre uma conexão SQLite configurada para uso pela aplicação.

    Ativa chaves estrangeiras (necessário para ``ON DELETE CASCADE``) e define
    ``row_factory`` como :class:`sqlite3.Row` para acesso por nome de coluna.

    Use ``":memory:"`` como ``caminho`` para um banco em memória (útil em testes).
    """
    alvo = ":memory:" if caminho == ":memory:" else str(caminho or CAMINHO_BANCO_PADRAO)
    conexao = sqlite3.connect(alvo)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys = ON;")
    return conexao


def inicializar_banco(
    caminho: Union[str, Path, None] = None,
    *,
    conexao: sqlite3.Connection | None = None,
) -> sqlite3.Connection:
    """Cria o esquema de forma idempotente e retorna a conexão.

    Pode receber uma ``conexao`` já aberta (ex.: banco em memória compartilhado
    em testes) ou um ``caminho`` de arquivo. Chamar a função mais de uma vez não
    recria nem apaga tabelas existentes (usa ``IF NOT EXISTS``), de modo que
    serve tanto para inicialização quanto para migração leve.
    """
    con = conexao if conexao is not None else conectar(caminho)
    con.execute("PRAGMA foreign_keys = ON;")

    with con:  # commit automático ao fim do bloco
        for ddl in _DDL_TABELAS:
            con.execute(ddl)
        for indice in _DDL_INDICES:
            con.execute(indice)
        _aplicar_versao(con)

    return con


def _aplicar_versao(con: sqlite3.Connection) -> None:
    """Registra a versão do esquema via ``PRAGMA user_version`` (idempotente)."""
    versao_atual = con.execute("PRAGMA user_version;").fetchone()[0]
    if versao_atual < VERSAO_ESQUEMA:
        # PRAGMA não aceita parâmetros vinculados; VERSAO_ESQUEMA é um int interno.
        con.execute(f"PRAGMA user_version = {int(VERSAO_ESQUEMA)};")
