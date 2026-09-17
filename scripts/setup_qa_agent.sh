#!/usr/bin/env bash
#
# setup_qa_agent.sh — Comandos de setup/validação do QA Agent BMG por épico.
#
# Uso:
#   Edite as variáveis abaixo, depois rode um bloco por vez:
#     ./setup_qa_agent.sh acesso        # Épico 1 — validar acesso AWS
#     ./setup_qa_agent.sh guardrails    # Épico 2 — criar guardrails
#     ./setup_qa_agent.sh s3            # Épico 2 — bucket + upload docs
#     ./setup_qa_agent.sh kb-test       # Épico 2/3 — testar retrieve na KB
#     ./setup_qa_agent.sh deploy        # Épico 2 — agentcore deploy
#     ./setup_qa_agent.sh e2e           # Épico 2/6 — validar end-to-end
#     ./setup_qa_agent.sh ingest        # Épico 3 — ingestão + sync KB
#     ./setup_qa_agent.sh rag           # Épico 3 — validar qualidade RAG
#     ./setup_qa_agent.sh lambdas-local # Épico 4 — testar handlers local
#     ./setup_qa_agent.sh lambdas-deploy# Épico 4 — deploy das 3 Lambdas
#     ./setup_qa_agent.sh subagents     # Épico 5/6 — testar subagents + sintaxe
#     ./setup_qa_agent.sh dev           # roda agentcore dev (browser)
#
# NÃO roda nada destrutivo automaticamente. Cada bloco é explícito.

set -euo pipefail

# ─────────────────────────────────────────────────────────────
# CONFIG — ajustar pro ambiente BMG
# ─────────────────────────────────────────────────────────────
PROFILE="${PROFILE:-ciandt_teste}"        # trocar pelo profile da conta BMG
REGION="${REGION:-us-east-1}"
PROJ="${PROJ:-$HOME/Documentos/Projetos/BMG/BMGQAAgent}"

MODEL_ID="us.anthropic.claude-sonnet-4-5-20250929-v1:0"
BUCKET="${BUCKET:-bmg-qa-agent-kb-source}"
KB_PREFIX="${KB_PREFIX:-kb-data}"

# Preenchidos após criar recursos (KB no Console, Lambdas, etc.)
KB_ID="${KB_ID:-}"                        # ex: X8RYNPZISY
DS_ID="${DS_ID:-}"                        # data source id da KB
ACCOUNT_ID="${ACCOUNT_ID:-}"              # id da conta (pra ARN das Lambdas)
LAMBDA_ROLE="${LAMBDA_ROLE:-bmg-qa-lambda-role-PPD}"
GUARDRAIL_ID="${GUARDRAIL_ID:-}"

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
say() { echo -e "\n=== $* ===\n"; }
need() { [ -n "${!1:-}" ] || { echo "ERRO: variável '$1' não definida. Edite o script ou exporte antes."; exit 1; }; }

# ─────────────────────────────────────────────────────────────
# SSO login (rodar primeiro se a conta BMG usar AWS SSO)
# ─────────────────────────────────────────────────────────────
sso-login() {
  say "AWS SSO login — profile $PROFILE"
  aws sso login --profile "$PROFILE"
  say "Confirmar identidade"
  aws sts get-caller-identity --profile "$PROFILE"
}

# ─────────────────────────────────────────────────────────────
# Épico 1 — Validar acesso AWS
# ─────────────────────────────────────────────────────────────
acesso() {
  say "Identidade"
  aws sts get-caller-identity --profile "$PROFILE"

  say "Bedrock — modelos Claude"
  aws bedrock list-foundation-models --profile "$PROFILE" --region "$REGION" \
    --query "modelSummaries[?contains(modelId,'claude')].modelId" --output table

  say "Bedrock — inference profiles Claude"
  aws bedrock list-inference-profiles --profile "$PROFILE" --region "$REGION" \
    --query "inferenceProfileSummaries[?contains(inferenceProfileName,'Claude')].[inferenceProfileId,status]" --output table

  say "S3 — listar buckets (global, sem region)"
  aws s3 ls --profile "$PROFILE"

  say "Lambda — listar funções"
  aws lambda list-functions --profile "$PROFILE" --region "$REGION" --query "Functions[].FunctionName"

  say "Bedrock — invoke Claude (gate do Épico 1)"
  echo '{"anthropic_version":"bedrock-2023-05-31","max_tokens":50,"messages":[{"role":"user","content":"Diga oi"}]}' > /tmp/bedrock_test.json
  aws bedrock-runtime invoke-model \
    --model-id "$MODEL_ID" \
    --profile "$PROFILE" --region "$REGION" \
    --content-type application/json --accept application/json \
    --body fileb:///tmp/bedrock_test.json /tmp/bedrock_out.json
  cat /tmp/bedrock_out.json | python3 -m json.tool
}

# ─────────────────────────────────────────────────────────────
# Épico 2 — Guardrails
# ─────────────────────────────────────────────────────────────
guardrails() {
  say "Criar guardrail"
  aws bedrock create-guardrail \
    --name "bmg-qa-agent-guardrail" \
    --profile "$PROFILE" --region "$REGION" \
    --blocked-input-messaging "Conteúdo bloqueado por política de compliance." \
    --blocked-outputs-messaging "Resposta bloqueada por política de compliance." \
    --content-policy-config '{"filtersConfig":[
      {"type":"SEXUAL","inputStrength":"HIGH","outputStrength":"HIGH"},
      {"type":"HATE","inputStrength":"HIGH","outputStrength":"HIGH"},
      {"type":"VIOLENCE","inputStrength":"HIGH","outputStrength":"HIGH"},
      {"type":"INSULTS","inputStrength":"HIGH","outputStrength":"HIGH"},
      {"type":"MISCONDUCT","inputStrength":"HIGH","outputStrength":"HIGH"}]}' \
    --sensitive-information-policy-config '{"piiEntitiesConfig":[
      {"type":"EMAIL","action":"ANONYMIZE"},
      {"type":"PHONE","action":"ANONYMIZE"},
      {"type":"NAME","action":"ANONYMIZE"},
      {"type":"CREDIT_DEBIT_CARD_NUMBER","action":"BLOCK"}]}' \
    --topic-policy-config '{"topicsConfig":[{
      "name":"dados_bancarios_sensiveis",
      "definition":"Saldos, transações, senhas, tokens ou dados financeiros de clientes",
      "examples":["Qual o saldo da conta 12345?"],
      "type":"DENY"}]}'

  say "Listar guardrails (pegar o ID)"
  aws bedrock list-guardrails --profile "$PROFILE" --region "$REGION"
  echo ">>> Defina GUARDRAIL_ID e rode: guardrail-version"
}

guardrail-version() {
  need GUARDRAIL_ID
  aws bedrock create-guardrail-version --guardrail-identifier "$GUARDRAIL_ID" \
    --profile "$PROFILE" --region "$REGION"
}

# ─────────────────────────────────────────────────────────────
# Épico 2 — S3 (bucket + upload)
# ─────────────────────────────────────────────────────────────
s3() {
  say "Criar bucket (se s3:CreateBucket liberado — senão usar bucket existente)"
  aws s3 mb "s3://$BUCKET" --profile "$PROFILE" --region "$REGION" || \
    echo "AVISO: mb falhou (SCP?). Use um bucket existente e ajuste \$BUCKET/\$KB_PREFIX."

  say "Upload dos docs pro S3"
  aws s3 sync "$PROJ/kb-test-data/" "s3://$BUCKET/$KB_PREFIX/" --profile "$PROFILE" --region "$REGION"

  say "Listar o que subiu"
  aws s3 ls "s3://$BUCKET/$KB_PREFIX/" --recursive --profile "$PROFILE"
}

# ─────────────────────────────────────────────────────────────
# Épico 2/3 — Testar retrieve na KB (KB criada no Console)
# ─────────────────────────────────────────────────────────────
kb-test() {
  need KB_ID
  aws bedrock-agent-runtime retrieve \
    --knowledge-base-id "$KB_ID" \
    --profile "$PROFILE" --region "$REGION" \
    --retrieval-query '{"text":"Quais rollbacks envolveram o módulo PIX?"}'
}

# ─────────────────────────────────────────────────────────────
# Épico 2 — AgentCore deploy (Runtime + Gateway + targets)
# ─────────────────────────────────────────────────────────────
deploy() {
  cd "$PROJ"
  say "Pré-requisitos"
  node --version
  agentcore --version
  echo ">>> Antes de continuar: trocar ACCOUNT_ID no agentcore.json pelos ARNs reais das Lambdas."
  say "Validar config"
  agentcore validate
  say "Deploy (cria Runtime + Gateway + targets via CDK)"
  agentcore deploy
  agentcore status
}

# ─────────────────────────────────────────────────────────────
# Épico 2/6 — Validar end-to-end
# ─────────────────────────────────────────────────────────────
e2e() {
  cd "$PROJ"
  agentcore invoke "Analise a GMUD CHG0074521" --profile "$PROFILE"
}

# ─────────────────────────────────────────────────────────────
# Épico 3 — Ingestão + sync KB
# ─────────────────────────────────────────────────────────────
ingest() {
  cd "$PROJ"
  say "Rodar script de ingestão (formata docs)"
  python scripts/ingest_kb.py

  say "Subir pro S3"
  aws s3 sync kb-test-data/ "s3://$BUCKET/$KB_PREFIX/" --profile "$PROFILE" --region "$REGION"

  need KB_ID; need DS_ID
  say "Disparar ingestion job na KB"
  aws bedrock-agent start-ingestion-job \
    --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
    --profile "$PROFILE" --region "$REGION"

  echo ">>> Acompanhar com: aws bedrock-agent get-ingestion-job --knowledge-base-id $KB_ID --data-source-id $DS_ID --ingestion-job-id <JOB_ID> --profile $PROFILE --region $REGION"
}

# ─────────────────────────────────────────────────────────────
# Épico 3 — Validar qualidade RAG
# ─────────────────────────────────────────────────────────────
rag() {
  cd "$PROJ"
  python scripts/test_retrieve.py
}

# ─────────────────────────────────────────────────────────────
# Épico 4 — Testar handlers local
# ─────────────────────────────────────────────────────────────
lambdas-local() {
  cd "$PROJ"
  python lambdas/get_gmud_metadata/handler.py
  python lambdas/get_rollback_history/handler.py
  python lambdas/get_score_info/handler.py
}

# ─────────────────────────────────────────────────────────────
# Épico 4 — Deploy das 3 Lambdas (quando lambda:CreateFunction liberado)
# ─────────────────────────────────────────────────────────────
lambdas-deploy() {
  need ACCOUNT_ID
  cd "$PROJ"
  local role_arn="arn:aws:iam::${ACCOUNT_ID}:role/${LAMBDA_ROLE}"

  for fn in get_gmud_metadata get_rollback_history get_score_info; do
    say "Deploy $fn"
    (cd "lambdas/$fn" && zip -q -r "/tmp/$fn.zip" handler.py)
    aws lambda create-function \
      --function-name "bmg-${fn//_/-}" \
      --runtime python3.12 --handler handler.lambda_handler \
      --zip-file "fileb:///tmp/$fn.zip" \
      --role "$role_arn" \
      --profile "$PROFILE" --region "$REGION" \
      || echo "AVISO: create-function falhou para $fn (SCP ou já existe?)."
  done

  say "Teste rápido da get_gmud_metadata deployada"
  aws lambda invoke --function-name bmg-get-gmud-metadata \
    --payload '{"gmud_id":"CHG0074521"}' --cli-binary-format raw-in-base64-out \
    --profile "$PROFILE" --region "$REGION" /tmp/lambda_out.json
  cat /tmp/lambda_out.json
}

# ─────────────────────────────────────────────────────────────
# Épico 5/6 — Testar subagents + sintaxe
# ─────────────────────────────────────────────────────────────
subagents() {
  cd "$PROJ"
  say "Checar sintaxe dos arquivos-chave"
  python -c "import ast; [ast.parse(open(f).read()) for f in ['app/BMGQAAgent/main.py','app/BMGQAAgent/local_tools.py','app/BMGQAAgent/subagents.py']]; print('OK')"
  say "Testar subagents isolados"
  python scripts/test_subagents.py
}

# ─────────────────────────────────────────────────────────────
# agentcore dev (browser)
# ─────────────────────────────────────────────────────────────
dev() {
  cd "$PROJ"
  echo "USE_LOCAL_TOOLS controla mock local vs Gateway MCP (ver agentcore/.env.local)"
  agentcore dev
}

# ─────────────────────────────────────────────────────────────
# Dispatcher
# ─────────────────────────────────────────────────────────────
CMD="${1:-help}"
case "$CMD" in
  acesso|guardrails|guardrail-version|s3|kb-test|deploy|e2e|ingest|rag|lambdas-local|lambdas-deploy|subagents|dev|sso-login)
    "$CMD" ;;
  *)
    cat <<'EOF'
Comandos disponíveis (rode um por vez):
  sso-login       (rodar 1º se a conta BMG usar SSO) aws sso login + confirmar identidade
  acesso          Épico 1 — validar acesso AWS (identidade, Bedrock, S3, Lambda, invoke)
  guardrails      Épico 2 — criar guardrail
  guardrail-version  Épico 2 — criar versão do guardrail (precisa GUARDRAIL_ID)
  s3              Épico 2 — criar bucket + upload docs
  kb-test         Épico 2/3 — testar retrieve na KB (precisa KB_ID)
  deploy          Épico 2 — agentcore validate + deploy + status
  e2e             Épico 2/6 — agentcore invoke (end-to-end)
  ingest          Épico 3 — ingestão + sync KB (precisa KB_ID, DS_ID)
  rag             Épico 3 — validar qualidade RAG
  lambdas-local   Épico 4 — testar handlers local
  lambdas-deploy  Épico 4 — deploy das 3 Lambdas (precisa ACCOUNT_ID)
  subagents       Épico 5/6 — checar sintaxe + testar subagents
  dev             roda agentcore dev (browser)
EOF
    echo
    echo "Config atual: PROFILE=$PROFILE REGION=$REGION BUCKET=$BUCKET KB_ID=${KB_ID:-<vazio>}"
    ;;
esac
