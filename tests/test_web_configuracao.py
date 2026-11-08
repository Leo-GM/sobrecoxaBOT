"""Testes da camada web de configuração (Tarefa 11.1).

Exercita os endpoints e telas de configuração via ``fastapi.testclient``
(TestClient sobre httpx) — sem servidor vivo nem rede real, e com SQLite em
memória. Cobre:

* pratos monitorados: listar/adicionar (trim, tamanho, unicidade, limite) e
  remover (Req 2.1, 2.3, 2.4, 2.5, 2.7);
* canal e contato: seleção com validação por canal e bloqueio sem canal válido
  (Req 4.3, 4.8, 4.9);
* horário de coleta (Req 1.7).

As asserções verificam tanto o efeito no estado (via repositórios/cofre) quanto
as mensagens exibidas na tela após o *Post/Redirect/Get*.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from notificacoes_ru.seguranca.cofre import gerar_chave
from notificacoes_ru.web import ContextoApp, construir_contexto, create_app


@pytest.fixture()
def contexto() -> ContextoApp:
    """``ContextoApp`` com SQLite em memória compartilhável entre threads.

    O ``check_same_thread=False`` é necessário porque o FastAPI executa os
    endpoints síncronos em um threadpool; a conexão em memória vive enquanto a
    fixture existir.
    """
    con = sqlite3.connect(":memory:", check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON;")
    return construir_contexto(conexao=con, chave_fernet=gerar_chave())


@pytest.fixture()
def client(contexto: ContextoApp) -> TestClient:
    """TestClient sobre a aplicação criada a partir do contexto em memória."""
    return TestClient(create_app(contexto=contexto))


# ---------------------------------------------------------------------------
# Tela principal e redirecionamento da raiz
# ---------------------------------------------------------------------------
def test_raiz_redireciona_para_configuracao(client: TestClient) -> None:
    resposta = client.get("/", follow_redirects=False)
    assert resposta.status_code == 303
    assert resposta.headers["location"] == "/configuracao"


def test_tela_configuracao_renderiza(client: TestClient) -> None:
    resposta = client.get("/configuracao")
    assert resposta.status_code == 200
    assert "Pratos monitorados" in resposta.text
    assert "E-mail de notificação" in resposta.text


# ---------------------------------------------------------------------------
# Pratos monitorados (Req 2)
# ---------------------------------------------------------------------------
def test_adicionar_prato_faz_trim_e_lista(
    client: TestClient, contexto: ContextoApp
) -> None:
    resposta = client.post(
        "/configuracao/pratos",
        data={"nome": "  Sobrecoxa de Frango "},
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert "Sobrecoxa de Frango" in resposta.text

    pratos = contexto.config_repo.pratos_monitorados()
    assert [p.nome_original for p in pratos] == ["Sobrecoxa de Frango"]


def test_adicionar_prato_vazio_e_rejeitado(
    client: TestClient, contexto: ContextoApp
) -> None:
    resposta = client.post(
        "/configuracao/pratos", data={"nome": "   "}, follow_redirects=True
    )
    assert "entre 1 e 100" in resposta.text
    assert contexto.config_repo.pratos_monitorados() == []


def test_adicionar_prato_longo_demais_e_rejeitado(
    client: TestClient, contexto: ContextoApp
) -> None:
    resposta = client.post(
        "/configuracao/pratos", data={"nome": "a" * 101}, follow_redirects=True
    )
    assert "entre 1 e 100" in resposta.text
    assert contexto.config_repo.pratos_monitorados() == []


def test_adicionar_prato_duplicado_e_rejeitado(
    client: TestClient, contexto: ContextoApp
) -> None:
    client.post("/configuracao/pratos", data={"nome": "Sobrecoxa de Frango"})
    resposta = client.post(
        "/configuracao/pratos",
        data={"nome": "SOBRECOXA DE FRANGO"},
        follow_redirects=True,
    )
    assert "já está cadastrado" in resposta.text
    # A lista permanece com um único prato (o original).
    assert len(contexto.config_repo.pratos_monitorados()) == 1


def test_remover_prato(client: TestClient, contexto: ContextoApp) -> None:
    prato = contexto.config_repo.adicionar_prato("Arroz")
    resposta = client.post(
        "/configuracao/pratos/remover",
        data={"nome_normalizado": prato.nome_normalizado},
        follow_redirects=True,
    )
    assert resposta.status_code == 200
    assert contexto.config_repo.pratos_monitorados() == []


# ---------------------------------------------------------------------------
# Canal e contato (Req 4.3, 4.8, 4.9)
# ---------------------------------------------------------------------------
def test_sem_canal_valido_exibe_bloqueio(client: TestClient) -> None:
    resposta = client.get("/configuracao")
    assert "ativar o monitoramento" in resposta.text


def test_definir_email_valido(client: TestClient, contexto: ContextoApp) -> None:
    resposta = client.post(
        "/configuracao/canal",
        data={"contato": "aluno@unicamp.br"},
        follow_redirects=True,
    )
    assert "salvo" in resposta.text
    # Sem o aviso de bloqueio após configurar um e-mail válido (Req 4.9).
    assert "ativar o monitoramento" not in resposta.text

    canal, contato = contexto.config_repo.canal_e_contato()
    assert canal.value == "e-mail"
    assert contato.valor == "aluno@unicamp.br"


def test_definir_email_invalido_e_rejeitado(
    client: TestClient, contexto: ContextoApp
) -> None:
    resposta = client.post(
        "/configuracao/canal",
        data={"contato": "sem-arroba"},
        follow_redirects=True,
    )
    assert "inválido" in resposta.text
    # Nada foi persistido.
    assert contexto.config_repo.canal_e_contato() == (None, None)


def test_definir_email_vazio_e_rejeitado(
    client: TestClient, contexto: ContextoApp
) -> None:
    resposta = client.post(
        "/configuracao/canal",
        data={"contato": ""},
        follow_redirects=True,
    )
    assert "ausente ou inválido" in resposta.text
    assert contexto.config_repo.canal_e_contato() == (None, None)


# ---------------------------------------------------------------------------
# Horário de coleta (Req 1.7)
# ---------------------------------------------------------------------------
def test_definir_horario(client: TestClient, contexto: ContextoApp) -> None:
    resposta = client.post(
        "/configuracao/horario",
        data={"hora": "9", "minuto": "30"},
        follow_redirects=True,
    )
    assert "09:30" in resposta.text
    horario = contexto.config_repo.horario_coleta()
    assert (horario.hora, horario.minuto) == (9, 30)


def test_definir_horario_invalido_e_rejeitado(
    client: TestClient, contexto: ContextoApp
) -> None:
    resposta = client.post(
        "/configuracao/horario",
        data={"hora": "99", "minuto": "0"},
        follow_redirects=True,
    )
    assert "Horário inválido" in resposta.text
    # Mantém o padrão atual (sábado 11:00).
    horario = contexto.config_repo.horario_coleta()
    assert (horario.hora, horario.minuto) == (11, 0)
