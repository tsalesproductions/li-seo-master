import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
from config import BASE_DIR, STORE_NAME, STORE_URL, OPENAI_MODEL

DB_PATH = BASE_DIR / "database.db"


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Inicializa as tabelas do SQLite se não existirem."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        chave TEXT PRIMARY KEY,
        valor TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS produtos (
        id INTEGER PRIMARY KEY,
        sku TEXT,
        nome TEXT,
        preco TEXT,
        ativo INTEGER DEFAULT 1,
        imagem_url TEXT,
        seo_uri TEXT,
        seo_id INTEGER,
        seo_title_atual TEXT,
        seo_desc_atual TEXT,
        seo_keywords_atual TEXT,
        descricao_atual TEXT,
        seo_title_sugerido TEXT,
        seo_desc_sugerido TEXT,
        seo_keywords_sugerido TEXT,
        descricao_sugerida_html TEXT,
        status_aprovacao TEXT DEFAULT 'PENDENTE', -- PENDENTE, APROVADO, REJEITADO, PUBLICADO
        has_seo INTEGER DEFAULT 0,
        has_description INTEGER DEFAULT 0,
        synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        published_at TIMESTAMP
    )
    """)

    # Popula configurações iniciais se não existirem
    default_settings = {
        "store_name": STORE_NAME,
        "store_url": STORE_URL,
        "openai_model": OPENAI_MODEL,
    }
    for k, v in default_settings.items():
        cursor.execute("INSERT OR IGNORE INTO settings (chave, valor) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()


def clear_all_products():
    """Limpa todos os produtos do banco SQLite local."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM produtos")
    conn.commit()
    conn.close()


def get_setting(key: str, default: str = "") -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT valor FROM settings WHERE chave = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row["valor"] if row else default


def set_setting(key: str, value: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO settings (chave, valor, updated_at) 
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, updated_at = CURRENT_TIMESTAMP
        """,
        (key, value)
    )
    conn.commit()
    conn.close()


def get_all_settings() -> Dict[str, str]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT chave, valor FROM settings")
    rows = cursor.fetchall()
    conn.close()
    return {row["chave"]: row["valor"] for row in rows}


def upsert_product_from_li(product_data: Dict[str, Any], seo_data: Optional[Dict[str, Any]] = None):
    """
    Insere ou atualiza os dados reais vindos da Loja Integrada.
    Preserva as sugestões da IA se o produto já existir e tiver sido editado.
    """
    prod_id = product_data.get("id")
    sku = product_data.get("sku", "")
    nome = product_data.get("nome", "")
    ativo = 1 if product_data.get("ativo", True) else 0
    preco = str(product_data.get("preco_cheio") or product_data.get("preco_promocional") or "")
    descricao_atual = product_data.get("descricao_completa") or ""

    # Imagem principal (se houver)
    imagem_url = ""
    filhos = product_data.get("imagem_principal")
    if isinstance(filhos, dict):
        imagem_url = filhos.get("grande", "") or filhos.get("caminho", "")
    elif isinstance(product_data.get("imagens"), list) and len(product_data["imagens"]) > 0:
        first_img = product_data["imagens"][0]
        imagem_url = first_img.get("caminho") or first_img.get("grande") or ""

    # Dados de SEO
    seo_uri = product_data.get("seo") or ""
    seo_id = None
    if isinstance(seo_uri, str) and "/" in seo_uri:
        parts = seo_uri.strip("/").split("/")
        if parts[-1].isdigit():
            seo_id = int(parts[-1])

    seo_title_atual = ""
    seo_desc_atual = ""
    seo_keywords_atual = ""
    if isinstance(seo_data, dict):
        seo_title_atual = seo_data.get("title") or ""
        seo_desc_atual = seo_data.get("description") or ""
        seo_keywords_atual = seo_data.get("keyword") or ""

    has_seo = 1 if (seo_title_atual and seo_desc_atual) else 0
    has_description = 1 if (descricao_atual and len(descricao_atual.strip()) > 30) else 0

    conn = get_db_connection()
    cursor = conn.cursor()

    # Verifica se já existe para preservar edições
    cursor.execute("SELECT id, status_aprovacao FROM produtos WHERE id = ?", (prod_id,))
    existing = cursor.fetchone()

    if existing:
        cursor.execute(
            """
            UPDATE produtos SET
                sku = ?,
                nome = ?,
                preco = ?,
                ativo = ?,
                imagem_url = CASE WHEN ? != '' THEN ? ELSE imagem_url END,
                seo_uri = ?,
                seo_id = ?,
                seo_title_atual = ?,
                seo_desc_atual = ?,
                seo_keywords_atual = ?,
                descricao_atual = ?,
                has_seo = ?,
                has_description = ?,
                synced_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                sku,
                nome,
                preco,
                ativo,
                imagem_url,
                imagem_url,
                str(seo_uri),
                seo_id,
                seo_title_atual,
                seo_desc_atual,
                seo_keywords_atual,
                descricao_atual,
                has_seo,
                has_description,
                prod_id,
            ),
        )
    else:
        cursor.execute(
            """
            INSERT INTO produtos (
                id, sku, nome, preco, ativo, imagem_url,
                seo_uri, seo_id, seo_title_atual, seo_desc_atual, seo_keywords_atual,
                descricao_atual, has_seo, has_description, status_aprovacao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDENTE')
            """,
            (
                prod_id,
                sku,
                nome,
                preco,
                ativo,
                imagem_url,
                str(seo_uri),
                seo_id,
                seo_title_atual,
                seo_desc_atual,
                seo_keywords_atual,
                descricao_atual,
                has_seo,
                has_description,
            ),
        )

    conn.commit()
    conn.close()


def update_product_suggestion(
    product_id: int,
    seo_title: str,
    seo_desc: str,
    seo_keywords: str,
    descricao_html: str,
    status: str = "APROVADO",
):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE produtos SET
            seo_title_sugerido = ?,
            seo_desc_sugerido = ?,
            seo_keywords_sugerido = ?,
            descricao_sugerida_html = ?,
            status_aprovacao = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (seo_title, seo_desc, seo_keywords, descricao_html, status, product_id),
    )
    conn.commit()
    conn.close()


def update_product_status(product_id: int, status: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE produtos SET status_aprovacao = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (status, product_id),
    )
    conn.commit()
    conn.close()


def approve_all_pending() -> int:
    """Aprova todos os produtos que estão com status PENDENTE."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE produtos 
        SET status_aprovacao = 'APROVADO', updated_at = CURRENT_TIMESTAMP 
        WHERE status_aprovacao = 'PENDENTE'
        """
    )
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count


def mark_as_published(product_id: int, seo_id: Optional[int] = None, seo_uri: Optional[str] = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE produtos SET
            status_aprovacao = 'PUBLICADO',
            published_at = CURRENT_TIMESTAMP,
            seo_title_atual = CASE WHEN seo_title_sugerido != '' THEN seo_title_sugerido ELSE seo_title_atual END,
            seo_desc_atual = CASE WHEN seo_desc_sugerido != '' THEN seo_desc_sugerido ELSE seo_desc_atual END,
            seo_keywords_atual = CASE WHEN seo_keywords_sugerido != '' THEN seo_keywords_sugerido ELSE seo_keywords_atual END,
            descricao_atual = CASE WHEN descricao_sugerida_html != '' THEN descricao_sugerida_html ELSE descricao_atual END,
            has_seo = 1,
            seo_id = COALESCE(?, seo_id),
            seo_uri = COALESCE(?, seo_uri)
        WHERE id = ?
        """,
        (seo_id, seo_uri, product_id),
    )
    conn.commit()
    conn.close()


def get_product(product_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM produtos WHERE id = ?", (product_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def _build_product_filter(
    status: Optional[str] = None,
    search: Optional[str] = None,
    missing_seo_only: bool = False,
    ai_status: Optional[str] = None,
    seo_status: Optional[str] = None,
):
    query = " WHERE 1=1"
    params = []

    if status and status != "TODOS":
        query += " AND status_aprovacao = ?"
        params.append(status)

    if missing_seo_only or seo_status == "SEM_SEO":
        query += " AND has_seo = 0"
    elif seo_status == "COM_SEO":
        query += " AND has_seo = 1"

    if ai_status == "GERADO":
        query += " AND ((seo_title_sugerido IS NOT NULL AND seo_title_sugerido != '') OR (descricao_sugerida_html IS NOT NULL AND descricao_sugerida_html != ''))"
    elif ai_status == "NAO_GERADO":
        query += " AND (seo_title_sugerido IS NULL OR seo_title_sugerido = '') AND (descricao_sugerida_html IS NULL OR descricao_sugerida_html = '')"

    if search:
        query += " AND (nome LIKE ? OR sku LIKE ? OR id LIKE ?)"
        s = f"%{search}%"
        params.extend([s, s, s])

    return query, params


def list_products(
    status: Optional[str] = None,
    search: Optional[str] = None,
    missing_seo_only: bool = False,
    ai_status: Optional[str] = None,
    seo_status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()

    where_clause, params = _build_product_filter(
        status=status,
        search=search,
        missing_seo_only=missing_seo_only,
        ai_status=ai_status,
        seo_status=seo_status,
    )

    query = f"SELECT * FROM produtos{where_clause} ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_products(
    status: Optional[str] = None,
    search: Optional[str] = None,
    missing_seo_only: bool = False,
    ai_status: Optional[str] = None,
    seo_status: Optional[str] = None,
) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()

    where_clause, params = _build_product_filter(
        status=status,
        search=search,
        missing_seo_only=missing_seo_only,
        ai_status=ai_status,
        seo_status=seo_status,
    )

    query = f"SELECT COUNT(*) FROM produtos{where_clause}"
    cursor.execute(query, params)
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_stats() -> Dict[str, int]:
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM produtos")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM produtos WHERE has_seo = 0")
    sem_seo = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM produtos WHERE status_aprovacao = 'APROVADO'")
    aprovados = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM produtos WHERE status_aprovacao = 'PENDENTE'")
    pendentes = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM produtos WHERE status_aprovacao = 'PUBLICADO'")
    publicados = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM produtos WHERE (seo_title_sugerido IS NOT NULL AND seo_title_sugerido != '') OR (descricao_sugerida_html IS NOT NULL AND descricao_sugerida_html != '')")
    com_ia = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM produtos WHERE (seo_title_sugerido IS NULL OR seo_title_sugerido = '') AND (descricao_sugerida_html IS NULL OR descricao_sugerida_html = '')")
    sem_ia = cursor.fetchone()[0]

    conn.close()
    return {
        "total": total,
        "sem_seo": sem_seo,
        "pendentes": pendentes,
        "aprovados": aprovados,
        "publicados": publicados,
        "com_ia": com_ia,
        "sem_ia": sem_ia,
    }


# Inicializa o banco assim que importado
init_db()

