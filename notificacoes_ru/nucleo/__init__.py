"""Núcleo do Notificações_RU: tipos conceituais e contratos.

Este subpacote define apenas os *contratos* (Protocols/ABCs) e os tipos
conceituais (dataclasses/enums) compartilhados pelas demais camadas. Não
contém implementação de regra de negócio — as implementações concretas vivem
em ``coleta``, ``persistencia``, ``notificacao``, ``agendamento`` e ``web``.
"""

from notificacoes_ru.nucleo.texto import contem, normalizar
from notificacoes_ru.nucleo.tipos import (
    Canal_de_Notificacao,
    Dado_de_Contato,
    HorarioColeta,
    Refeicao,
    Restaurante_Universitario,
)
from notificacoes_ru.nucleo.modelos import (
    Cardapio_Semanal,
    Configuracao,
    Credencial_Unicamp,
    ItemCardapio,
    Ocorrencia,
    Prato_Monitorado,
)
from notificacoes_ru.nucleo.resultados import (
    Falha,
    FalhaAutenticacao,
    ResultadoColeta,
    ResultadoEnvio,
    Sucesso,
    Vazio,
)
from notificacoes_ru.nucleo.contratos import (
    Agendador,
    CanalNotificacao,
    Coletor,
    CofreCredenciais,
    ConfigRepo,
    Detector,
    HistoricoRepo,
    Notificador,
)

__all__ = [
    # normalizador de texto
    "normalizar",
    "contem",
    # tipos
    "Canal_de_Notificacao",
    "Dado_de_Contato",
    "HorarioColeta",
    "Refeicao",
    "Restaurante_Universitario",
    # modelos
    "Cardapio_Semanal",
    "Configuracao",
    "Credencial_Unicamp",
    "ItemCardapio",
    "Ocorrencia",
    "Prato_Monitorado",
    # resultados
    "Falha",
    "FalhaAutenticacao",
    "ResultadoColeta",
    "ResultadoEnvio",
    "Sucesso",
    "Vazio",
    # contratos
    "Agendador",
    "CanalNotificacao",
    "Coletor",
    "CofreCredenciais",
    "ConfigRepo",
    "Detector",
    "HistoricoRepo",
    "Notificador",
]
