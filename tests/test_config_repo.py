"""Testes unitários de ``ConfigRepoSQLite`` (Tarefa 3.2).

Cobre as regras de negócio de cadastro de pratos monitorados (trim, validação
de tamanho, limite de 50, unicidade por nome normalizado, remoção e listagem),
canal/contato de notificação (Req 4.3) e horário de coleta (Req 1.7).
"""

from __future__ import annotations

import pytest

from notificacoes_ru.nucleo.tipos import (
    Canal_de_Notificacao,
    Dado_de_Contato,
    HorarioColeta,
)
from notificacoes_ru.persistencia import (
    ConfigRepoSQLite,
    ErroValidacaoConfig,
    LIMITE_PRATOS,
    inicializar_banco,
)


@pytest.fixture()
def repo() -> ConfigRepoSQLite:
    """``ConfigRepoSQLite`` sobre um banco SQLite em memória recém-inicializado."""
    con = inicializar_banco(":memory:")
    return ConfigRepoSQLite(con)


# ---------------------------------------------------------------------------
# Pratos monitorados
# ---------------------------------------------------------------------------
def test_adicionar_prato_faz_trim_e_registra(repo: ConfigRepoSQLite) -> None:
    prato = repo.adicionar_prato("  Sobrecoxa de Frango  ")

    assert prato.nome_original == "Sobrecoxa de Frango"
    assert prato.nome_normalizado == "sobrecoxa de frango"
    assert [p.nome_original for p in repo.pratos_monitorados()] == [
        "Sobrecoxa de Frango"
    ]


def test_listagem_preserva_ordem_de_cadastro(repo: ConfigRepoSQLite) -> None:
    repo.adicionar_prato("Arroz")
    repo.adicionar_prato("Feijão")
    repo.adicionar_prato("Bife")

    assert [p.nome_original for p in repo.pratos_monitorados()] == [
        "Arroz",
        "Feijão",
        "Bife",
    ]


def test_nome_vazio_apos_trim_e_rejeitado(repo: ConfigRepoSQLite) -> None:
    with pytest.raises(ErroValidacaoConfig):
        repo.adicionar_prato("    ")
    assert repo.pratos_monitorados() == []


def test_nome_acima_de_100_chars_e_rejeitado(repo: ConfigRepoSQLite) -> None:
    with pytest.raises(ErroValidacaoConfig):
        repo.adicionar_prato("a" * 101)
    assert repo.pratos_monitorados() == []


def test_nome_com_100_chars_e_aceito(repo: ConfigRepoSQLite) -> None:
    nome = "a" * 100
    repo.adicionar_prato(nome)
    assert len(repo.pratos_monitorados()) == 1


def test_unicidade_por_nome_normalizado(repo: ConfigRepoSQLite) -> None:
    repo.adicionar_prato("Sobrecoxa de Frango")

    # Mesma chave normalizada (caixa/acentuação diferentes) deve ser rejeitada.
    with pytest.raises(ErroValidacaoConfig):
        repo.adicionar_prato("SOBRECOXA DE FRANGO")

    assert len(repo.pratos_monitorados()) == 1


def test_limite_de_50_pratos(repo: ConfigRepoSQLite) -> None:
    for i in range(LIMITE_PRATOS):
        repo.adicionar_prato(f"prato {i}")

    assert len(repo.pratos_monitorados()) == LIMITE_PRATOS

    with pytest.raises(ErroValidacaoConfig):
        repo.adicionar_prato("prato excedente")

    assert len(repo.pratos_monitorados()) == LIMITE_PRATOS


def test_remover_prato(repo: ConfigRepoSQLite) -> None:
    prato = repo.adicionar_prato("Sobrecoxa de Frango")
    repo.remover_prato(prato.nome_normalizado)
    assert repo.pratos_monitorados() == []


def test_remover_prato_tolera_variacao_de_caixa(repo: ConfigRepoSQLite) -> None:
    repo.adicionar_prato("Sobrecoxa de Frango")
    repo.remover_prato("SOBRECOXA DE FRANGO")
    assert repo.pratos_monitorados() == []


def test_remover_prato_ausente_e_silencioso(repo: ConfigRepoSQLite) -> None:
    repo.adicionar_prato("Arroz")
    repo.remover_prato("inexistente")
    assert len(repo.pratos_monitorados()) == 1


def test_round_trip_adicionar_remover(repo: ConfigRepoSQLite) -> None:
    repo.adicionar_prato("Arroz")
    antes = repo.pratos_monitorados()

    novo = repo.adicionar_prato("Bife")
    repo.remover_prato(novo.nome_normalizado)

    assert repo.pratos_monitorados() == antes


# ---------------------------------------------------------------------------
# Canal e contato
# ---------------------------------------------------------------------------
def test_canal_e_contato_padrao_vazio(repo: ConfigRepoSQLite) -> None:
    assert repo.canal_e_contato() == (None, None)


def test_definir_e_obter_canal(repo: ConfigRepoSQLite) -> None:
    contato = Dado_de_Contato(canal=Canal_de_Notificacao.EMAIL, valor="a@b.com")
    repo.definir_canal(Canal_de_Notificacao.EMAIL, contato)

    canal, obtido = repo.canal_e_contato()
    assert canal == Canal_de_Notificacao.EMAIL
    assert obtido == contato


def test_definir_canal_rejeita_contato_vazio(repo: ConfigRepoSQLite) -> None:
    contato = Dado_de_Contato(canal=Canal_de_Notificacao.TELEGRAM, valor="   ")
    with pytest.raises(ErroValidacaoConfig):
        repo.definir_canal(Canal_de_Notificacao.TELEGRAM, contato)
    assert repo.canal_e_contato() == (None, None)


def test_definir_canal_rejeita_canal_divergente(repo: ConfigRepoSQLite) -> None:
    contato = Dado_de_Contato(canal=Canal_de_Notificacao.EMAIL, valor="a@b.com")
    with pytest.raises(ErroValidacaoConfig):
        repo.definir_canal(Canal_de_Notificacao.WHATSAPP, contato)


def test_redefinir_canal_atualiza(repo: ConfigRepoSQLite) -> None:
    repo.definir_canal(
        Canal_de_Notificacao.EMAIL,
        Dado_de_Contato(canal=Canal_de_Notificacao.EMAIL, valor="a@b.com"),
    )
    repo.definir_canal(
        Canal_de_Notificacao.WHATSAPP,
        Dado_de_Contato(canal=Canal_de_Notificacao.WHATSAPP, valor="+5519999999999"),
    )
    canal, contato = repo.canal_e_contato()
    assert canal == Canal_de_Notificacao.WHATSAPP
    assert contato.valor == "+5519999999999"


# ---------------------------------------------------------------------------
# Horário de coleta
# ---------------------------------------------------------------------------
def test_horario_padrao(repo: ConfigRepoSQLite) -> None:
    horario = repo.horario_coleta()
    assert horario.hora == 11
    assert horario.minuto == 0
    assert horario.fuso == "America/Sao_Paulo"
    assert horario.dia_semana == "sabado"


def test_definir_e_obter_horario_round_trip(repo: ConfigRepoSQLite) -> None:
    novo = HorarioColeta(hora=9, minuto=30, fuso="America/Bahia", dia_semana="terça")
    repo.definir_horario(novo)
    assert repo.horario_coleta() == novo


def test_definir_horario_preserva_canal(repo: ConfigRepoSQLite) -> None:
    contato = Dado_de_Contato(canal=Canal_de_Notificacao.EMAIL, valor="a@b.com")
    repo.definir_canal(Canal_de_Notificacao.EMAIL, contato)
    repo.definir_horario(HorarioColeta(hora=8, minuto=15))

    canal, obtido = repo.canal_e_contato()
    assert canal == Canal_de_Notificacao.EMAIL
    assert obtido == contato


def test_definir_canal_preserva_horario(repo: ConfigRepoSQLite) -> None:
    horario = HorarioColeta(hora=6, minuto=45, dia_semana="quarta")
    repo.definir_horario(horario)
    repo.definir_canal(
        Canal_de_Notificacao.TELEGRAM,
        Dado_de_Contato(canal=Canal_de_Notificacao.TELEGRAM, valor="@usuario"),
    )
    assert repo.horario_coleta() == horario


# ---------------------------------------------------------------------------
# Contrato estrutural
# ---------------------------------------------------------------------------
def test_satisfaz_protocolo_config_repo(repo: ConfigRepoSQLite) -> None:
    from notificacoes_ru.nucleo.contratos import ConfigRepo

    assert isinstance(repo, ConfigRepo)
