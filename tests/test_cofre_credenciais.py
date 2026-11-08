"""Testes unitários do Cofre de Credenciais com Fernet (Tarefa 5.1).

Cobrem o contrato ``nucleo.CofreCredenciais`` implementado por
``CofreCredenciaisFernet``: round trip de criptografia (Req 6.2), rejeição de
login/senha vazios preservando a credencial anterior (Req 6.3), mascaramento na
exibição (Req 6.4), omissão da senha em claro em representações/saídas (Req 6.5)
e remoção (Req 6.8).
"""

from __future__ import annotations

import sqlite3

import pytest

from notificacoes_ru.nucleo.contratos import CofreCredenciais
from notificacoes_ru.nucleo.modelos import Credencial_Unicamp
from notificacoes_ru.persistencia import conectar, inicializar_banco
from notificacoes_ru.seguranca import (
    CARACTERE_MASCARA,
    CofreCredenciaisFernet,
    CredencialAusenteError,
    carregar_ou_criar_chave,
    gerar_chave,
)


@pytest.fixture()
def cofre() -> CofreCredenciaisFernet:
    con = conectar(":memory:")
    inicializar_banco(conexao=con)
    return CofreCredenciaisFernet(con, gerar_chave())


# -- Contrato -------------------------------------------------------------


def test_satisfaz_o_protocolo_cofre_credenciais(cofre: CofreCredenciaisFernet):
    # runtime_checkable: a instância deve satisfazer o Protocol do núcleo.
    assert isinstance(cofre, CofreCredenciais)


# -- Req 6.2: round trip de criptografia ----------------------------------


def test_armazenar_cifra_senha_em_repouso(cofre: CofreCredenciaisFernet):
    cofre.armazenar("ra123456", "minha-senha-secreta")

    bruto = cofre._con.execute(
        "SELECT senha_criptografada FROM credencial WHERE id = 1;"
    ).fetchone()[0]

    assert isinstance(bruto, bytes)
    # O valor em repouso difere do texto claro (Req 6.2 / Property 17).
    assert b"minha-senha-secreta" not in bruto


def test_round_trip_decifra_senha_original(cofre: CofreCredenciaisFernet):
    cofre.armazenar("ra123456", "s3nh@-ção-🔑")

    assert cofre.obter_senha_em_claro() == "s3nh@-ção-🔑"


def test_obter_para_coleta_retorna_modelo_com_senha_cifrada(
    cofre: CofreCredenciaisFernet,
):
    cofre.armazenar("ra123456", "abc123")

    credencial = cofre.obter_para_coleta()

    assert isinstance(credencial, Credencial_Unicamp)
    assert credencial.login == "ra123456"
    assert isinstance(credencial.senha_criptografada, bytes)
    assert b"abc123" not in credencial.senha_criptografada


def test_atualizar_credencial_sobrescreve_linha_unica(cofre: CofreCredenciaisFernet):
    cofre.armazenar("ra111111", "senha-antiga")
    cofre.armazenar("ra222222", "senha-nova")

    credencial = cofre.obter_para_coleta()
    assert credencial.login == "ra222222"
    assert cofre.obter_senha_em_claro() == "senha-nova"
    total = cofre._con.execute("SELECT COUNT(*) FROM credencial;").fetchone()[0]
    assert total == 1


# -- Req 6.3: rejeição de vazios preservando credencial anterior ----------


@pytest.mark.parametrize(
    "login,senha",
    [
        ("", "senha"),
        ("   ", "senha"),
        ("login", ""),
        ("login", "   "),
        ("", ""),
    ],
)
def test_rejeita_login_ou_senha_vazios(
    cofre: CofreCredenciaisFernet, login: str, senha: str
):
    with pytest.raises(ValueError):
        cofre.armazenar(login, senha)
    assert not cofre.existe()


def test_rejeicao_preserva_credencial_anterior(cofre: CofreCredenciaisFernet):
    cofre.armazenar("ra123456", "senha-valida")

    with pytest.raises(ValueError):
        cofre.armazenar("", "")

    # A credencial anterior permanece intacta (Req 6.3).
    assert cofre.obter_para_coleta().login == "ra123456"
    assert cofre.obter_senha_em_claro() == "senha-valida"


# -- Req 6.4: mascaramento na exibição ------------------------------------


def test_mascarar_substitui_todos_os_caracteres(cofre: CofreCredenciaisFernet):
    cofre.armazenar("ra123456", "senha123")

    mascarada = cofre.mascarar_para_exibicao()

    assert mascarada == CARACTERE_MASCARA * len("senha123")
    assert "senha123" not in mascarada


def test_mascarar_sem_credencial_retorna_vazio(cofre: CofreCredenciaisFernet):
    assert cofre.mascarar_para_exibicao() == ""


# -- Req 6.5: a senha em claro nunca aparece em representações -------------


def test_repr_nao_expoe_senha(cofre: CofreCredenciaisFernet):
    cofre.armazenar("ra123456", "senha-ultra-secreta")

    texto = repr(cofre)
    assert "senha-ultra-secreta" not in texto
    assert "com credencial" in texto


def test_repr_vazio_quando_sem_credencial(cofre: CofreCredenciaisFernet):
    assert "vazio" in repr(cofre)


def test_modelo_credencial_omite_senha_no_repr(cofre: CofreCredenciaisFernet):
    cofre.armazenar("ra123456", "senha-x")
    credencial = cofre.obter_para_coleta()
    # senha_criptografada tem repr=False no dataclass (Req 6.5).
    assert "senha_criptografada" not in repr(credencial)


# -- Req 6.8: remoção -----------------------------------------------------


def test_remover_apaga_credencial(cofre: CofreCredenciaisFernet):
    cofre.armazenar("ra123456", "senha")
    assert cofre.existe()

    cofre.remover()

    assert not cofre.existe()


def test_remover_e_idempotente(cofre: CofreCredenciaisFernet):
    cofre.remover()  # sem credencial — não deve falhar
    cofre.remover()
    assert not cofre.existe()


# -- Erros ao ler credencial ausente --------------------------------------


def test_obter_para_coleta_sem_credencial_levanta(cofre: CofreCredenciaisFernet):
    with pytest.raises(CredencialAusenteError):
        cofre.obter_para_coleta()


def test_obter_senha_em_claro_sem_credencial_levanta(
    cofre: CofreCredenciaisFernet,
):
    with pytest.raises(CredencialAusenteError):
        cofre.obter_senha_em_claro()


# -- Gestão de chave ------------------------------------------------------


def test_carregar_ou_criar_chave_persiste_e_reutiliza(tmp_path):
    caminho = tmp_path / "chave.key"

    chave1 = carregar_ou_criar_chave(caminho)
    assert caminho.exists()
    chave2 = carregar_ou_criar_chave(caminho)

    # Segunda chamada reutiliza a mesma chave persistida.
    assert chave1 == chave2


def test_chave_persistida_decifra_entre_instancias(tmp_path):
    caminho = tmp_path / "chave.key"
    chave = carregar_ou_criar_chave(caminho)

    con = conectar(":memory:")
    inicializar_banco(conexao=con)
    cofre_a = CofreCredenciaisFernet(con, chave)
    cofre_a.armazenar("ra123456", "persistente")

    # Outra instância com a mesma chave e conexão decifra o valor.
    cofre_b = CofreCredenciaisFernet(con, carregar_ou_criar_chave(caminho))
    assert cofre_b.obter_senha_em_claro() == "persistente"


def test_chave_invalida_rejeitada_na_construcao():
    con = conectar(":memory:")
    inicializar_banco(conexao=con)
    with pytest.raises((ValueError, Exception)):
        CofreCredenciaisFernet(con, b"chave-invalida")
