"""Tipos conceituais básicos do domínio.

Enumerações e aliases de tipo compartilhados pelas camadas. São definições de
vocabulário do domínio — sem regra de negócio associada.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Refeicao(str, Enum):
    """Período de serviço de um Restaurante_Universitario (Glossary)."""

    ALMOCO = "almoço"
    JANTAR = "jantar"


class Canal_de_Notificacao(str, Enum):
    """Meio pelo qual o Notificador envia mensagens ao Usuario (Req 4.3)."""

    WHATSAPP = "WhatsApp"
    TELEGRAM = "Telegram"
    EMAIL = "e-mail"


# Identificador de um Restaurante_Universitario (ex.: "RU", "RA", "RS").
# Modelado como alias de ``str`` por ser apenas uma etiqueta no domínio.
Restaurante_Universitario = str


@dataclass(frozen=True)
class Dado_de_Contato:
    """Dado associado ao Canal_de_Notificacao usado para entregar mensagens.

    Número de telefone para WhatsApp, identificador para Telegram ou endereço
    de e-mail (Glossary / Req 4.8). A validação de formato por canal é
    responsabilidade da camada que implementa o contrato correspondente.
    """

    canal: Canal_de_Notificacao
    valor: str


@dataclass(frozen=True)
class HorarioColeta:
    """Horário agendado da coleta semanal.

    Padrão atual: sábado 11:00 (início do almoço) no fuso
    ``America/Sao_Paulo``, configurável pelo Usuario (Req 1.7).
    """

    hora: int
    minuto: int
    fuso: str = "America/Sao_Paulo"
    dia_semana: str = "sabado"
