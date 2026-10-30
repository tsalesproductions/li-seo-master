import argparse
import sys
import json
import logging
from pathlib import Path

# Garante compatibilidade UTF-8 no terminal Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Verifica dependências básicas
missing_deps = []
for pkg in ["requests", "openai", "pandas", "openpyxl", "flask"]:
    try:
        __import__(pkg)
    except ImportError:
        missing_deps.append(pkg)

if missing_deps:
    print("\n" + "!" * 60)
    print("⚠️  ATENÇÃO: Dependências necessárias não encontradas!")
    print(f"Faltam os pacotes: {', '.join(missing_deps)}")
    print("Para instalar tudo com um único comando, execute:")
    print("    pip install -r requirements.txt")
    print("!" * 60 + "\n")
    sys.exit(1)

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, desc=None, **kwargs):
        if desc:
            print(f">>> {desc}...")
        return iterable

from config import (
    validate_config,
    PRODUCT_LIMIT,
    ONLY_MISSING_SEO_OR_DESC,
    ONLY_ACTIVE_PRODUCTS,
    UPDATE_SEO_TITLE,
    UPDATE_SEO_DESCRIPTION,
    UPDATE_SEO_KEYWORDS,
    UPDATE_DESCRIPTION_HTML,
    DRY_RUN,
    OUTPUT_DIR,
)
import db
from li_client import LojaIntegradaClient
from gpt_generator import GPTGenerator
from storage import StorageManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Main")


def run_scan():
    """Varre a loja e sincroniza com o banco local SQLite, exibindo diagnóstico detalhado."""
    validate_config(require_openai=False, require_li=True)
    li = LojaIntegradaClient()

    logger.info("Executando escaneamento e sincronização com o banco local SQLite...")
    synced = li.sync_catalog_to_sqlite(
        max_products=PRODUCT_LIMIT,
        only_active=ONLY_ACTIVE_PRODUCTS,
        only_missing_seo=False,
    )

    stats = db.get_stats()
    products = db.list_products(limit=15)

    print("\n" + "=" * 65)
    print("📊 DIAGNÓSTICO DO CATÁLOGO (LOJA INTEGRADA)")
    print("=" * 65)
    print(f"• Total de Produtos no Banco Local: {stats['total']}")
    print(f"• Produtos Sem SEO na Loja Integrada: {stats['sem_seo']}")
    print(f"• Produtos Pendentes de Revisão: {stats['pendentes']}")
    print(f"• Produtos Aprovados: {stats['aprovados']}")
    print(f"• Produtos Já Publicados: {stats['publicados']}")
    print("-" * 65)

    for p in products:
        has_seo = bool(p.get("has_seo"))
        has_desc = bool(p.get("has_description"))
        print(f"• ID: {p.get('id'):<9} | SKU: {p.get('sku', ''):<10} | {p.get('nome')[:35]:<35}")
        print(f"  SEO: {'✅ PREENCHIDO' if has_seo else '❌ AUSENTE'} | Descrição: {'✅ PREENCHIDO' if has_desc else '❌ AUSENTE'}")

    print("=" * 65)
    print("\n💡 Como prosseguir:")
    print("1. Para usar o Dashboard Visual com SQLite (Recomendado):")
    print("   python main.py --mode web")
    print("   ou: python app.py")
    print("2. Para gerar sugestões em lote via terminal:")
    print("   python main.py --mode generate")
    print("=" * 65 + "\n")


def run_generate(limit: int = None, all_products: bool = False):
    """Gera sugestões de SEO e Descrição com IA para os produtos pendentes no SQLite."""
    validate_config(require_openai=True, require_li=True)
    gpt = GPTGenerator()

    stats = db.get_stats()
    print("\n" + "=" * 65)
    print("🤖 GERAÇÃO DE SEO & COPYWRITING COM IA")
    print("=" * 65)
    print(f"• Total de Produtos no Banco: {stats.get('total', 0)}")
    print(f"• Já Gerados com IA: {stats.get('com_ia', 0)}")
    print(f"• Pendentes de Geração (sem IA): {stats.get('sem_ia', 0)}")
    print("-" * 65)

    target_limit = 5000 if all_products or (limit == 0) else (limit if limit is not None else (PRODUCT_LIMIT if PRODUCT_LIMIT > 0 else 50))

    # Busca produtos pendentes que ainda NÃO foram gerados com IA
    candidates = db.list_products(status="PENDENTE", ai_status="NAO_GERADO", limit=target_limit)
    if not candidates:
        candidates = db.list_products(ai_status="NAO_GERADO", limit=target_limit)

    if not candidates:
        logger.info("Nenhum produto sem IA encontrado no banco local.")
        logger.info("Todos os produtos cadastrados já possuem sugestões de IA!")
        logger.info("Abra o dashboard ('python main.py --mode web') para revisar ou publique com '--mode publish'.")
        return

    logger.info(f"Iniciando geração com IA para lote de {len(candidates)} produtos...")
    for prod in tqdm(candidates, desc="Processando com GPT"):
        prod_id = prod["id"]
        try:
            generated = gpt.generate_seo_and_copy(prod)
            db.update_product_suggestion(
                product_id=prod_id,
                seo_title=generated.get("seo_title", ""),
                seo_desc=generated.get("seo_description", ""),
                seo_keywords=generated.get("seo_keywords", ""),
                descricao_html=generated.get("descricao_completa_html", ""),
                status="APROVADO",
            )
        except Exception as e:
            logger.error(f"Erro ao processar produto #{prod_id}: {e}")

    updated_stats = db.get_stats()
    print("\n" + "=" * 65)
    print(f"✅ GERAÇÃO CONCLUÍDA! {len(candidates)} produtos processados.")
    print(f"• Total com IA no banco agora: {updated_stats.get('com_ia', 0)}")
    print(f"• Restantes sem IA: {updated_stats.get('sem_ia', 0)}")
    print("-" * 65)
    print("💡 Como prosseguir:")
    print("1. Para revisar no Dashboard Web:")
    print("   python main.py --mode web")
    print("   (Dica: no painel use o filtro 'Gerados pela IA' ou 'Aprovados')")
    print("2. Para gerar o próximo lote de produtos:")
    print("   python main.py --mode generate --limit 50")
    print("   (ou use '--all' para gerar todos de uma vez)")
    print("3. Para publicar na Loja Integrada:")
    print("   python main.py --mode publish")
    print("=" * 65 + "\n")


def run_publish():
    """Publica todos os produtos aprovados no SQLite para a Loja Integrada."""
    validate_config(require_openai=False, require_li=True)
    li = LojaIntegradaClient()

    approved = db.list_products(status="APROVADO", limit=500)
    if not approved:
        logger.warning("Nenhum produto marcado como 'APROVADO' no banco local.")
        return

    logger.info(f"Total de {len(approved)} produtos aprovados para publicação.")

    # Backup de segurança
    logger.info("Criando snapshot de backup dos produtos originais...")
    backup_list = []
    for p in tqdm(approved, desc="Coletando produtos para backup"):
        try:
            backup_list.append(li.get_product(p["id"]))
        except Exception as e:
            logger.warning(f"Erro ao obter backup do produto {p['id']}: {e}")

    if backup_list:
        backup_path = StorageManager.create_safety_backup(backup_list)
        logger.info(f"🛡️ Backup de segurança salvo em: {backup_path}")

    if DRY_RUN:
        logger.info("⚠️ DRY_RUN ativado: Nenhuma alteração foi enviada para a Loja Integrada.")
        return

    success_count = 0
    fail_count = 0

    for prod in tqdm(approved, desc="Publicando na Loja Integrada"):
        prod_id = prod["id"]
        try:
            # 1. Atualiza Descrição Completa
            desc = prod.get("descricao_sugerida_html") or prod.get("descricao_atual")
            if UPDATE_DESCRIPTION_HTML and desc:
                li.update_product_description(prod_id, desc)

            # 2. Atualiza ou Cria SEO
            seo_res = li.update_or_create_seo(
                product_id=prod_id,
                seo_id=prod.get("seo_id"),
                title=prod.get("seo_title_sugerido") or prod.get("seo_title_atual") or "",
                description=prod.get("seo_desc_sugerido") or prod.get("seo_desc_atual") or "",
                keyword=prod.get("seo_keywords_sugerido") or prod.get("seo_keywords_atual") or "",
            )

            new_seo_id = seo_res.get("id") or prod.get("seo_id")
            new_seo_uri = seo_res.get("resource_uri") or prod.get("seo_uri")
            db.mark_as_published(prod_id, seo_id=new_seo_id, seo_uri=new_seo_uri)
            success_count += 1
        except Exception as e:
            logger.error(f"Erro ao publicar produto #{prod_id}: {e}")
            fail_count += 1

    print("\n" + "=" * 60)
    print(f"🚀 ATUALIZAÇÃO CONCLUÍDA!")
    print(f"✅ Sucesso: {success_count} produtos atualizados na Loja Integrada")
    if fail_count > 0:
        print(f"❌ Falhas: {fail_count} produtos com erro")
    print("=" * 60 + "\n")


def run_web():
    """Inicia o Dashboard Web local com SQLite."""
    from app import app
    print("\n" + "=" * 65)
    print("🚀 LI SEO & Copy Master - Dashboard Web Iniciado!")
    print("👉 Acesse no seu navegador: http://localhost:5000")
    print("=" * 65 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=False)


def main():
    parser = argparse.ArgumentParser(
        description="Otimizador de SEO e Descrições de Alta Conversão para Loja Integrada com IA e SQLite"
    )
    parser.add_argument(
        "--mode",
        choices=["scan", "generate", "publish", "web"],
        default="web",
        help="Modo de operação: web (inicia Dashboard Web), scan (sincroniza e diagnostica), generate (processa pendentes), publish (publica aprovados)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Quantidade de produtos a processar no modo generate ou scan (0 para todos)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Processa todos os produtos pendentes sem limite de quantidade",
    )

    args = parser.parse_args()

    if args.mode == "scan":
        run_scan()
    elif args.mode == "generate":
        run_generate(limit=args.limit, all_products=args.all)
    elif args.mode == "publish":
        run_publish()
    elif args.mode == "web":
        run_web()


if __name__ == "__main__":
    main()
