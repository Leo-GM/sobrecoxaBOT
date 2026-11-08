"""Modelos de dados conceituais do domínio.

Dataclasses que descrevem as entidades do design (seção *Data Models*). São
contratos de forma de dado — a persistência, validação e demais regras de
negócio ficam a cargo das camadas concretas (tarefas posteriores).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time

from notificacoes_ru.nucleo.tipos import (
    Canal_de_Notificacao,
    Refeicao,
    Restaurante_Universitario,
)


@dataclass(frozen=True)
class ItemCardapio:
    """Texto de um prato servido num ``(diaSemana, refeicao)`` específico."""

    dia_semana: str
    refeicao: Refeicao
    texto_item: str


@dataclass(frozen=True)
class Cardapio_Semanal:
    """Cardápio de um restaurante numa semana.

    Composto por itens indexados por ``(diaSemana, refeicao)``; armazenado com
    ``data_coleta`` e ``restaurante`` (Req 1.3).
    """

    restaurante: Restaurante_Universitario
    data_coleta: date
    semana_ano: int
    itens: tuple[ItemCardapio, ...] = ()


@dataclass(frozen=True)
class Prato_Monitorado:
    """Nome de prato cadastrado pelo Usuario para ser procurado.

    Guarda ``nome_original`` (como o Usuario digitou, com trim) e
    ``nome_normalizado`` (chave de unicidade e de busca). Entre 1 e 100
    caracteres; até 50 por usuário (Req 2).
    """

    nome_original: str
    nome_normalizado: str


@dataclass(frozen=True)
class Ocorrencia:
    """Resultado da detecção de um prato num cardápio (Req 3.2)."""

    dia_semana: str
    refeicao: Refeicao
    restaurante: Restaurante_Universitario
    data_coleta: date


@dataclass(frozen=True)
class Configuracao:
    """Preferências do Usuario: canal, contato, horário e fuso."""

    canal: Canal_de_Notificacao | None = None
    contato: str | None = None
    horario_coleta: time | None = None
    fuso: str = "America/Sao_Paulo"


@dataclass(frozen=True)
class Credencial_Unicamp:
    """Par de login e senha institucional da Unicamp (opcional).

    A senha é mantida criptografada em repouso (``senha_criptografada``); o
    valor em claro nunca é persistido (Req 6.2, 6.4, 6.5).
    """

    login: str
    senha_criptografada: bytes = field(repr=False, default=b"")
