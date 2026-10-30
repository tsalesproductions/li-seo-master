import sys
import logging
import time
from flask import Flask, render_template, request, jsonify

# Garante compatibilidade UTF-8 no Windows
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

from config import (
    UPDATE_SEO_TITLE,
    UPDATE_SEO_DESCRIPTION,
    UPDATE_SEO_KEYWORDS,
    UPDATE_DESCRIPTION_HTML,
    DRY_RUN,
)
import db
from li_client import LojaIntegradaClient
from gpt_generator import GPTGenerator
from storage import StorageManager
from task_manager import task_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AppWeb")

app = Flask(__name__)

li_client = LojaIntegradaClient()
gpt_generator = GPTGenerator()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/stats", methods=["GET"])
def api_stats():
    return jsonify(db.get_stats())


@app.route("/api/task-status", methods=["GET"])
def api_task_status():
    """Retorna o status atual da tarefa em segundo plano."""
    return jsonify(task_manager.get_state())


@app.route("/api/task-cancel", methods=["POST"])
def api_task_cancel():
    """Solicita o cancelamento da tarefa em segundo plano."""
    task_manager.request_cancel()
    return jsonify({"ok": True})


@app.route("/api/products", methods=["GET"])
def api_products():
    status = request.args.get("status", "TODOS")
    ai_status = request.args.get("ai_status", "TODOS")
    seo_status = request.args.get("seo_status", "TODOS")
    search = request.args.get("search", "").strip()

    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1

    try:
        limit = max(1, min(500, int(request.args.get("limit", 50))))
    except (ValueError, TypeError):
        limit = 50

    offset = (page - 1) * limit

    # Retrocompatibilidade com status="SEM_SEO"
    if status == "SEM_SEO":
        seo_status = "SEM_SEO"
        status = "TODOS"

    filter_status = None if status == "TODOS" else status
    filter_ai = None if ai_status == "TODOS" else ai_status
    filter_seo = None if seo_status == "TODOS" else seo_status
    filter_search = search if search else None

    total = db.count_products(
        status=filter_status,
        search=filter_search,
        ai_status=filter_ai,
        seo_status=filter_seo,
    )

    products = db.list_products(
        status=filter_status,
        search=filter_search,
        ai_status=filter_ai,
        seo_status=filter_seo,
        limit=limit,
        offset=offset,
    )

    total_pages = max(1, (total + limit - 1) // limit)

    return jsonify({
        "products": products,
        "total": total,
        "page": page,
        "pages": total_pages,
        "limit": limit,
    })


@app.route("/api/products/<int:product_id>", methods=["GET"])
def api_get_product(product_id):
    product = db.get_product(product_id)
    if not product:
        return jsonify({"error": "Produto não encontrado"}), 404
    return jsonify(product)


@app.route("/api/products/<int:product_id>/save", methods=["POST"])
def api_save_product(product_id):
    data = request.json or {}
    seo_title = data.get("seo_title_sugerido", "")
    seo_desc = data.get("seo_desc_sugerido", "")
    seo_keywords = data.get("seo_keywords_sugerido", "")
    descricao_html = data.get("descricao_sugerida_html", "")
    status = data.get("status_aprovacao", "APROVADO")

    db.update_product_suggestion(
        product_id=product_id,
        seo_title=seo_title,
        seo_desc=seo_desc,
        seo_keywords=seo_keywords,
        descricao_html=descricao_html,
        status=status,
    )
    return jsonify({"ok": True})


@app.route("/api/products/<int:product_id>/generate", methods=["POST"])
def api_generate_product(product_id):
    product = db.get_product(product_id)
    if not product:
        return jsonify({"ok": False, "error": "Produto não encontrado"}), 404

    try:
        generated = gpt_generator.generate_seo_and_copy(product)
        db.update_product_suggestion(
            product_id=product_id,
            seo_title=generated.get("seo_title", ""),
            seo_desc=generated.get("seo_description", ""),
            seo_keywords=generated.get("seo_keywords", ""),
            descricao_html=generated.get("descricao_completa_html", ""),
            status="PENDENTE",
        )
        return jsonify({"ok": True, "generated": generated})
    except Exception as e:
        logger.error(f"Erro ao gerar com IA para o produto #{product_id}: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/products/<int:product_id>/publish", methods=["POST"])
def api_publish_product(product_id):
    product = db.get_product(product_id)
    if not product:
        return jsonify({"ok": False, "error": "Produto não encontrado"}), 404

    try:
        # 1. Faz backup de segurança do produto original antes de alterar
        full_original = li_client.get_product(product_id)
        StorageManager.create_safety_backup([full_original])

        if DRY_RUN:
            logger.info("Modo DRY_RUN ativado: simulação de publicação.")
            db.mark_as_published(product_id)
            return jsonify({"ok": True, "dry_run": True})

        # 2. Atualiza Descrição Completa na Loja Integrada
        desc_to_publish = product.get("descricao_sugerida_html") or product.get("descricao_atual")
        if UPDATE_DESCRIPTION_HTML and desc_to_publish:
            li_client.update_product_description(product_id, desc_to_publish)

        # 3. Atualiza ou Cria SEO na Loja Integrada
        seo_title = product.get("seo_title_sugerido") or product.get("seo_title_atual") or ""
        seo_desc = product.get("seo_desc_sugerido") or product.get("seo_desc_atual") or ""
        seo_keywords = product.get("seo_keywords_sugerido") or product.get("seo_keywords_atual") or ""

        seo_res = li_client.update_or_create_seo(
            product_id=product_id,
            seo_id=product.get("seo_id"),
            title=seo_title,
            description=seo_desc,
            keyword=seo_keywords,
        )

        new_seo_id = seo_res.get("id") or product.get("seo_id")
        new_seo_uri = seo_res.get("resource_uri") or product.get("seo_uri")

        # 4. Atualiza estado no banco local SQLite
        db.mark_as_published(product_id, seo_id=new_seo_id, seo_uri=new_seo_uri)

        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"Erro ao publicar produto #{product_id}: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ----------------------------------------------------
# WORKERS DE SEGUNDO PLANO (THREADS)
# ----------------------------------------------------

def _worker_sync(tm, limit: int, only_available: bool):
    def progress_cb(current, total, msg):
        tm.update_progress(current, total, msg)

    tm.update_progress(0, limit, "Conectando à API da Loja Integrada...")
    count = li_client.sync_catalog_to_sqlite(
        max_products=limit,
        only_active=True,
        only_available=only_available,
        only_missing_seo=False,
        stop_event=tm.stop_requested,
        progress_callback=progress_cb,
    )
    tm.update_progress(count, count, f"Sincronização concluída: {count} produtos salvos!")


def _worker_batch_generate(tm, limit: int):
    # Se limit == 0, busca TODOS os produtos elegíveis no banco
    query_limit = 5000 if limit <= 0 else limit
    # Busca apenas produtos que ainda NÃO foram gerados pela IA!
    candidates = db.list_products(status="PENDENTE", ai_status="NAO_GERADO", limit=query_limit)
    if not candidates:
        candidates = db.list_products(ai_status="NAO_GERADO", limit=query_limit)

    total = len(candidates)
    if total == 0:
        tm.update_progress(0, 0, "Nenhum produto pendente para gerar.")
        return

    tm.update_progress(0, total, f"Iniciando geração para {total} produtos...")
    processed = 0

    for i, prod in enumerate(candidates, start=1):
        if tm.stop_requested.is_set():
            tm.update_progress(processed, total, f"Interrompido pelo usuário. {processed} gerados.")
            break

        prod_id = prod["id"]
        nome = prod.get("nome", "")[:25]
        tm.update_progress(processed, total, f"Processando #{prod_id} - '{nome}' ({i}/{total})...")

        try:
            # Respeito a limite de taxa da OpenAI com retry se necessário
            max_openai_retries = 3
            for attempt in range(max_openai_retries):
                try:
                    generated = gpt_generator.generate_seo_and_copy(prod)
                    break
                except Exception as openai_err:
                    if "rate_limit" in str(openai_err).lower() and attempt < max_openai_retries - 1:
                        time.sleep(5 * (attempt + 1))
                        continue
                    raise

            db.update_product_suggestion(
                product_id=prod_id,
                seo_title=generated.get("seo_title", ""),
                seo_desc=generated.get("seo_description", ""),
                seo_keywords=generated.get("seo_keywords", ""),
                descricao_html=generated.get("descricao_completa_html", ""),
                status="PENDENTE",
            )
            processed += 1
            tm.update_progress(processed, total, f"Concluído #{prod_id} ({processed}/{total})")

            # Pausa suave entre chamadas para não estourar TPM/RPM da OpenAI
            time.sleep(0.4)

        except Exception as e:
            logger.error(f"Erro ao processar produto #{prod_id}: {e}")
            tm.add_error(f"#{prod_id}: {str(e)[:60]}")

    tm.update_progress(processed, total, f"Geração finalizada: {processed} de {total} produtos processados!")


def _worker_batch_publish(tm):
    approved = db.list_products(status="APROVADO", limit=5000)
    total = len(approved)

    if total == 0:
        tm.update_progress(0, 0, "Nenhum produto aprovado para publicação.")
        return

    tm.update_progress(0, total, f"Criando backup de segurança para {total} produtos...")

    # Backup coletivo inicial
    backup_list = []
    for p in approved:
        try:
            backup_list.append(li_client.get_product(p["id"]))
        except Exception:
            pass

    if backup_list:
        StorageManager.create_safety_backup(backup_list)

    published = 0
    for i, prod in enumerate(approved, start=1):
        if tm.stop_requested.is_set():
            tm.update_progress(published, total, f"Publicação interrompida: {published} publicados.")
            break

        prod_id = prod["id"]
        nome = prod.get("nome", "")[:25]
        tm.update_progress(published, total, f"Publicando #{prod_id} - '{nome}' na Loja Integrada ({i}/{total})...")

        try:
            if not DRY_RUN:
                # Descrição
                desc = prod.get("descricao_sugerida_html") or prod.get("descricao_atual")
                if UPDATE_DESCRIPTION_HTML and desc:
                    li_client.update_product_description(prod_id, desc)

                # SEO
                seo_res = li_client.update_or_create_seo(
                    product_id=prod_id,
                    seo_id=prod.get("seo_id"),
                    title=prod.get("seo_title_sugerido") or prod.get("seo_title_atual") or "",
                    description=prod.get("seo_desc_sugerido") or prod.get("seo_desc_atual") or "",
                    keyword=prod.get("seo_keywords_sugerido") or prod.get("seo_keywords_atual") or "",
                )
                new_seo_id = seo_res.get("id") or prod.get("seo_id")
                new_seo_uri = seo_res.get("resource_uri") or prod.get("seo_uri")
                db.mark_as_published(prod_id, seo_id=new_seo_id, seo_uri=new_seo_uri)
            else:
                db.mark_as_published(prod_id)

            published += 1
            tm.update_progress(published, total, f"Publicado #{prod_id} na loja ({published}/{total})")

        except Exception as e:
            logger.error(f"Erro ao publicar #{prod_id}: {e}")
            tm.add_error(f"#{prod_id}: {str(e)[:60]}")

    tm.update_progress(published, total, f"Publicação concluída: {published} de {total} produtos atualizados na Loja Integrada!")


# ----------------------------------------------------
# ROTAS DA API
# ----------------------------------------------------

@app.route("/api/sync", methods=["POST"])
def api_sync():
    data = request.json or {}
    limit = int(data.get("limit", 20))
    only_available = bool(data.get("only_available", True))

    started = task_manager.start_task(
        task_type="sync",
        title="Sincronizando Catálogo da Loja Integrada",
        worker_func=_worker_sync,
        limit=limit,
        only_available=only_available,
    )
    if not started:
        return jsonify({"ok": False, "error": "Já existe uma tarefa em execução. Aguarde ou cancele."}), 409

    return jsonify({"ok": True, "message": "Sincronização iniciada em segundo plano!"})


@app.route("/api/batch-generate", methods=["POST"])
def api_batch_generate():
    data = request.json or {}
    limit = int(data.get("limit", 10))

    started = task_manager.start_task(
        task_type="generate",
        title="Gerando SEO e Copywriting com IA",
        worker_func=_worker_batch_generate,
        limit=limit,
    )
    if not started:
        return jsonify({"ok": False, "error": "Já existe uma tarefa em execução. Aguarde ou cancele."}), 409

    return jsonify({"ok": True, "message": "Geração em lote iniciada em segundo plano!"})


@app.route("/api/batch-publish", methods=["POST"])
def api_batch_publish():
    started = task_manager.start_task(
        task_type="publish",
        title="Publicando Produtos Aprovados na Loja Integrada",
        worker_func=_worker_batch_publish,
    )
    if not started:
        return jsonify({"ok": False, "error": "Já existe uma tarefa em execução. Aguarde ou cancele."}), 409

    return jsonify({"ok": True, "message": "Publicação iniciada em segundo plano!"})


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "POST":
        data = request.json or {}
        if "store_name" in data:
            db.set_setting("store_name", data["store_name"].strip())
        if "store_url" in data:
            db.set_setting("store_url", data["store_url"].strip().rstrip("/"))
        if "openai_model" in data:
            db.set_setting("openai_model", data["openai_model"].strip())
        return jsonify({"ok": True})
    return jsonify(db.get_all_settings())


@app.route("/api/clear", methods=["POST"])
def api_clear_database():
    try:
        db.clear_all_products()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🚀 LI SEO & Copy Master - Dashboard Web Iniciado!")
    print("👉 Acesse no seu navegador: http://localhost:5000")
    print("=" * 60 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=False)

