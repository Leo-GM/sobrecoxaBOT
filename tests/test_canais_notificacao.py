"""Testes dos adaptadores de canal e da geração de mensagens (tarefa 8.1).

Cobrem:

* validação de contato por canal (Req 4.8);
* envio por cada adaptador com transporte mockado (offline/determinístico) —
  sucesso, falha e timeout convertidos em ``ResultadoEnvio`` (Req 4.2, 4.5);
* geração das mensagens de ocorrências (Req 4.1), de "nenhum prato encontrado"
  (Req 4.4) e de falha de coleta (Req 1.6).

Nenhum e-mail/mensagem real é enviado: o transporte é um duble em memória.
"""

from __future__ import annotations

from datetime import date

import pytest

from notificacoes_ru.nucleo.modelos import Ocorrencia, Prato_Monitorado
from notificacoes_ru.nucleo.tipos import Canal_de_Notificacao, Dado_de_Contato, Refeicao
from notificacoes_ru.notificacao.canais import (
    NotificadorEmail,
    NotificadorTelegram,
    NotificadorWhatsApp,
    criar_canal,
)
from notificacoes_ru.notificacao.mensagens import (
    mensagem_falha_coleta,
    mensagem_lembrete_dia,
    mensagem_ocorrencias,
    mensagem_sem_ocorrencias,
    validar_contato,
)


# ---------------------------------------------------------------------------
# Dubles de transporte (offline)
# ---------------------------------------------------------------------------


class TransporteOk:
    """Transporte que registra os envios e sempre tem sucesso."""

    def __init__(self) -> None:
        self.enviados: list[tuple[Dado_de_Contato, str, float]] = []

    def __call__(self, destino: Dado_de_Contato, mensagem: str, timeout: float) -> None:
        self.enviados.append((destino, mensagem, timeout))


def transporte_falha(destino: Dado_de_Contato, mensagem: str, timeout: float) -> None:
    raise RuntimeError("provedor indisponível")


def transporte_timeout(destino: Dado_de_Contato, mensagem: str, timeout: float) -> None:
    raise TimeoutError("estouro de tempo")


# ---------------------------------------------------------------------------
# Validação de contato por canal (Req 4.8)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("canal", "valor"),
    [
        (Canal_de_Notificacao.WHATSAPP, "+5519999998888"),
        (Canal_de_Notificacao.WHATSAPP, "5519999998888"),
        (Canal_de_Notificacao.WHATSAPP, "+55 (19) 99999-8888"),
        (Canal_de_Notificacao.TELEGRAM, "@usuario_valido"),
        (Canal_de_Notificacao.TELEGRAM, "123456789"),
        (Canal_de_Notificacao.TELEGRAM, "-100987654321"),
        (Canal_de_Notificacao.EMAIL, "aluno@dac.unicamp.br"),
    ],
)
def test_contato_valido_por_canal(canal: Canal_de_Notificacao, valor: str) -> None:
    assert validar_contato(Dado_de_Contato(canal=canal, valor=valor)) is True


@pytest.mark.parametrize(
    ("canal", "valor"),
    [
        (Canal_de_Notificacao.WHATSAPP, ""),
        (Canal_de_Notificacao.WHATSAPP, "   "),
        (Canal_de_Notificacao.WHATSAPP, "telefone"),
        (Canal_de_Notificacao.WHATSAPP, "012345"),  # começa com 0 / curto
        (Canal_de_Notificacao.TELEGRAM, "@ab"),  # curto demais
        (Canal_de_Notificacao.TELEGRAM, "sem_arroba"),
        (Canal_de_Notificacao.TELEGRAM, ""),
        (Canal_de_Notificacao.EMAIL, "sem-arroba"),
        (Canal_de_Notificacao.EMAIL, "a@b"),  # sem TLD
        (Canal_de_Notificacao.EMAIL, "a @b.com"),  # espaço
    ],
)
def test_contato_invalido_por_canal(canal: Canal_de_Notificacao, valor: str) -> None:
    assert validar_contato(Dado_de_Contato(canal=canal, valor=valor)) is False


# ---------------------------------------------------------------------------
# Envio pelos adaptadores (Req 4.2, 4.5)
# ---------------------------------------------------------------------------


def test_envio_sucesso_whatsapp_usa_timeout_30s() -> None:
    transporte = TransporteOk()
    canal = NotificadorWhatsApp(transporte)
    destino = Dado_de_Contato(Canal_de_Notificacao.WHATSAPP, "+5519999998888")

    resultado = canal.enviar(destino, "olá")

    assert resultado.sucesso is True
    assert resultado.motivo is None
    assert len(transporte.enviados) == 1
    _, mensagem, timeout = transporte.enviados[0]
    assert mensagem == "olá"
    assert timeout == 30.0


def test_envio_telegram_e_email_sucesso() -> None:
    for canal_cls, canal_enum, valor in [
        (NotificadorTelegram, Canal_de_Notificacao.TELEGRAM, "@usuario_valido"),
        (NotificadorEmail, Canal_de_Notificacao.EMAIL, "aluno@unicamp.br"),
    ]:
        transporte = TransporteOk()
        canal = canal_cls(transporte)
        destino = Dado_de_Contato(canal_enum, valor)
        assert canal.enviar(destino, "msg").sucesso is True
        assert len(transporte.enviados) == 1


def test_envio_rejeita_contato_invalido_sem_chamar_transporte() -> None:
    transporte = TransporteOk()
    canal = NotificadorEmail(transporte)
    destino = Dado_de_Contato(Canal_de_Notificacao.EMAIL, "invalido")

    resultado = canal.enviar(destino, "msg")

    assert resultado.sucesso is False
    assert "inválido" in resultado.motivo
    assert transporte.enviados == []  # transporte nunca é acionado


def test_envio_rejeita_canal_incompativel() -> None:
    transporte = TransporteOk()
    canal = NotificadorWhatsApp(transporte)
    destino = Dado_de_Contato(Canal_de_Notificacao.EMAIL, "aluno@unicamp.br")

    resultado = canal.enviar(destino, "msg")

    assert resultado.sucesso is False
    assert "não corresponde" in resultado.motivo
    assert transporte.enviados == []


def test_envio_falha_do_transporte_vira_resultado_falha() -> None:
    canal = NotificadorWhatsApp(transporte_falha)
    destino = Dado_de_Contato(Canal_de_Notificacao.WHATSAPP, "+5519999998888")

    resultado = canal.enviar(destino, "msg")

    assert resultado.sucesso is False
    assert resultado.motivo == "provedor indisponível"


def test_envio_timeout_do_transporte_vira_resultado_falha() -> None:
    canal = NotificadorEmail(transporte_timeout)
    destino = Dado_de_Contato(Canal_de_Notificacao.EMAIL, "aluno@unicamp.br")

    resultado = canal.enviar(destino, "msg")

    assert resultado.sucesso is False
    assert resultado.motivo == "estouro de tempo"


def test_criar_canal_retorna_adaptador_correto() -> None:
    transporte = TransporteOk()
    assert isinstance(
        criar_canal(Canal_de_Notificacao.WHATSAPP, transporte), NotificadorWhatsApp
    )
    assert isinstance(
        criar_canal(Canal_de_Notificacao.TELEGRAM, transporte), NotificadorTelegram
    )
    assert isinstance(
        criar_canal(Canal_de_Notificacao.EMAIL, transporte), NotificadorEmail
    )


def test_adaptadores_satisfazem_contrato_canalnotificacao() -> None:
    import notificacoes_ru.nucleo as nucleo

    transporte = TransporteOk()
    assert isinstance(NotificadorWhatsApp(transporte), nucleo.CanalNotificacao)
    assert isinstance(NotificadorTelegram(transporte), nucleo.CanalNotificacao)
    assert isinstance(NotificadorEmail(transporte), nucleo.CanalNotificacao)


# ---------------------------------------------------------------------------
# Geração de mensagens (Req 4.1, 4.4, 1.6)
# ---------------------------------------------------------------------------


def _ocorrencia(dia: str, refeicao: Refeicao, restaurante: str) -> Ocorrencia:
    return Ocorrencia(
        dia_semana=dia,
        refeicao=refeicao,
        restaurante=restaurante,
        data_coleta=date(2024, 3, 11),
    )


def test_mensagem_ocorrencias_cobre_prato_dia_refeicao_restaurante() -> None:
    prato = Prato_Monitorado("Sobrecoxa de frango", "sobrecoxa de frango")
    ocorrencias = {
        prato: [
            _ocorrencia("segunda", Refeicao.ALMOCO, "RU"),
            _ocorrencia("quarta", Refeicao.JANTAR, "RA"),
        ]
    }

    msg = mensagem_ocorrencias(ocorrencias)

    # Prato
    assert "Sobrecoxa de frango" in msg
    # Primeira ocorrência: dia, refeição, restaurante
    assert "segunda" in msg
    assert Refeicao.ALMOCO.value in msg
    assert "RU" in msg
    # Segunda ocorrência: cada ocorrência aparece separadamente (Req 3.3)
    assert "quarta" in msg
    assert Refeicao.JANTAR.value in msg
    assert "RA" in msg


def test_mensagem_ocorrencias_ignora_pratos_sem_ocorrencia() -> None:
    com = Prato_Monitorado("Feijoada", "feijoada")
    sem = Prato_Monitorado("Peixe", "peixe")
    ocorrencias = {
        com: [_ocorrencia("sexta", Refeicao.ALMOCO, "RU")],
        sem: [],
    }

    msg = mensagem_ocorrencias(ocorrencias)

    assert "Feijoada" in msg
    assert "Peixe" not in msg


def test_mensagem_ocorrencias_vazia_lanca_erro() -> None:
    with pytest.raises(ValueError):
        mensagem_ocorrencias({Prato_Monitorado("x", "x"): []})
    with pytest.raises(ValueError):
        mensagem_ocorrencias({})


def test_mensagem_sem_ocorrencias_informa_ausencia() -> None:
    msg = mensagem_sem_ocorrencias()
    assert "Nenhum" in msg
    assert "monitorados" in msg


def test_mensagem_falha_coleta_informa_indisponibilidade() -> None:
    msg = mensagem_falha_coleta()
    assert "cardápio" in msg
    assert "preservado" in msg


# ---------------------------------------------------------------------------
# Lembrete diário (Opção 1)
# ---------------------------------------------------------------------------


def test_mensagem_lembrete_um_periodo() -> None:
    msg = mensagem_lembrete_dia("Sobrecoxa", [Refeicao.ALMOCO.value])
    assert msg == "HOJE É SOBRECOXA NO ALMOÇO PORRAAAAA"


def test_mensagem_lembrete_so_jantar() -> None:
    msg = mensagem_lembrete_dia("Sobrecoxa", [Refeicao.JANTAR.value])
    assert msg == "HOJE É SOBRECOXA NO JANTA PORRAAAAA"


def test_mensagem_lembrete_dois_periodos() -> None:
    msg = mensagem_lembrete_dia(
        "Sobrecoxa", [Refeicao.ALMOCO.value, Refeicao.JANTAR.value]
    )
    assert msg == "HOJE É SOBRECOXA NO ALMOÇO/JANTA PORRAAAAA"
