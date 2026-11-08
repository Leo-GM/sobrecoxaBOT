"""Tipos de resultado conceituais (sum types) usados pelos contratos.

Modelam ``ResultadoColeta`` e ``ResultadoEnvio`` do design como uma união de
dataclasses. São apenas estruturas de dados — a lógica que os produz vive nas
camadas concretas (tarefas posteriores).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from notificacoes_ru.nucleo.modelos import Cardapio_Semanal


@dataclass(frozen=True)
class Sucesso:
    """Coleta bem-sucedida com cardápio não vazio."""

    cardapio: Cardapio_Semanal


@dataclass(frozen=True)
class Vazio:
    """Cardápio extraído sem itens de refeição; não deve ser persistido (Req 1.4)."""


@dataclass(frozen=True)
class Falha:
    """Coleta malsucedida (indisponível, timeout ou estrutura inválida)."""

    motivo: str


@dataclass(frozen=True)
class FalhaAutenticacao:
    """Falha específica de autenticação com a Credencial_Unicamp (Req 6.6)."""

    motivo: str = "credenciais inválidas"


# ResultadoColeta = Sucesso(Cardapio_Semanal) | Vazio | Falha(motivo) | FalhaAutenticacao
ResultadoColeta = Union[Sucesso, Vazio, Falha, FalhaAutenticacao]


@dataclass(frozen=True)
class ResultadoEnvio:
    """Resultado de uma tentativa de envio por um CanalNotificacao (timeout 30s)."""

    sucesso: bool
    motivo: str | None = None
