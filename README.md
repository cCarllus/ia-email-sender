# Nerdin Mailer

Automação em Python para ler o TXT de vagas, enviar uma candidatura por e-mail para o destinatário de cada bloco e anexar o currículo em PDF.

## O que o programa faz

- lê blocos `EMAIL VAGA N` do TXT;
- extrai vaga, empresa, destinatário, assunto e corpo;
- ignora automaticamente blocos sem e-mail identificado;
- anexa o mesmo currículo PDF em todas as candidaturas;
- envia uma mensagem por vez;
- usa SMTP autenticado com TLS;
- mantém `state.json` para não reenviar vagas já concluídas;
- grava `logs/envios.csv` com sucesso, erro e vagas ignoradas;
- possui `--dry-run` para testar sem enviar;
- possui limite por execução e limite móvel de 24 horas.

## 1. Coloque os arquivos

Copie o TXT gerado para:

```text
data/vagas.txt
```

Copie o currículo para:

```text
data/curriculo.pdf
```

Ou passe caminhos diferentes usando `--txt` e `--cv`.

## 2. Configure o SMTP

Copie o exemplo:

```bash
cp .env.example .env
```

Edite `.env`.

### Gmail / Google Workspace

Use:

```text
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=seu-email@gmail.com
SMTP_PASSWORD=sua-senha-de-app
SMTP_FROM_EMAIL=seu-email@gmail.com
SMTP_FROM_NAME=Carlos Henrique Caldeira
SMTP_REPLY_TO=seu-email@gmail.com
DAILY_LIMIT=25
SEND_INTERVAL_SECONDS=120
```

Para Gmail, a senha deve ser uma **senha de app**, não a senha normal da conta.

## 3. Valide antes de enviar

```bash
python3 mailer.py --dry-run --limit 3
```

Isso mostra destinatário, assunto, anexo e parte do corpo sem enviar nada.

## 4. Faça um envio real de teste

Envie somente a vaga 1:

```bash
python3 mailer.py --send --only 1
```

Ou envie duas candidaturas:

```bash
python3 mailer.py --send --limit 2
```

## 5. Envio contínuo

```bash
python3 mailer.py --send
```

O programa respeita `DAILY_LIMIT` e `SEND_INTERVAL_SECONDS`. Quando o limite móvel das últimas 24 horas for alcançado, ele encerra sem continuar disparando.

Para começar em uma vaga específica:

```bash
python3 mailer.py --send --start-at 101
```

## Entregabilidade e caixa de spam

Nenhum código consegue garantir entrada na caixa principal. O que realmente ajuda é:

1. enviar por uma conta legítima e autenticada;
2. usar SMTP do próprio provedor;
3. manter SPF, DKIM e DMARC corretos quando usar domínio próprio;
4. enviar um por vez, com ritmo moderado;
5. usar assunto e corpo realmente relacionados à vaga;
6. não usar links encurtados, pixels de rastreamento, HTML promocional ou anexos suspeitos;
7. evitar centenas de mensagens em sequência em uma conta nova.

Este projeto deliberadamente não implementa técnicas para contornar filtros antispam. O objetivo é preservar a reputação da conta e fazer envios legítimos de candidatura.

## Arquivos gerados

### `state.json`

Registra as vagas enviadas com timestamp. Não apague se quiser evitar duplicatas.

### `logs/envios.csv`

Histórico legível em Excel/Sheets com status:

- `SENT`
- `ERROR`
- `SKIPPED_NO_EMAIL`

## Observação sobre as 804 vagas

O programa aceita o TXT inteiro. Blocos cujo campo `EMAIL DO RECRUTADOR` esteja como não identificado são ignorados automaticamente e registrados no log.
