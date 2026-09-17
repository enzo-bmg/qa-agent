"""
Lambda mock: get_score_info
Calcula score de risco de uma GMUD baseado em fatores.
Em produção, usará dados reais do histórico + ML model.
"""

import json

# Mock: dados internos que a função usa pra calcular score
SISTEMA_CRITICIDADE = {
    "core banking": 0.9,
    "módulo pix": 0.85,
    "api gateway": 0.7,
    "anti-fraude": 0.8,
    "módulo empréstimos": 0.75,
    "database oracle": 0.85,
    "batch noturno": 0.6,
    "onboarding digital": 0.7,
    "integração serpro": 0.65,
    "cache redis": 0.5,
    "bi/analytics": 0.3,
}

HISTORICO_ROLLBACKS_POR_SISTEMA = {
    "core banking": 3,
    "módulo pix": 4,
    "api gateway": 5,
    "anti-fraude": 2,
    "módulo empréstimos": 2,
    "database oracle": 3,
    "batch noturno": 1,
    "onboarding digital": 2,
    "integração serpro": 3,
    "cache redis": 1,
    "bi/analytics": 0,
}


def calcular_score(gmud_id, sistemas_afetados):
    """Calcula score de risco com base em fatores ponderados."""

    fatores = []

    # Fator 1: Criticidade dos sistemas (peso 30%)
    if sistemas_afetados:
        criticidades = [
            SISTEMA_CRITICIDADE.get(s.lower(), 0.5)
            for s in sistemas_afetados
        ]
        max_criticidade = max(criticidades)
        contribuicao = max_criticidade * 30
        fatores.append({
            "fator": "Criticidade máxima dos sistemas afetados",
            "peso": 0.30,
            "valor": f"{max_criticidade:.2f} (sistema mais crítico)",
            "contribuicao_score": round(contribuicao, 1)
        })
    else:
        contribuicao = 15  # default médio
        fatores.append({
            "fator": "Criticidade dos sistemas",
            "peso": 0.30,
            "valor": "Desconhecido (sistemas não informados)",
            "contribuicao_score": contribuicao
        })

    # Fator 2: Quantidade de sistemas afetados (peso 20%)
    qtd_sistemas = len(sistemas_afetados) if sistemas_afetados else 1
    contribuicao_qtd = min(qtd_sistemas / 5, 1.0) * 20
    fatores.append({
        "fator": "Quantidade de sistemas afetados",
        "peso": 0.20,
        "valor": f"{qtd_sistemas} sistemas",
        "contribuicao_score": round(contribuicao_qtd, 1)
    })

    # Fator 3: Histórico de rollbacks nos sistemas (peso 30%)
    if sistemas_afetados:
        total_rollbacks = sum(
            HISTORICO_ROLLBACKS_POR_SISTEMA.get(s.lower(), 0)
            for s in sistemas_afetados
        )
        contribuicao_hist = min(total_rollbacks / 10, 1.0) * 30
        fatores.append({
            "fator": "Histórico de rollbacks nos sistemas afetados (últimos 12 meses)",
            "peso": 0.30,
            "valor": f"{total_rollbacks} rollbacks anteriores",
            "contribuicao_score": round(contribuicao_hist, 1)
        })
    else:
        contribuicao_hist = 15
        fatores.append({
            "fator": "Histórico de rollbacks",
            "peso": 0.30,
            "valor": "Desconhecido",
            "contribuicao_score": contribuicao_hist
        })

    # Fator 4: Tipo de mudança inferido (peso 20%)
    # Em produção, viria do ServiceNow. Aqui assume "normal"
    contribuicao_tipo = 10  # normal = médio
    fatores.append({
        "fator": "Complexidade estimada da mudança",
        "peso": 0.20,
        "valor": "Média (baseado em heurística)",
        "contribuicao_score": contribuicao_tipo
    })

    # Score total
    score_total = sum(f["contribuicao_score"] for f in fatores)
    score_total = min(round(score_total, 1), 100)

    # Classificação
    if score_total >= 75:
        nivel = "critico"
        recomendacao = (
            "GMUD de alto risco. Recomenda-se: testes de integração completos, "
            "teste de carga, plano de rollback detalhado com dry-run, "
            "monitoramento ativo durante execução e war room."
        )
    elif score_total >= 50:
        nivel = "alto"
        recomendacao = (
            "GMUD com risco elevado. Recomenda-se: testes de regressão ampliados, "
            "validação do plano de rollback, deploy progressivo (canary) e "
            "monitoramento durante a janela."
        )
    elif score_total >= 30:
        nivel = "medio"
        recomendacao = (
            "GMUD com risco moderado. Recomenda-se: testes funcionais padrão, "
            "smoke test pós-deploy e monitoramento por 30 minutos."
        )
    else:
        nivel = "baixo"
        recomendacao = (
            "GMUD de baixo risco. Testes funcionais básicos e smoke test "
            "pós-deploy são suficientes."
        )

    return {
        "gmud_id": gmud_id,
        "score_risco": score_total,
        "nivel_risco": nivel,
        "fatores": fatores,
        "recomendacao": recomendacao
    }


def lambda_handler(event, context):
    """Handler principal da Lambda."""

    if isinstance(event, str):
        event = json.loads(event)

    body = event.get("body", event)
    if isinstance(body, str):
        body = json.loads(body)

    gmud_id = body.get("gmud_id")
    sistemas_afetados = body.get("sistemas_afetados", [])

    if not gmud_id:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "gmud_id é obrigatório"})
        }

    resultado = calcular_score(gmud_id, sistemas_afetados)

    return {
        "statusCode": 200,
        "body": json.dumps(resultado, ensure_ascii=False)
    }


# Para teste local
if __name__ == "__main__":
    test_event = {
        "gmud_id": "CHG0074521",
        "sistemas_afetados": ["API Gateway", "Core Banking", "Módulo PIX", "Anti-Fraude"]
    }
    result = lambda_handler(test_event, None)
    print(json.dumps(json.loads(result["body"]), indent=2, ensure_ascii=False))
