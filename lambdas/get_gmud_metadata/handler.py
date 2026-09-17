"""
Lambda mock: get_gmud_metadata
Retorna metadados de uma GMUD do ServiceNow.
Em produção, fará query real na API REST do ServiceNow.
"""

import json

# Mock data — simula GMUDs reais do BMG
MOCK_GMUDS = {
    "CHG0074521": {
        "gmud_id": "CHG0074521",
        "titulo": "Atualização da API de PIX - Novo formato de chave aleatória",
        "descricao": (
            "Deploy da versão 3.2.0 do módulo PIX que adiciona suporte ao novo "
            "formato de chave aleatória conforme regulamentação BACEN. "
            "Inclui alteração na validação de input e no formato de resposta da API."
        ),
        "sistemas_afetados": ["API Gateway", "Core Banking", "Módulo PIX", "Anti-Fraude"],
        "tipo_mudanca": "normal",
        "janela_execucao": {
            "inicio": "2026-09-15T02:00:00-03:00",
            "fim": "2026-09-15T04:00:00-03:00"
        },
        "responsavel": "João Silva",
        "plano_rollback": (
            "1. Reverter deploy da API PIX para versão 3.1.2 via pipeline Jenkins\n"
            "2. Restaurar configuração do API Gateway (route /pix/v3)\n"
            "3. Invalidar cache do Redis (cluster pix-prod)\n"
            "4. Validar health check dos endpoints\n"
            "5. Notificar equipe de operações"
        ),
        "repositorios": [
            "https://git.bmg.internal/core-banking/modulo-pix/pull/342",
            "https://git.bmg.internal/infra/api-gateway-config/pull/89"
        ],
        "status": "planejada"
    },
    "CHG0074522": {
        "gmud_id": "CHG0074522",
        "titulo": "Migração de banco de dados - Módulo de Empréstimos",
        "descricao": (
            "Migração do schema do banco de dados Oracle para suportar novos "
            "campos de compliance LGPD no módulo de empréstimos consignados. "
            "Inclui scripts DDL, migração de dados e atualização da camada ORM."
        ),
        "sistemas_afetados": ["Módulo Empréstimos", "Database Oracle", "Batch Noturno", "BI/Analytics"],
        "tipo_mudanca": "normal",
        "janela_execucao": {
            "inicio": "2026-09-17T01:00:00-03:00",
            "fim": "2026-09-17T05:00:00-03:00"
        },
        "responsavel": "Maria Santos",
        "plano_rollback": (
            "1. Executar script de rollback DDL (rollback_v2.4.sql)\n"
            "2. Restaurar backup do tablespace EMPRESTIMOS_PROD\n"
            "3. Reverter deploy da aplicação para versão 2.3.8\n"
            "4. Validar integridade dos dados com script de verificação\n"
            "5. Re-executar batch de conciliação"
        ),
        "repositorios": [
            "https://git.bmg.internal/emprestimos/consignado/pull/201",
            "https://git.bmg.internal/dba/migrations/pull/55"
        ],
        "status": "planejada"
    },
    "CHG0074523": {
        "gmud_id": "CHG0074523",
        "titulo": "Hotfix - Timeout na integração com SERPRO",
        "descricao": (
            "Correção emergencial do timeout na consulta de CPF via SERPRO. "
            "Aumenta timeout de 5s para 15s e adiciona retry com backoff exponencial. "
            "Problema impacta 12% das aberturas de conta digital."
        ),
        "sistemas_afetados": ["Onboarding Digital", "Integração SERPRO", "API Gateway"],
        "tipo_mudanca": "emergencial",
        "janela_execucao": {
            "inicio": "2026-09-10T14:00:00-03:00",
            "fim": "2026-09-10T15:00:00-03:00"
        },
        "responsavel": "Carlos Oliveira",
        "plano_rollback": (
            "1. Reverter deploy do serviço onboarding-api para versão anterior\n"
            "2. Restaurar configuração de timeout original no API Gateway\n"
            "3. Monitorar taxa de erro por 15 minutos"
        ),
        "repositorios": [
            "https://git.bmg.internal/digital/onboarding-api/pull/178"
        ],
        "status": "planejada"
    },
}


def lambda_handler(event, context):
    """Handler principal da Lambda."""

    # Extrair input — pode vir do API Gateway ou do AgentCore
    if isinstance(event, str):
        event = json.loads(event)

    # Suporte a diferentes formatos de input
    body = event.get("body", event)
    if isinstance(body, str):
        body = json.loads(body)

    gmud_id = body.get("gmud_id") or body.get("change_number")

    if not gmud_id:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "gmud_id é obrigatório"})
        }

    gmud = MOCK_GMUDS.get(gmud_id)

    if not gmud:
        return {
            "statusCode": 404,
            "body": json.dumps({
                "error": f"GMUD {gmud_id} não encontrada",
                "gmuds_disponiveis": list(MOCK_GMUDS.keys())
            })
        }

    return {
        "statusCode": 200,
        "body": json.dumps(gmud, ensure_ascii=False)
    }


# Para teste local
if __name__ == "__main__":
    # Simula chamada
    test_event = {"gmud_id": "CHG0074521"}
    result = lambda_handler(test_event, None)
    print(json.dumps(json.loads(result["body"]), indent=2, ensure_ascii=False))
