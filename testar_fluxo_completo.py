"""Teste manual de ponta a ponta do Marimbondos Informes RU com envio REAL por e-mail.

Simula o ciclo semanal inteiro, mas disparando os e-mails na hora (sem esperar
o sábado nem as 10h do dia do prato). Serve para validar que a notificação
chega no Gmail com o texto certo.

O que o script faz:
  1. Coleta o cardápio REAL da semana escolhida (bate no site da Unicamp).
  2. Detecta o prato que você informou (busca insensível a caixa/acento).
  3. Envia o e-mail de RESUMO da semana (o mesmo que sairia no sábado).
  4. Para cada dia em que o prato aparece, envia IMEDIATAMENTE o e-mail de
     LEMBRETE ("Hoje tem ... no almoço!") — simulando o aviso das 10h.

NÃO é um teste automatizado: faz conexão SMTP real e requisições ao site.

Configuração por variáveis de ambiente (PowerShell):
    $env:PYTHONPATH="."
    $env:BUSCA_SMTP_USER="seu-email@gmail.com"       # remetente/login (obrigatório)
    $env:BUSCA_SMTP_PASSWORD="senha-de-app-16-letras" # senha de app do Gmail (obrigatório)
    $env:BUSCA_SMTP_TO="para-onde-enviar@gmail.com"  # destinatário (opcional; default = USER)
    $env:BUSCA_PRATO="sobrecoxa"                       # prato a procurar (opcional; default = frango)
    $env:BUSCA_SEMANA="2026-11-09"                     # qualquer dia da semana alvo (opcional; default = hoje)

Uso:
    py testar_fluxo_completo.py

A senha NUNCA é impressa.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

from notificacoes_ru.coleta.coletor_publico import ClienteRequests, parsear_dia
from notificacoes_ru.deteccao.detector import detectar
from notificacoes_ru.nucleo.modelos import Cardapio_Semanal, Prato_Monitorado
from notificacoes_ru.nucleo.texto import normalizar
from notificacoes_ru.nucleo.tipos import Canal_de_Notificacao, Dado_de_Contato
from notificacoes_ru.notificacao.canais import criar_canal
from notificacoes_ru.notificacao.politica import NotificadorComRetry
from notificacoes_ru.notificacao.transporte_email import transporte_email_do_ambiente


def _dias_da_semana(referencia: date) -> list[date]:
    """Os 7 dias (segunda a domingo) da semana ISO que contem ``referencia``."""
    segunda = referencia - timedelta(days=referencia.weekday())
    return [segunda + timedelta(days=o) for o in range(7)]


def main() -> int:
    # 1. Valida a configuracao de e-mail.
    transporte = transporte_email_do_ambiente()
    if transporte is None:
        print(
            "ERRO: configure BUSCA_SMTP_USER e BUSCA_SMTP_PASSWORD "
            "(senha de app do Gmail) antes de rodar.\n"
            "Veja as instrucoes no topo deste arquivo.",
            file=sys.stderr,
        )
        return 1

    usuario = os.environ["BUSCA_SMTP_USER"]
    destinatario = os.environ.get("BUSCA_SMTP_TO") or usuario
    prato_nome = os.environ.get("BUSCA_PRATO", "frango").strip()
    semana_env = os.environ.get("BUSCA_SEMANA", "").strip()
    referencia = date.fromisoformat(semana_env) if semana_env else date.today()

    destino = Dado_de_Contato(canal=Canal_de_Notificacao.EMAIL, valor=destinatario)

    # Notificador real: canal de e-mail com o transporte SMTP do ambiente.
    canal = criar_canal(Canal_de_Notificacao.EMAIL, transporte)
    notificador = NotificadorComRetry(canal)

    # 2. Coleta REAL da semana escolhida, dia a dia.
    dias = _dias_da_semana(referencia)
    print(f"Coletando cardapio de {dias[0].isoformat()} a {dias[-1].isoformat()} ...")
    cliente = ClienteRequests()
    itens = []
    for d in dias:
        url = f"https://sistemas.prefeitura.unicamp.br/apps/cardapio/index.php?d={d.isoformat()}"
        try:
            html = cliente.get_html(url, timeout=60)
            itens.extend(parsear_dia(html, d))
        except Exception as erro:  # noqa: BLE001 - diagnostico do teste manual
            print(f"  aviso: falha ao coletar {d.isoformat()}: {type(erro).__name__}")

    if not itens:
        print("ERRO: nenhum item coletado do site (fonte indisponivel?).", file=sys.stderr)
        return 1

    cardapio = Cardapio_Semanal(
        restaurante="RU",
        data_coleta=referencia,
        semana_ano=referencia.isocalendar().week,
        itens=tuple(itens),
    )

    # 3. Detecta o prato monitorado.
    prato = Prato_Monitorado(nome_original=prato_nome, nome_normalizado=normalizar(prato_nome))
    mapa = detectar(cardapio, [prato])
    ocorrencias = list(mapa.get(prato, []))

    print(f"Prato buscado: '{prato_nome}' -> {len(ocorrencias)} ocorrencia(s) na semana.")
    if not ocorrencias:
        print(
            "Nenhuma ocorrencia encontrada para esse termo nesta semana.\n"
            "Dica: o RU costuma escrever 'frango', 'frango caipira', etc. "
            "Tente BUSCA_PRATO=frango para ver o fluxo com resultados."
        )
        # Ainda assim envia um e-mail de teste simples para validar o SMTP.
        print(f"Enviando e-mail de teste simples para {destinatario} ...")
        res = notificador.notificar_lembrete_dia(prato_nome, ["almoço"], None, destino)
        print("  resultado:", "ENTREGUE" if res.entregue else f"FALHOU ({res.falhas})")
        return 0 if res.entregue else 1

    # 4a. E-mail de RESUMO da semana (o que sairia no sabado).
    print(f"Enviando e-mail de RESUMO da semana para {destinatario} ...")
    res_resumo = notificador.notificar_ocorrencias(mapa, None, destino)
    print("  resumo:", "ENTREGUE" if res_resumo.entregue else f"FALHOU ({res_resumo.falhas})")

    # 4b. Um LEMBRETE por dia em que o prato aparece (simula o aviso das 10h).
    periodos_por_dia: dict[str, list[str]] = {}
    for oc in ocorrencias:
        periodos_por_dia.setdefault(oc.dia_semana, [])
        if oc.refeicao.value not in periodos_por_dia[oc.dia_semana]:
            periodos_por_dia[oc.dia_semana].append(oc.refeicao.value)

    for dia_semana, periodos in periodos_por_dia.items():
        print(f"Enviando LEMBRETE de {dia_semana} ({', '.join(periodos)}) ...")
        res = notificador.notificar_lembrete_dia(prato_nome, periodos, None, destino)
        print("  lembrete:", "ENTREGUE" if res.entregue else f"FALHOU ({res.falhas})")

    print("\nConcluido. Verifique a caixa de entrada (e o spam) de", destinatario)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
