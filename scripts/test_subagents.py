"""
Testa os SubAgents isoladamente.

Modo 1 (sem LLM): valida que os inputs estão corretos e prontos pra chamar o LLM
Modo 2 (com LLM): roda de verdade e mostra o output

Uso:
    cd ~/Documentos/Projetos/BMG/BMGQAAgent
    
    # Modo dry-run (sem LLM — valida inputs)
    python scripts/test_subagents.py --dry-run
    
    # Modo real (precisa de credenciais Bedrock)
    python scripts/test_subagents.py
"""

import json
import sys
import argparse
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "app" / "BMGQAAgent"))
sys.path.insert(0, str(PROJECT_ROOT / "lambdas"))


def get_test_inputs():
    """Prepara inputs de teste usando os mocks locais."""
    from get_gmud_metadata.handler import lambda_handler as gmud_handler
    from get_rollback_history.handler import lambda_handler as rollback_handler
    from get_score_info.handler import lambda_handler as score_handler

    # 1. GMUD metadata
    gmud_result = gmud_handler({"gmud_id": "CHG0074521"}, None)
    gmud_metadata = json.loads(gmud_result["body"])

    # 2. Rollback history
    sistemas = gmud_metadata["sistemas_afetados"]
    rollback_result = rollback_handler({"sistemas": sistemas}, None)
    rollback_data = json.loads(rollback_result["body"])

    # 3. Score
    score_result = score_handler({
        "gmud_id": "CHG0074521",
        "sistemas_afetados": sistemas
    }, None)
    score_info = json.loads(score_result["body"])

    # 4. KB context (simula retrieve)
    kb_context = """
Sistema: Módulo PIX
Criticidade: Alta (regulatório BACEN + volume financeiro)
Integrações: Core Banking (REST, síncrono), Anti-Fraude (REST, timeout 50ms), 
SPI/BACEN (ISO 20022, mTLS), Cache Redis (cluster pix-prod, 3 nós).
Pontos críticos: SLA BACEN <10s, Anti-Fraude síncrono, Redis SPOF para cache de chaves.
Histórico: 4 rollbacks nos últimos 12 meses, principal causa: integração com legados.
"""

    return gmud_metadata, rollback_data, score_info, kb_context


def test_dry_run():
    """Valida que os inputs estão prontos (sem chamar LLM)."""
    print("=" * 60)
    print("🧪 Teste DRY-RUN (validação de inputs)")
    print("=" * 60)

    gmud_metadata, rollback_data, score_info, kb_context = get_test_inputs()

    print("\n1️⃣  GMUD Metadata:")
    print(f"   ID: {gmud_metadata['gmud_id']}")
    print(f"   Título: {gmud_metadata['titulo']}")
    print(f"   Sistemas: {gmud_metadata['sistemas_afetados']}")
    print(f"   Tipo: {gmud_metadata['tipo_mudanca']}")

    print("\n2️⃣  Rollback History:")
    print(f"   Total: {rollback_data['total_encontrados']} rollbacks")
    for rb in rollback_data['rollbacks'][:3]:
        print(f"   • {rb['gmud_id']} ({rb['categoria_falha']}): {rb['causa_raiz'][:60]}...")

    print("\n3️⃣  Score de Risco:")
    print(f"   Score: {score_info['score_risco']}/100 ({score_info['nivel_risco']})")
    print(f"   Recomendação: {score_info['recomendacao'][:80]}...")

    print("\n4️⃣  KB Context:")
    print(f"   {kb_context.strip()[:200]}...")

    print("\n" + "=" * 60)
    print("✅ Todos os inputs prontos para os SubAgents!")
    print()
    print("   SubAgent Code Analysis receberá:")
    print(f"     - gmud_metadata ({len(json.dumps(gmud_metadata))} chars)")
    print(f"     - kb_context ({len(kb_context)} chars)")
    print()
    print("   SubAgent Test Scenarios Gen receberá:")
    print(f"     - gmud_metadata ({len(json.dumps(gmud_metadata))} chars)")
    print(f"     - code_analysis (output do Code Analysis)")
    print(f"     - rollback_history ({len(json.dumps(rollback_data))} chars)")
    print(f"     - score_info ({len(json.dumps(score_info))} chars)")
    print("=" * 60)


def test_with_llm():
    """Roda os SubAgents de verdade (precisa de Bedrock)."""
    print("=" * 60)
    print("🚀 Teste REAL (com LLM)")
    print("=" * 60)

    try:
        from subagents import run_code_analysis, run_test_scenarios_gen
        from model.load import load_model
    except ImportError as e:
        print(f"❌ Erro de import: {e}")
        print("   Verifique se as dependências estão instaladas (strands-agents, bedrock-agentcore)")
        return

    try:
        model = load_model()
    except Exception as e:
        print(f"❌ Erro ao carregar modelo: {e}")
        print("   Provavelmente faltam credenciais AWS/Bedrock.")
        print("   Use --dry-run pra testar sem LLM.")
        return

    gmud_metadata, rollback_data, score_info, kb_context = get_test_inputs()

    # 1. Code Analysis
    print("\n🔍 Rodando SubAgent Code Analysis...")
    code_analysis = run_code_analysis(model, gmud_metadata, kb_context)

    if code_analysis.get("parse_error"):
        print("   ⚠️  Não conseguiu parsear JSON. Resposta raw:")
        print(f"   {code_analysis.get('raw_response', '')[:500]}")
    else:
        print("   ✅ Análise gerada!")
        print(f"   Componentes: {len(code_analysis.get('componentes_tocados', []))}")
        print(f"   Pontos de atenção: {len(code_analysis.get('pontos_atencao', []))}")
        print(f"   Resumo: {code_analysis.get('resumo_executivo', 'N/A')[:100]}")

    # 2. Test Scenarios Gen
    print("\n📋 Rodando SubAgent Test Scenarios Gen...")
    scenarios = run_test_scenarios_gen(
        model, gmud_metadata, code_analysis, rollback_data["rollbacks"], score_info
    )

    if scenarios.get("parse_error"):
        print("   ⚠️  Não conseguiu parsear JSON. Resposta raw:")
        print(f"   {scenarios.get('raw_response', '')[:500]}")
    else:
        print("   ✅ Cenários gerados!")
        print(f"   Total: {scenarios.get('total_cenarios', 'N/A')}")
        for ct in scenarios.get("cenarios", [])[:5]:
            print(f"   • {ct.get('id', '?')} [{ct.get('prioridade', '?')}] {ct.get('titulo', '?')}")

    # Salvar outputs
    output_dir = PROJECT_ROOT / "test_outputs"
    output_dir.mkdir(exist_ok=True)

    with open(output_dir / "code_analysis.json", "w") as f:
        json.dump(code_analysis, f, indent=2, ensure_ascii=False)

    with open(output_dir / "test_scenarios.json", "w") as f:
        json.dump(scenarios, f, indent=2, ensure_ascii=False)

    print(f"\n💾 Outputs salvos em: {output_dir}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Testa SubAgents do QA Agent BMG")
    parser.add_argument("--dry-run", action="store_true", help="Valida inputs sem chamar LLM")
    args = parser.parse_args()

    if args.dry_run:
        test_dry_run()
    else:
        test_with_llm()
