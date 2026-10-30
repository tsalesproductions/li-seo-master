import sys
import logging
from tqdm import tqdm
from li_client import LojaIntegradaClient
from gpt_generator import GPTGenerator
import db

# Garante compatibilidade UTF-8 no terminal Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ProcessSKUs")

SKUS_LIST = [
    "SHXO-101", "SHPL-025", "SHP4-062", "SHP4-040", "SHXO-100",
    "SHXO-096", "SHPL-005", "SHX3-631", "SHXO-111", "SHP3-348",
    "SHPL-022", "SHXO-108", "SHPL-024", "SHP3-414", "SHPL-016",
    "SHPL-036", "SHXO-059", "SHP4-047", "SHXO-148", "SHXO-154",
    "SHP4-135", "SHP4-173", "SHP4-161", "SHXO-1016", "SHXO-1017",
    "SHXO-1018", "SHP4-1052", "SHXO-1033", "SHP4-1055", "SHP4-1094",
    "SHP4-1098", "SHP3-1103", "SHP4-1109", "SHP4-1110", "SHXO-1093",
    "SHXO-1101", "SHPL-1007", "SHPL-1004", "SHPL-1002", "SHPL-1017",
    "SHPL-1029", "SHPL-1031", "SHPL-008", "SHP4-1194", "SHXO-1145",
    "SHXO-043", "SHP4-1225", "SHP4-1234", "SHP4-1249", "SHXO-1162"
]


def is_eligible_for_sale(product_detail: dict) -> tuple[bool, str]:
    """
    Valida se o produto está realmente ativo e disponível para venda com estoque.
    """
    if product_detail.get("removido", False):
        return False, "Produto removido/excluído"

    if product_detail.get("bloqueado", False):
        return False, "Produto bloqueado"

    if not product_detail.get("ativo", False):
        return False, "Produto desativado na loja"

    # Verificação de estoque
    is_managed = product_detail.get("estoque_gerenciado", False)
    stock_qty = product_detail.get("estoque_quantidade")
    
    if is_managed:
        if stock_qty is None or float(stock_qty) <= 0:
            return False, f"Sem estoque (qtd: {stock_qty or 0})"

    return True, "Disponível para venda"


def process():
    # 1. Limpa todos os produtos anteriores no banco de dados local
    logger.info("Limpando produtos anteriores do banco de dados local SQLite...")
    db.clear_all_products()

    li = LojaIntegradaClient()
    gpt = GPTGenerator()

    total_skus = len(SKUS_LIST)
    print("\n" + "=" * 70)
    print(f"🔍 ANALISANDO E FILTRANDO {total_skus} SKUS (APENAS ATIVOS E COM ESTOQUE)")
    print("=" * 70)

    eligible_products = []
    skipped_products = []

    # Passo 1: Varredura rápida de elegibilidade na LI
    print("Passo 1/2: Validando status e estoque de cada produto...")
    for sku in tqdm(SKUS_LIST, desc="Checando Loja Integrada"):
        try:
            res = li._request_with_retry("GET", "/produto/", params={"sku": sku})
            data = res.json()
            objects = data.get("objects", [])

            if not objects:
                skipped_products.append((sku, "Não encontrado na Loja Integrada"))
                continue

            summary = objects[0]
            prod_id = summary.get("id")

            # Busca detalhes completos do produto para conferir estoque e flags
            full_prod = li.get_product(prod_id)
            eligible, reason = is_eligible_for_sale(full_prod)

            if not eligible:
                skipped_products.append((sku, f"{reason} - '{full_prod.get('nome')[:28]}'"))
                continue

            # Busca SEO atual se houver
            seo_uri = full_prod.get("seo")
            seo_data = None
            if seo_uri and isinstance(seo_uri, str):
                seo_data = li.get_seo_detail(seo_uri)

            eligible_products.append((full_prod, seo_data))

        except Exception as e:
            logger.error(f"Erro ao consultar SKU {sku}: {e}")
            skipped_products.append((sku, f"Erro na API: {e}"))

    print("\n" + "-" * 70)
    print(f"📊 RESULTADO DA FILTRAGEM PRÉVIA:")
    print(f"• Produtos Elegíveis (Ativos e com Estoque): {len(eligible_products)}")
    print(f"• Produtos Descartados (Desativados/Sem Estoque): {len(skipped_products)}")
    print("-" * 70)

    if skipped_products:
        print("Motivos dos descartes:")
        for sku, reason in skipped_products:
            print(f"  ❌ {sku}: {reason}")
        print("-" * 70)

    if not eligible_products:
        print("Nenhum produto da lista está ativo e com estoque no momento.")
        return

    # Passo 2: Geração com IA apenas para os produtos válidos
    print(f"\nPasso 2/2: Gerando SEO e Copywriting com IA para {len(eligible_products)} produtos ativos...")
    success_count = 0

    for full_prod, seo_data in tqdm(eligible_products, desc="Gerando com IA"):
        prod_id = full_prod.get("id")
        sku = full_prod.get("sku", "")
        nome = full_prod.get("nome", "")

        try:
            # Salva produto no SQLite
            db.upsert_product_from_li(full_prod, seo_data)

            # Gera com IA
            generated = gpt.generate_seo_and_copy(full_prod)

            # Salva sugestão com status PENDENTE para revisão no painel
            db.update_product_suggestion(
                product_id=prod_id,
                seo_title=generated.get("seo_title", ""),
                seo_desc=generated.get("seo_description", ""),
                seo_keywords=generated.get("seo_keywords", ""),
                descricao_html=generated.get("descricao_completa_html", ""),
                status="PENDENTE",
            )
            success_count += 1
            logger.info(f"✅ SKU {sku} (#{prod_id}) - '{nome[:30]}' gerado com sucesso!")

        except Exception as e:
            logger.error(f"❌ Erro ao gerar com GPT para SKU {sku}: {e}")

    print("\n" + "=" * 70)
    print("🎉 PROCESSAMENTO CONCLUÍDO COM SUCESSO!")
    print(f"✅ {success_count} produtos ativos foram gerados e estão prontos para aprovação no painel.")
    print("👉 Acesse o Dashboard para revisar e aprovar: http://localhost:5000")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    process()
