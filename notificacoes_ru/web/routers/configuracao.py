"""Router de configuração do Usuario (Tarefa 11.1).

Expõe as telas e endpoints de **configuração**:

* **Pratos monitorados** (Req 2.1, 2.3, 2.4, 2.5, 2.7): listar, adicionar
  (com *trim* e validação de 1–100 caracteres, limite de 50 e unicidade por
  nome normalizado) e remover.
* **E-mail de notificação** (Req 4.3, 4.8, 4.9): cadastrar o endereço de
  e-mail (único canal com envio real) com validação de formato; sinalizar
  quando não há e-mail válido configurado (bloqueio de ativação do
  monitoramento).
* **Horário de coleta** (Req 1.7): definir hora/minuto da coleta semanal.

Toda regra de negócio é delegada ao núcleo (``ConfigRepoSQLite``,
``notificacao.validar_contato``); este router só
traduz HTTP ↔ chamadas de serviço e escolhe a mensagem a exibir. Os POSTs
seguem o padrão *Post/Redirect/Get*: em sucesso ou erro de validação,
redirecionam de volta à tela de configuração com uma mensagem, evitando reenvio
de formulário.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from notificacoes_ru.notificacao import validar_contato
from notificacoes_ru.nucleo.tipos import (
    Canal_de_Notificacao,
    Dado_de_Contato,
    HorarioColeta,
)
from notificacoes_ru.persistencia.config_repo import (
    ConfigRepoSQLite,
    ErroValidacaoConfig,
)
from notificacoes_ru.web.dependencias import obter_config_repo
from notificacoes_ru.web.templating import templates

router = APIRouter(prefix="/configuracao", tags=["configuracao"])

# Tipos de mensagem exibidos na tela (classe CSS correspondente no template).
_SUCESSO = "sucesso"
_ERRO = "erro"


def _redirecionar(mensagem: str, tipo: str) -> RedirectResponse:
    """Redireciona para a tela de configuração carregando uma mensagem.

    Usa *Post/Redirect/Get*: a mensagem viaja por querystring e é exibida uma
    única vez no próximo GET, preservando o estado da configuração.
    """
    query = urlencode({"msg": mensagem, "tipo": tipo})
    return RedirectResponse(url=f"/configuracao?{query}", status_code=303)


# ---------------------------------------------------------------------------
# Tela principal de configuração (GET)
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def tela_configuracao(
    request: Request,
    msg: Optional[str] = None,
    tipo: Optional[str] = None,
    config_repo: ConfigRepoSQLite = Depends(obter_config_repo),
) -> HTMLResponse:
    """Renderiza a tela de configuração com o estado atual (Req 2.4, 4.3).

    Exibe a lista de pratos monitorados, o canal/contato configurados e o
    horário de coleta. Quando não há canal válido, sinaliza o bloqueio de
    ativação do monitoramento (Req 4.9).
    """
    pratos = config_repo.pratos_monitorados()
    canal, contato = config_repo.canal_e_contato()
    horario = config_repo.horario_coleta()

    canal_valido = contato is not None and validar_contato(contato)

    contexto = {
        "pratos": pratos,
        "canal_atual": canal,
        "contato_atual": contato.valor if contato is not None else "",
        "canal_valido": canal_valido,
        "horario": horario,
        "mensagem": msg,
        "mensagem_tipo": tipo,
    }
    return templates.TemplateResponse(request, "configuracao.html", contexto)


# ---------------------------------------------------------------------------
# Pratos monitorados (Req 2)
# ---------------------------------------------------------------------------


@router.post("/pratos")
def adicionar_prato(
    nome: str = Form(""),
    config_repo: ConfigRepoSQLite = Depends(obter_config_repo),
) -> RedirectResponse:
    """Adiciona um prato monitorado delegando ao ``ConfigRepo`` (Req 2.1, 2.5, 2.7).

    Erros de validação (nome vazio/longo demais, duplicado ou limite de 50
    atingido) chegam como :class:`ErroValidacaoConfig` e são exibidos ao
    Usuario; a lista atual permanece inalterada.
    """
    try:
        prato = config_repo.adicionar_prato(nome)
    except ErroValidacaoConfig as erro:
        return _redirecionar(str(erro), _ERRO)
    return _redirecionar(f'Prato "{prato.nome_original}" adicionado.', _SUCESSO)


@router.post("/pratos/remover")
def remover_prato(
    nome_normalizado: str = Form(...),
    config_repo: ConfigRepoSQLite = Depends(obter_config_repo),
) -> RedirectResponse:
    """Remove o prato monitorado indicado (Req 2.3). Operação idempotente."""
    config_repo.remover_prato(nome_normalizado)
    return _redirecionar("Prato removido.", _SUCESSO)


# ---------------------------------------------------------------------------
# E-mail de notificação (Req 4.3, 4.8)
# ---------------------------------------------------------------------------


@router.post("/canal")
def definir_canal(
    contato: str = Form(""),
    config_repo: ConfigRepoSQLite = Depends(obter_config_repo),
) -> RedirectResponse:
    """Define o e-mail de notificação (Req 4.3, 4.8).

    O único canal suportado é o e-mail (WhatsApp e Telegram não têm envio real),
    então o canal é fixado em ``EMAIL``. Valida o formato do endereço com
    ``notificacao.validar_contato`` antes de persistir; um e-mail ausente ou
    inválido é rejeitado, preservando o estado anterior.
    """
    dado = Dado_de_Contato(canal=Canal_de_Notificacao.EMAIL, valor=contato)
    if not validar_contato(dado):
        return _redirecionar(
            "E-mail ausente ou inválido. Informe um endereço como voce@exemplo.com.",
            _ERRO,
        )

    try:
        config_repo.definir_canal(Canal_de_Notificacao.EMAIL, dado)
    except ErroValidacaoConfig as erro:
        return _redirecionar(str(erro), _ERRO)

    return _redirecionar("E-mail de notificação salvo.", _SUCESSO)


# ---------------------------------------------------------------------------
# Horário de coleta (Req 1.7)
# ---------------------------------------------------------------------------


@router.post("/horario")
def definir_horario(
    hora: int = Form(...),
    minuto: int = Form(...),
    config_repo: ConfigRepoSQLite = Depends(obter_config_repo),
) -> RedirectResponse:
    """Define o horário da coleta semanal (Req 1.7).

    Valida que hora (0–23) e minuto (0–59) estão nos intervalos legais antes de
    delegar ao ``ConfigRepo``; o dia da semana e o fuso usam o padrão do design.
    """
    if not (0 <= hora <= 23) or not (0 <= minuto <= 59):
        return _redirecionar(
            "Horário inválido: informe hora entre 0 e 23 e minuto entre 0 e 59.",
            _ERRO,
        )

    config_repo.definir_horario(HorarioColeta(hora=hora, minuto=minuto))
    return _redirecionar(
        f"Horário de coleta definido para {hora:02d}:{minuto:02d}.", _SUCESSO
    )
