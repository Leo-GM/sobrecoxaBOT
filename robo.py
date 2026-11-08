"""Modo robô do Marimbondos Informes RU — execução única para o GitHub Actions.

Em vez de manter um processo/agendador ligado (como ``py -m notificacoes_ru``),
este script roda UMA vez e sai. O agendamento fica a cargo do GitHub Actions
(cron), que o chama nos horários certos. Isso permite hospedar o robô de graça,
sem depender do PC do usuário ligado.

Dois modos (primeiro argumento da linha de comando):

* ``resumo``   — coleta o cardápio da SEMANA e, se algum prato monitorado for
                 encontrado, envia um e-mail de resumo listando os dias/refeições.
                 (Equivale ao aviso de sábado.)
* ``lembrete`` — coleta o cardápio de HOJE e, se algum prato monitorado estiver
                 no cardápio do dia, envia o e-mail de lembrete ("Hoje tem...").
                 (Equivale ao aviso das 10h; rode diariamente de manhã.)

Configuração:
* ``config.json`` (no repositório): e-mail de destino, lista de pratos e
  restaurante. NÃO contém segredo.
* Variáveis de ambiente / GitHub Secrets: credenciais do Gmail
  (``BUSCA_SMTP_USER``, ``BUSCA_SMTP_PASSWORD`` e, opcionalmente,
  ``BUSCA_SMTP_HOST`` / ``BUSCA_SMTP_PORT`` / ``BUSCA_SMTP_FROM``).

Reutiliza os componentes já existentes do pacote ``notificacoes_ru``
(coletor público, detector, mensagens e transporte de e-mail). A senha NUNCA é
impressa.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

from notificacoes_ru.coleta.coletor_publico import (
    ClienteRequests,
    EstruturaInvalida,
    URL_PADRAO,
    parsear_dia,
)
from notificacoes_ru.deteccao.detector import detectar
from notificacoes_ru.nucleo.modelos import Cardapio_Semanal, Prato_Monitorado
from notificacoes_ru.nucleo.texto import normalizar
from notificacoes_ru.nucleo.tipos import Canal_de_Notificacao, Dado_de_Contato
from notificacoes_ru.notificacao.canais import criar_canal
from notificacoes_ru.notificacao.politica import NotificadorComRetry
from notificacoes_ru.notificacao.transporte_email import transporte_email_do_ambiente

CAMINHO_CONFIG = Path(__file__).resolve().parent / "config.json"
TIMEOUT_HTTP = 60


def _carregar_config() -> dict:
    """Lê ``config.json`` (e-mail de destino, pratos, restaurante)."""
    with open(CAMINHO_CONFIG, encoding="utf-8") as arquivo:
        return json.load(arquivo)


def _pratos_monitorados(config: dict) -> list[Prato_Monitorado]:
    """Constrói os ``Prato_Monitorado`` a partir da lista do config."""
    pratos = []
    for nome in config.get("pratos", []):
        nome_limpo = str(nome).strip()
        if nome_limpo:
            pratos.append(
                Prato_Monitorado(
                    nome_original=nome_limpo,
                    nome_normalizado=normalizar(nome_limpo),
                )
            )
    return pratos


def _coletar_itens(datas: list[date]):
    """Coleta e parseia o cardápio de cada data informada (offline-safe)."""
    cliente = ClienteRequests()
    itens = []
    for d in datas:
        separador = "&" if "?" in URL_PADRAO else "?"
        url = f"{URL_PADRAO}{separador}d={d.isoformat()}"
        try:
            html = cliente.get_html(url, timeout=TIMEOUT_HTTP)
            itens.extend(parsear_dia(html, d))
        except EstruturaInvalida:
            continue
        except Exception as erro:  # noqa: BLE001 - diagnóstico do robô
            print(f"  aviso: falha ao coletar {d.isoformat()}: {type(erro).__name__}")
    return itens


def _montar_notificador():
    """Monta o notificador real com o transporte de e-mail do ambiente.

    Retorna ``None`` quando as credenciais SMTP não estão configuradas.
    """
    transporte = transporte_email_do_ambiente()
    if transporte is None:
        return None
    canal = criar_canal(Canal_de_Notificacao.EMAIL, transporte)
    return NotificadorComRetry(canal)


def _destino(config: dict) -> Dado_de_Contato:
    return Dado_de_Contato(
        canal=Canal_de_Notificacao.EMAIL,
        valor=str(config["email_destino"]).strip(),
    )


def modo_resumo(config: dict, hoje: date) -> int:
    """Coleta a semana e envia o resumo dos pratos encontrados."""
    restaurante = config.get("restaurante", "RU")
    pratos = _pratos_monitorados(config)
    if not pratos:
        print("Nenhum prato configurado em config.json.")
        return 0

    segunda = hoje - timedelta(days=hoje.weekday())
    dias = [segunda + timedelta(days=o) for o in range(7)]
    print(f"[resumo] coletando {dias[0].isoformat()} a {dias[-1].isoformat()} ...")

    itens = _coletar_itens(dias)
    if not itens:
        print("[resumo] fonte indisponível ou sem itens; nada a enviar.")
        return 0

    cardapio = Cardapio_Semanal(
        restaurante=restaurante,
        data_coleta=hoje,
        semana_ano=hoje.isocalendar().week,
        itens=tuple(itens),
    )
    mapa = detectar(cardapio, pratos)
    tem_ocorrencia = any(lista for lista in mapa.values())
    if not tem_ocorrencia:
        print("[resumo] nenhum prato monitorado nesta semana; nenhum e-mail enviado.")
        return 0

    notificador = _montar_notificador()
    if notificador is None:
        print("ERRO: credenciais SMTP ausentes (BUSCA_SMTP_USER/PASSWORD).", file=sys.stderr)
        return 1

    destino = _destino(config)
    resultado = notificador.notificar_ocorrencias(mapa, None, destino)
    print("[resumo]", "ENTREGUE" if resultado.entregue else f"FALHOU ({resultado.falhas})")
    return 0 if resultado.entregue else 1


def modo_lembrete(config: dict, hoje: date) -> int:
    """Coleta o cardápio de HOJE e envia lembrete se o prato estiver nele."""
    restaurante = config.get("restaurante", "RU")
    pratos = _pratos_monitorados(config)
    if not pratos:
        print("Nenhum prato configurado em config.json.")
        return 0

    print(f"[lembrete] coletando o dia {hoje.isoformat()} ...")
    itens = _coletar_itens([hoje])
    if not itens:
        print("[lembrete] fonte indisponível ou sem itens hoje; nada a enviar.")
        return 0

    cardapio = Cardapio_Semanal(
        restaurante=restaurante,
        data_coleta=hoje,
        semana_ano=hoje.isocalendar().week,
        itens=tuple(itens),
    )
    mapa = detectar(cardapio, pratos)

    notificador = None
    destino = _destino(config)
    enviados = 0
    for prato, ocorrencias in mapa.items():
        if not ocorrencias:
            continue
        # Períodos (almoço/jantar) do prato hoje, sem repetir.
        periodos: list[str] = []
        for oc in ocorrencias:
            periodo = oc.refeicao.value
            if periodo not in periodos:
                periodos.append(periodo)

        if notificador is None:
            notificador = _montar_notificador()
            if notificador is None:
                print("ERRO: credenciais SMTP ausentes (BUSCA_SMTP_USER/PASSWORD).", file=sys.stderr)
                return 1

        resultado = notificador.notificar_lembrete_dia(
            prato.nome_original, periodos, None, destino
        )
        print(
            f"[lembrete] {prato.nome_original} ({', '.join(periodos)}):",
            "ENTREGUE" if resultado.entregue else f"FALHOU ({resultado.falhas})",
        )
        enviados += 1

    if enviados == 0:
        print("[lembrete] nenhum prato monitorado hoje; nenhum e-mail enviado.")
    return 0


def main(argv: list[str]) -> int:
    # Carrega .env localmente (no GitHub Actions as credenciais vêm dos Secrets).
    try:
        from dotenv import load_dotenv

        load_dotenv(override=False)
    except ImportError:
        pass

    modo = argv[1] if len(argv) > 1 else "resumo"
    config = _carregar_config()
    hoje = date.today()

    if modo == "resumo":
        return modo_resumo(config, hoje)
    if modo == "lembrete":
        return modo_lembrete(config, hoje)

    print(f"Modo desconhecido: {modo!r}. Use 'resumo' ou 'lembrete'.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
