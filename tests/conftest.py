"""Configuração compartilhada dos testes (pytest + Hypothesis).

Registra e ativa um perfil do Hypothesis que garante o mínimo de 100 iterações
por teste de propriedade exigido pela *Testing Strategy* do design.
"""

from __future__ import annotations

from hypothesis import HealthCheck, settings

# Mínimo de 100 iterações por teste de propriedade (Testing Strategy).
settings.register_profile(
    "ci",
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("ci")
