"""
Lambda mock: get_rollback_history
Consulta histórico de rollbacks em GMUDs anteriores.
Em produção, fará query no banco de incidentes/Knowledge Base.
"""

import json

# Mock data — simula histórico real de rollbacks do BMG
MOCK_ROLLBACKS = [
    {
        "gmud_id": "CHG0071234",
        "data": "2026-07-10",
        "sistemas_afetados": ["Core Banking", "Módulo PIX", "API Gateway"],
        "causa_raiz": (
            "Timeout na integração com sistema legado de cartões. "
            "O novo endpoint chamava o mainframe com payload maior que o suportado, "
            "causando timeout após 30s e cascateando para o API Gateway."
        ),
        "categoria_falha": "timeout",
        "impacto": "Indisponibilidade do PIX por 23 minutos em horário de pico",
        "tempo_retrabalho_horas": 18,
        "licoes_aprendidas": (
            "Sempre validar tamanho de payload com sistemas legados antes do deploy. "
            "Incluir teste de carga com cenários de integração no plano de homologação."
        )
    },
    {
        "gmud_id": "CHG0070891",
        "data": "2026-06-22",
        "sistemas_afetados": ["Módulo PIX", "Anti-Fraude"],
        "causa_raiz": (
            "Regra de anti-fraude bloqueou transações PIX legítimas após atualização "
            "dos thresholds. O modelo de ML foi retreinado mas os novos limites não "
            "foram validados com dados de produção."
        ),
        "categoria_falha": "config",
        "impacto": "15% das transações PIX rejeitadas indevidamente por 45 minutos",
        "tempo_retrabalho_horas": 8,
        "licoes_aprendidas": (
            "Validar mudanças em regras de fraude com shadow mode antes de ativar. "
            "Incluir cenário de falso-positivo no plano de testes."
        )
    },
    {
        "gmud_id": "CHG0069555",
        "data": "2026-05-03",
        "sistemas_afetados": ["Módulo Empréstimos", "Database Oracle", "Batch Noturno"],
        "causa_raiz": (
            "Script de migração DDL não considerou constraint de FK com tabela de clientes. "
            "O ALTER TABLE travou esperando lock exclusivo por 20 minutos e estourou timeout."
        ),
        "categoria_falha": "dados",
        "impacto": "Batch noturno de empréstimos não executou, atraso de 6h na conciliação",
        "tempo_retrabalho_horas": 24,
        "licoes_aprendidas": (
            "Executar migrations com pt-online-schema-change em tabelas grandes. "
            "Testar script DDL em ambiente com volume de dados similar à produção."
        )
    },
    {
        "gmud_id": "CHG0068200",
        "data": "2026-03-15",
        "sistemas_afetados": ["Onboarding Digital", "Integração SERPRO", "API Gateway"],
        "causa_raiz": (
            "Atualização da lib de HTTP client quebrou compatibilidade com certificado "
            "mTLS do SERPRO. Conexões passaram a ser recusadas com erro SSL handshake."
        ),
        "categoria_falha": "integracao",
        "impacto": "Abertura de contas digitais indisponível por 2 horas",
        "tempo_retrabalho_horas": 12,
        "licoes_aprendidas": (
            "Manter testes de integração com certificados reais (não mocks) no pipeline. "
            "Validar compatibilidade de libs HTTP com mTLS em ambiente de staging."
        )
    },
    {
        "gmud_id": "CHG0067800",
        "data": "2026-02-28",
        "sistemas_afetados": ["Core Banking", "API Gateway", "Cache Redis"],
        "causa_raiz": (
            "Nova versão da API consumia 3x mais memória no Redis por conta de mudança "
            "no formato de serialização. Cluster Redis atingiu 95% de memória e começou "
            "a fazer eviction de chaves ativas."
        ),
        "categoria_falha": "performance",
        "impacto": "Degradação de performance em todas as APIs por 30 minutos",
        "tempo_retrabalho_horas": 6,
        "licoes_aprendidas": (
            "Incluir análise de consumo de memória/cache no plano de testes. "
            "Monitorar Redis durante deploy progressivo (canary)."
        )
    },
]


def lambda_handler(event, context):
    """Handler principal da Lambda."""

    if isinstance(event, str):
        event = json.loads(event)

    body = event.get("body", event)
    if isinstance(body, str):
        body = json.loads(body)

    sistemas = body.get("sistemas", [])
    periodo_meses = body.get("periodo_meses", 12)
    limit = body.get("limit", 10)

    if not sistemas:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "sistemas é obrigatório (lista de sistemas afetados)"})
        }

    # Filtrar rollbacks que envolvem pelo menos um dos sistemas informados
    sistemas_lower = [s.lower() for s in sistemas]
    resultados = []

    for rollback in MOCK_ROLLBACKS:
        rollback_sistemas_lower = [s.lower() for s in rollback["sistemas_afetados"]]
        # Match se algum sistema da busca aparece nos sistemas do rollback
        if any(s in rs for s in sistemas_lower for rs in rollback_sistemas_lower):
            resultados.append(rollback)

    # Aplicar limit
    resultados = resultados[:limit]

    response = {
        "total_encontrados": len(resultados),
        "rollbacks": resultados
    }

    return {
        "statusCode": 200,
        "body": json.dumps(response, ensure_ascii=False)
    }


# Para teste local
if __name__ == "__main__":
    test_event = {"sistemas": ["Módulo PIX", "API Gateway"]}
    result = lambda_handler(test_event, None)
    print(json.dumps(json.loads(result["body"]), indent=2, ensure_ascii=False))
