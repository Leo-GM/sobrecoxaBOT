# Hospedar o Marimbondos Informes RU de graça (GitHub Actions)

O robô roda nos servidores do GitHub, nos horários certos, **sem depender do
seu PC ligado**. Siga os passos abaixo uma única vez.

## Como vai funcionar
- **Domingo 7h (horário de São Paulo):** envia o resumo da PRÓXIMA semana
  (segunda a domingo seguintes). Sempre envia (com ou sem sobrecoxa). Nunca
  mostra dia passado.
- **Todo dia 7h (horário de São Paulo):** checa o cardápio do dia e, se tiver
  sobrecoxa, envia o lembrete "Hoje tem...". Só o dia de hoje, nunca passado.
- **Keepalive (dia 1 de cada mês):** um commit automático mantém o repositório
  ativo para o GitHub não pausar os agendamentos (política de ~60 dias).
- O prato e o e-mail ficam no arquivo `config.json`. A senha do Gmail fica
  guardada como "Secret" no GitHub (nunca no código).

## Passo 1 — Criar o repositório no GitHub
1. Acesse https://github.com/new
2. Dê um nome (ex.: `marimbondos-informes-ru`), marque como **Private**
   (recomendado, já que envolve suas configurações) e clique em **Create
   repository**. NÃO adicione README/gitignore pela tela (já temos no projeto).

## Passo 2 — Subir o código (no terminal, dentro da pasta do projeto)
Troque `SEU-USUARIO` e o nome do repo pelos seus:

```powershell
cd "c:\Users\leo_s\OneDrive\Área de Trabalho\Busca_Sobrecoxa"
git init
git add .
git commit -m "Primeira versao do Marimbondos Informes RU"
git branch -M main
git remote add origin https://github.com/SEU-USUARIO/marimbondos-informes-ru.git
git push -u origin main
```

> O arquivo `.env` (com a senha) NÃO vai para o GitHub — ele está no
> `.gitignore`. Isso é proposital: a senha vai pelos Secrets (passo 3).

## Passo 3 — Cadastrar a senha do Gmail como Secret
No repositório, vá em **Settings → Secrets and variables → Actions → New
repository secret** e crie:

- Nome: `BUSCA_SMTP_USER`  → valor: `personalnotificationru@gmail.com`
- Nome: `BUSCA_SMTP_PASSWORD` → valor: a senha de app de 16 letras do Gmail

(Os demais — `BUSCA_SMTP_HOST`, `BUSCA_SMTP_PORT`, `BUSCA_SMTP_FROM` — são
opcionais; os padrões do Gmail já funcionam, pode deixar sem criar.)

## Passo 4 — Testar sem esperar o horário
Na aba **Actions** do repositório, abra o workflow **"Resumo semanal (domingo 7h)"**
e clique em **Run workflow**. Isso dispara o robô na hora.
Veja o log e confira o e-mail em `l247225@dac.unicamp.br`.
Faça o mesmo com **"Lembrete diário (7h)"** para testar o outro aviso.
Observação: ao rodar manualmente, o resumo mostra a PRÓXIMA semana — se ela
ainda não tiver sobrecoxa, nenhum e-mail é enviado (comportamento correto).

## Mudar o prato ou o e-mail depois
Edite o arquivo `config.json` (no GitHub dá para editar pelo próprio site:
abra o arquivo e clique no lápis), salve/commite, e pronto. Exemplo:

```json
{
  "email_destino": "l247225@dac.unicamp.br",
  "pratos": ["sobrecoxa"],
  "restaurante": "RU"
}
```

Para monitorar mais de um prato, adicione na lista: `["sobrecoxa", "feijoada"]`.

## Observações
- Os horários nos workflows estão em UTC (o GitHub usa UTC). Já ajustei para
  7h de São Paulo: resumo domingo 10:17 UTC; lembrete diário 10:23 UTC (minuto
  quebrado de propósito, pois horários "cheios" atrasam/pulam mais no GitHub).
  Se o Brasil voltar a ter horário de verão, esses horários precisariam de um
  ajuste de 1 hora.
- O GitHub Actions NÃO garante pontualidade de cron: pode atrasar alguns minutos
  e, em repositórios pouco ativos, às vezes pula uma execução. O keepalive
  mensal ajuda a manter o agendador ativo.
- O plano grátis do GitHub Actions é mais que suficiente para 1 execução/dia.
- A tela web de configuração continua existindo para uso local, mas na nuvem a
  configuração é o `config.json`.
