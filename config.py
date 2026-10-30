import os
from pathlib import Path
from dotenv import load_dotenv

# Carrega variáveis do arquivo .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Fallback simples caso python-dotenv não esteja instalado
    env_file = Path(__file__).resolve().parent / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
BACKUP_DIR = BASE_DIR / "backups"

OUTPUT_DIR.mkdir(exist_ok=True)
BACKUP_DIR.mkdir(exist_ok=True)

def str_to_bool(val: str, default: bool = False) -> bool:
    if val is None:
        return default
    return str(val).strip().lower() in ("true", "1", "yes", "t", "s", "sim")

# Loja Integrada
LI_BASE_URL = os.getenv("LI_BASE_URL", "https://api.awsli.com.br/v1").rstrip("/")
LI_PERSONAL_TOKEN = os.getenv("LI_PERSONAL_TOKEN", "").strip()
LI_CHAVE_API = os.getenv("LI_CHAVE_API", "").strip()
LI_CHAVE_APLICACAO = os.getenv("LI_CHAVE_APLICACAO", "").strip()
LI_REQUEST_DELAY = float(os.getenv("LI_REQUEST_DELAY", "0.8"))

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

# Regras de atualização
UPDATE_SEO_TITLE = str_to_bool(os.getenv("UPDATE_SEO_TITLE", "true"), True)
UPDATE_SEO_DESCRIPTION = str_to_bool(os.getenv("UPDATE_SEO_DESCRIPTION", "true"), True)
UPDATE_SEO_KEYWORDS = str_to_bool(os.getenv("UPDATE_SEO_KEYWORDS", "true"), True)
UPDATE_DESCRIPTION_HTML = str_to_bool(os.getenv("UPDATE_DESCRIPTION_HTML", "true"), True)

# Filtros
ONLY_MISSING_SEO_OR_DESC = str_to_bool(os.getenv("ONLY_MISSING_SEO_OR_DESC", "true"), True)
ONLY_ACTIVE_PRODUCTS = str_to_bool(os.getenv("ONLY_ACTIVE_PRODUCTS", "true"), True)
PRODUCT_LIMIT = int(os.getenv("PRODUCT_LIMIT", "20"))
DRY_RUN = str_to_bool(os.getenv("DRY_RUN", "false"), False)

# Nome e URL da loja para SEO, links de busca interna e copywriting
STORE_NAME = os.getenv("STORE_NAME", "ShopB").strip()
STORE_URL = os.getenv("STORE_URL", "https://www.shopb.com.br").rstrip("/")

def validate_config(require_openai: bool = True, require_li: bool = True):
    errors = []
    if require_li:
        has_token = bool(LI_PERSONAL_TOKEN)
        has_keys = bool(LI_CHAVE_API and LI_CHAVE_APLICACAO)
        if not (has_token or has_keys):
            errors.append(
                "Credenciais da Loja Integrada não encontradas! "
                "Defina LI_PERSONAL_TOKEN ou o par (LI_CHAVE_API e LI_CHAVE_APLICACAO) no arquivo .env."
            )

    if require_openai and not OPENAI_API_KEY:
        errors.append("OPENAI_API_KEY não encontrada! Configure no arquivo .env.")

    if errors:
        raise ValueError("\n".join(errors))
