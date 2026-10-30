import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
import pandas as pd
from config import OUTPUT_DIR, BACKUP_DIR


class StorageManager:
    """
    Gerencia arquivos de aprovação (Excel / CSV) e backups de segurança.
    Permite fácil revisão no Excel ou Google Sheets sem complicação de banco de dados.
    """

    @staticmethod
    def save_approval_sheet(records: List[Dict[str, Any]], filename: str = "produtos_para_revisao.xlsx") -> Path:
        """
        Salva a lista de produtos com as sugestões da IA em uma planilha Excel e CSV.
        """
        df = pd.DataFrame(records)
        excel_path = OUTPUT_DIR / filename
        csv_path = OUTPUT_DIR / filename.replace(".xlsx", ".csv")

        # Garante ordenação de colunas intuitiva
        priority_cols = [
            "status_aprovacao",
            "produto_id",
            "nome",
            "sku",
            "seo_title_sugerido",
            "seo_description_sugerido",
            "seo_keywords_sugerido",
            "seo_title_atual",
            "seo_description_atual",
            "descricao_sugerida_html",
            "descricao_atual",
        ]
        existing_cols = [c for c in priority_cols if c in df.columns]
        other_cols = [c for c in df.columns if c not in existing_cols]
        df = df[existing_cols + other_cols]

        # Salva Excel com largura ajustada se possível
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Aprovação SEO")

        # Salva CSV também para quem preferir importar no Google Sheets
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")

        return excel_path

    @staticmethod
    def load_approved_records(sheet_path: Path) -> List[Dict[str, Any]]:
        """
        Lê a planilha preenchida/revisada e retorna apenas os itens com status_aprovacao == 'APROVADO'.
        """
        if not sheet_path.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {sheet_path}")

        if sheet_path.suffix == ".csv":
            df = pd.read_csv(sheet_path, encoding="utf-8-sig")
        else:
            df = pd.read_excel(sheet_path)

        # Trata coluna de aprovação
        if "status_aprovacao" not in df.columns:
            raise ValueError("A coluna 'status_aprovacao' é obrigatória na planilha.")

        df["status_aprovacao"] = df["status_aprovacao"].astype(str).str.strip().str.upper()
        approved_df = df[df["status_aprovacao"].isin(["APROVADO", "SIM", "OK", "TRUE", "1"])]

        # Substitui NaN por string vazia
        approved_df = approved_df.fillna("")
        return approved_df.to_dict(orient="records")

    @staticmethod
    def create_safety_backup(products_data: List[Dict[str, Any]]) -> Path:
        """
        Cria um backup JSON dos dados originais dos produtos antes de qualquer alteração na LI.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = BACKUP_DIR / f"backup_antes_do_update_{timestamp}.json"
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(products_data, f, ensure_ascii=False, indent=2)
        return backup_file

