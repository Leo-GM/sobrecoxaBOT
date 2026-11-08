# Notificações_RU

Aplicação web que monitora automaticamente o cardápio dos Restaurantes
Universitários da Unicamp e notifica o usuário (WhatsApp, Telegram ou e-mail)
quando os pratos monitorados forem servidos. Mantém também um histórico anual
consultável do cardápio.

## Stack

- **Python 3.11+**
- Scraping: `requests` + `BeautifulSoup`
- Web/UI: FastAPI + Jinja2 (servido por `uvicorn`)
- Agendamento: APScheduler
- Persistência: SQLite
- Criptografia de credenciais: `cryptography` (Fernet)
- Testes: `pytest` + `Hypothesis` (property-based testing)

## Estrutura do projeto

```
notificacoes_ru/
├── nucleo/          # tipos conceituais e contratos (Protocols/ABCs)
├── coleta/          # coletor(es) de cardápio (scraping)
├── persistencia/    # modelos de dados e repositórios (SQLite)
├── notificacao/     # adaptadores de canal e política de notificação
├── agendamento/     # agendador do ciclo semanal
└── web/             # camada web / UI (FastAPI + Jinja2)
tests/               # testes unitários e de propriedade
```

## Desenvolvimento

Instale as dependências (incluindo as de desenvolvimento):

```bash
pip install -e ".[dev]"
```

Rode os testes:

```bash
pytest
```
