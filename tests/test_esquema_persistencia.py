"""Testes unitários do esquema SQLite e da inicialização (Tarefa 3.1).

Cobrem: criação de todas as tabelas esperadas, idempotência da inicialização,
preservação de dados em reinicializações, chaves estrangeiras ativas e as
restrições de linha única de configuração/credencial.
"""

from __future__ import annotations

import sqlite3

import pytest

from notificacoes_ru.persistencia import (
    VERSAO_ESQUEMA,
    conectar,
    inicializar_banco,
)

TABELAS_ESPERADAS = {
    "cardapios",
    "itens_cardapio",
    "pratos_monitorados",
    "ocorrencias",
    "configuracao",
    "credencial",
}


def _nomes_de_tabelas(con: sqlite3.Connection) -> set[str]:
    linhas = con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table';"
    ).fetchall()
    return {linha["name"] for linha in linhas}


def test_inicializar_cria_todas_as_tabelas():
    con = conectar(":memory:")
    inicializar_banco(conexao=con)

    assert TABELAS_ESPERADAS.issubset(_nomes_de_tabelas(con))


def test_inicializacao_e_idempotente():
    con = conectar(":memory:")
    inicializar_banco(conexao=con)
    # Segunda chamada não deve lançar nem recriar tabelas.
    inicializar_banco(conexao=con)

    assert TABELAS_ESPERADAS.issubset(_nomes_de_tabelas(con))


def test_reinicializar_preserva_dados_existentes():
    con = conectar(":memory:")
    inicializar_banco(conexao=con)
    con.execute(
        "INSERT INTO pratos_monitorados (nome_original, nome_normalizado) "
        "VALUES (?, ?);",
        ("Sobrecoxa de Frango", "sobrecoxa de frango"),
    )
    con.commit()

    # Reinicializar não deve apagar o dado inserido.
    inicializar_banco(conexao=con)

    total = con.execute("SELECT COUNT(*) FROM pratos_monitorados;").fetchone()[0]
    assert total == 1


def test_versao_do_esquema_registrada():
    con = conectar(":memory:")
    inicializar_banco(conexao=con)

    versao = con.execute("PRAGMA user_version;").fetchone()[0]
    assert versao == VERSAO_ESQUEMA


def test_unicidade_de_prato_normalizado():
    con = conectar(":memory:")
    inicializar_banco(conexao=con)
    con.execute(
        "INSERT INTO pratos_monitorados (nome_original, nome_normalizado) "
        "VALUES (?, ?);",
        ("Sobrecoxa", "sobrecoxa"),
    )
    con.commit()

    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO pratos_monitorados (nome_original, nome_normalizado) "
            "VALUES (?, ?);",
            ("SOBRECOXA", "sobrecoxa"),
        )


def test_unicidade_de_cardapio_por_restaurante_e_data():
    con = conectar(":memory:")
    inicializar_banco(conexao=con)
    con.execute(
        "INSERT INTO cardapios (restaurante, data_coleta, semana_ano) "
        "VALUES (?, ?, ?);",
        ("RU", "2024-06-03", 23),
    )
    con.commit()

    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO cardapios (restaurante, data_coleta, semana_ano) "
            "VALUES (?, ?, ?);",
            ("RU", "2024-06-03", 23),
        )


def test_chave_estrangeira_cascade_em_itens():
    con = conectar(":memory:")
    inicializar_banco(conexao=con)
    cur = con.execute(
        "INSERT INTO cardapios (restaurante, data_coleta, semana_ano) "
        "VALUES (?, ?, ?);",
        ("RU", "2024-06-03", 23),
    )
    cardapio_id = cur.lastrowid
    con.execute(
        "INSERT INTO itens_cardapio (cardapio_id, dia_semana, refeicao, texto_item) "
        "VALUES (?, ?, ?, ?);",
        (cardapio_id, "segunda", "almoço", "sobrecoxa de frango assada"),
    )
    con.commit()

    con.execute("DELETE FROM cardapios WHERE id = ?;", (cardapio_id,))
    con.commit()

    restantes = con.execute("SELECT COUNT(*) FROM itens_cardapio;").fetchone()[0]
    assert restantes == 0


def test_item_orfao_rejeitado_com_fk_ativa():
    con = conectar(":memory:")
    inicializar_banco(conexao=con)

    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO itens_cardapio (cardapio_id, dia_semana, refeicao, texto_item) "
            "VALUES (?, ?, ?, ?);",
            (999, "segunda", "almoço", "item sem cardápio"),
        )


def test_configuracao_restrita_a_linha_unica():
    con = conectar(":memory:")
    inicializar_banco(conexao=con)
    con.execute("INSERT INTO configuracao (id, canal) VALUES (1, 'e-mail');")
    con.commit()

    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO configuracao (id, canal) VALUES (2, 'Telegram');")


def test_credencial_armazena_senha_como_bytes():
    con = conectar(":memory:")
    inicializar_banco(conexao=con)
    senha_cifrada = b"\x00\x01segredo-cifrado\xff"
    con.execute(
        "INSERT INTO credencial (id, login, senha_criptografada) VALUES (1, ?, ?);",
        ("ra123456", senha_cifrada),
    )
    con.commit()

    valor = con.execute(
        "SELECT senha_criptografada FROM credencial WHERE id = 1;"
    ).fetchone()[0]
    assert isinstance(valor, bytes)
    assert valor == senha_cifrada


def test_inicializar_em_arquivo(tmp_path):
    caminho = tmp_path / "banco_teste.db"
    con = inicializar_banco(caminho)
    try:
        assert TABELAS_ESPERADAS.issubset(_nomes_de_tabelas(con))
    finally:
        con.close()
    assert caminho.exists()
