# Agente Orquestrador — CloudTrail + StackSpot AI

Orquestra consultas no AWS CloudTrail e envio ao agente StackSpot AI, processando registros de forma concorrente com retry exponencial e persistência imediata.

## Estrutura

```
agente-orquestrador/
├── main.py                        # Ponto de entrada (carrega CSV, mede tempo)
├── orquestrador.py                # Thread pool, retry, barras de progresso
├── aws/
│   ├── aws_auth.py                # SSO + AssumeRole com cache thread-safe
│   └── extrator_logs_aws.py       # Consulta CloudTrail via SQL (sem S3)
├── stackspot/
│   └── process_stackspot.py       # Cliente do agente com cache de token
├── utils/
│   └── logging_config.py          # Logs: INFO no console, WARNING+ em arquivo
├── setup.bat                      # Instalação e configuração inicial (Windows)
├── .env.example                   # Modelo de variáveis de ambiente
├── exemplo.csv                    # CSV de exemplo para testes
└── requirements.txt
```

## Configuração rápida (Windows)

```bat
setup.bat
```

O script instala as dependências, cria o `.env` e exibe as instruções.

## Configuração manual

```bash
pip install -r requirements.txt
cp .env.example .env
# Edite o .env com suas credenciais
aws sso login --profile bastion
```

## Uso

```bash
python main.py exemplo.csv
```

O CSV precisa ter ao menos: `account_id`, `data_inicio`, `data_fim`.

## Saída

| Arquivo | Conteúdo |
|---|---|
| `resultado.json` | Registros com `logs_cloudtrail` e `resposta_agente` |
| `execucao.log` | Logs WARNING e ERROR para debug |

### Comportamento quando não há logs

Se o CloudTrail não retornar eventos para um registro, o campo `resposta_agente` recebe `"Nenhuma log identificada para account_id <id>."` e o registro **não é enviado ao StackSpot**.

## Variáveis de ambiente

| Variável | Descrição |
|---|---|
| `STACKSPOT_REALM` | Realm da conta StackSpot |
| `STACKSPOT_CLIENT_ID` | Client ID da credencial de serviço |
| `STACKSPOT_CLIENT_SECRET` | Client Secret |
| `STACKSPOT_AGENT_ID` | ID do agente configurado |
| `STACKSPOT_AGENT_URL` | URL base da API do agente |
| `AWS_SSO_START_URL` | URL do portal SSO da organização |
| `AWS_SSO_REGION` | Região do SSO (ex: `us-east-1`) |
| `AWS_SSO_ACCOUNT_ID` | ID da conta bastion |
| `AWS_SSO_ROLE_NAME` | Nome da role na conta bastion |
| `AWS_ROLE_ARN_TEMPLATE` | ARN template com `{account_id}` |
| `AWS_DEFAULT_REGION` | Região padrão (padrão: `sa-east-1`) |
| `CLOUDTRAIL_QUERY` | Query SQL com `{account_id}`, `{data_inicio}`, `{data_fim}` |
| `WORKERS` | Workers paralelos (padrão: `3`) |
| `MAX_TENTATIVAS` | Máximo de tentativas com retry (padrão: `3`) |
