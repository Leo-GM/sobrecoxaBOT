"""Camada de detecção do Notificações_RU.

Implementa o contrato ``Detector`` do núcleo (Req 3): localiza cada
``Prato_Monitorado`` nos itens de um ``Cardapio_Semanal`` usando o Normalizador
compartilhado e produz as ``Ocorrencia`` correspondentes.
"""

from notificacoes_ru.deteccao.detector import (
    CardapioInvalidoError,
    DetectorPadrao,
    detectar,
)

__all__ = [
    "CardapioInvalidoError",
    "DetectorPadrao",
    "detectar",
]
