"""Geração de mensagens de notificação e validação de contato por canal.

Este módulo concentra a lógica pura da camada de notificação que não depende
de I/O externo:

* ``validar_contato`` — validação do formato do ``Dado_de_Contato`` por canal
  (Req 4.8; Property 10).
* ``mensagem_ocorrencias`` — texto listando cada prato encontrado com seus
  dias, refeição e restaurante (Req 4.1; Property 9).
* ``mensagem_sem_ocorrencias`` — texto informando que nenhum prato monitorado
  foi encontrado na semana (Req 4.4).
* ``mensagem_falha_coleta`` — texto informando que o cardápio da semana não
  pôde ser obtido (Req 1.6).

As funções são puras (sem efeitos colaterais) para facilitar os testes de
propriedade e reuso pelas políticas de envio (tarefa 8.2).
"""

from __future__ import annotations

import re
from typing import Mapping, Sequence

from notificacoes_ru.nucleo.modelos import Ocorrencia, Prato_Monitorado
from notificacoes_ru.nucleo.tipos import Canal_de_Notificacao, Dado_de_Contato

# ---------------------------------------------------------------------------
# Validação de contato por canal (Req 4.8 / Property 10)
# ---------------------------------------------------------------------------

# Telefone (WhatsApp): formato E.164 — opcional "+", de 8 a 15 dígitos, sem
# começar por zero. Ex.: "+5519999998888".
_RE_TELEFONE = re.compile(r"^\+?[1-9]\d{7,14}$")

# Identificador do Telegram: "@" seguido de 5 a 32 caracteres [A-Za-z0-9_],
# ou um chat id puramente numérico (pode ser negativo para grupos/canais).
_RE_TELEGRAM_USERNAME = re.compile(r"^@[A-Za-z0-9_]{5,32}$")
_RE_TELEGRAM_CHAT_ID = re.compile(r"^-?\d+$")

# E-mail: validação pragmática de "parte-local@dominio.tld" sem espaços.
_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _telefone_valido(valor: str) -> bool:
    # Dígitos podem vir separados por espaços, hífens ou parênteses na entrada
    # do usuário; normalizamos removendo esses separadores antes de validar.
    limpo = re.sub(r"[\s\-()]", "", valor)
    return bool(_RE_TELEFONE.fullmatch(limpo))


def _telegram_valido(valor: str) -> bool:
    candidato = valor.strip()
    return bool(
        _RE_TELEGRAM_USERNAME.fullmatch(candidato)
        or _RE_TELEGRAM_CHAT_ID.fullmatch(candidato)
    )


def _email_valido(valor: str) -> bool:
    return bool(_RE_EMAIL.fullmatch(valor.strip()))


def validar_contato(contato: Dado_de_Contato) -> bool:
    """Indica se ``contato`` está no formato válido do seu canal (Req 4.8).

    Aceita se e somente se o valor existe (não vazio após trim) e satisfaz o
    formato esperado pelo ``Canal_de_Notificacao``:

    * ``WhatsApp``  → número de telefone (E.164, 8–15 dígitos);
    * ``Telegram``  → ``@username`` (5–32 chars) ou um chat id numérico;
    * ``e-mail``    → endereço ``local@dominio.tld``.

    Property 10: a configuração é aceita se e somente se o contato existe e
    está no formato válido do canal; caso contrário é rejeitada.
    """
    if contato is None:
        return False

    valor = contato.valor
    if valor is None or not valor.strip():
        return False

    if contato.canal is Canal_de_Notificacao.WHATSAPP:
        return _telefone_valido(valor)
    if contato.canal is Canal_de_Notificacao.TELEGRAM:
        return _telegram_valido(valor)
    if contato.canal is Canal_de_Notificacao.EMAIL:
        return _email_valido(valor)

    # Canal desconhecido: rejeita por segurança.
    return False


# ---------------------------------------------------------------------------
# Geração de mensagens
# ---------------------------------------------------------------------------


def _formatar_ocorrencia(ocorrencia: Ocorrencia) -> str:
    """Formata uma linha "dia, refeição, restaurante" de uma ocorrência."""
    refeicao = ocorrencia.refeicao.value
    return (
        f"{ocorrencia.dia_semana} ({refeicao}) "
        f"no {ocorrencia.restaurante}"
    )


def mensagem_ocorrencias(
    ocorrencias: Mapping[Prato_Monitorado, Sequence[Ocorrencia]],
) -> str:
    """Gera a mensagem listando cada prato encontrado e suas ocorrências.

    Para cada prato com ao menos uma ocorrência, inclui o nome do prato e, para
    cada ocorrência, o dia, a refeição e o restaurante correspondentes (Req
    4.1; Property 9). Pratos sem ocorrências não são listados.

    Lança ``ValueError`` se não houver nenhuma ocorrência — este caso é tratado
    por ``mensagem_sem_ocorrencias`` (Req 4.4).
    """
    pratos_com_ocorrencia = [
        (prato, list(lista))
        for prato, lista in ocorrencias.items()
        if lista
    ]
    if not pratos_com_ocorrencia:
        raise ValueError(
            "mensagem_ocorrencias requer ao menos uma ocorrência; "
            "use mensagem_sem_ocorrencias para o caso vazio"
        )

    linhas: list[str] = [
        "TEM SOBRECOXA CARALHOOOOO",
        "",
    ]
    for prato, lista in pratos_com_ocorrencia:
        linhas.append(f"- {prato.nome_original}:")
        for ocorrencia in lista:
            linhas.append(f"    • {_formatar_ocorrencia(ocorrencia)}")

    return "\n".join(linhas)


def mensagem_sem_ocorrencias() -> str:
    """Mensagem informando que nenhum prato monitorado foi encontrado (Req 4.4)."""
    return (
        "Nenhum dos pratos monitorados foi encontrado no cardápio desta semana."
    )


def mensagem_falha_coleta() -> str:
    """Mensagem informando que o cardápio da semana não pôde ser obtido (Req 1.6)."""
    return (
        "Não foi possível obter o cardápio dos Restaurantes Universitários "
        "desta semana. O último cardápio armazenado foi preservado."
    )


def _periodo_lembrete(refeicoes: Sequence[str]) -> str:
    """Rótulo do período para o lembrete: ALMOÇO, JANTA ou ALMOÇO/JANTA.

    Considera os períodos em que o prato é servido hoje (insensível a
    caixa/acento) e devolve:

    * só almoço          -> ``"ALMOÇO"``
    * só jantar          -> ``"JANTA"``
    * almoço e jantar    -> ``"ALMOÇO/JANTA"``
    """
    tem_almoco = any("almo" in r.lower() for r in refeicoes if r)
    tem_jantar = any("jant" in r.lower() for r in refeicoes if r)
    if tem_almoco and tem_jantar:
        return "ALMOÇO/JANTA"
    if tem_jantar:
        return "JANTA"
    if tem_almoco:
        return "ALMOÇO"
    return ""


def mensagem_lembrete_dia(prato_nome: str, refeicoes: Sequence[str]) -> str:
    """Mensagem de lembrete de que um prato é servido hoje (Opção 1).

    Cobre os três casos de período em caixa alta, no estilo pedido:

    * só almoço        -> ``"HOJE É SOBRECOXA NO ALMOÇO PORRAAAAA"``
    * só jantar        -> ``"HOJE É SOBRECOXA NO JANTA PORRAAAAA"``
    * almoço e jantar  -> ``"HOJE É SOBRECOXA NO ALMOÇO/JANTA PORRAAAAA"``

    O nome do prato entra em caixa alta (ex.: ``sobrecoxa`` -> ``SOBRECOXA``).
    """
    periodo = _periodo_lembrete(refeicoes)
    prato = prato_nome.upper()
    if not periodo:
        return f"HOJE É {prato} PORRAAAAA"
    return f"HOJE É {prato} NO {periodo} PORRAAAAA"
