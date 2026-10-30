import threading
import time
import logging
from typing import Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("TaskManager")


class BackgroundTaskManager:
    """
    Gerencia tarefas de longa duração em background (Sincronização, Geração com IA, Publicação).
    Permite controle de progresso em tempo real, cancelamento e não trava o servidor web.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.stop_requested = threading.Event()
        self.active_thread: Optional[threading.Thread] = None
        self.task_state: Dict[str, Any] = {
            "is_running": False,
            "type": None,  # "sync", "generate", "publish"
            "title": "",
            "total": 0,
            "current": 0,
            "percent": 0,
            "message": "",
            "errors": [],
            "completed_at": None,
        }

    def get_state(self) -> Dict[str, Any]:
        with self.lock:
            return dict(self.task_state)

    def request_cancel(self):
        with self.lock:
            if self.task_state["is_running"]:
                self.stop_requested.set()
                self.task_state["message"] = "Cancelamento solicitado..."
                logger.info("Cancelamento de tarefa em background solicitado.")

    def start_task(self, task_type: str, title: str, worker_func, *args, **kwargs) -> bool:
        """Inicia uma tarefa em background caso nenhuma outra esteja rodando."""
        with self.lock:
            if self.task_state["is_running"]:
                return False

            self.stop_requested.clear()
            self.task_state = {
                "is_running": True,
                "type": task_type,
                "title": title,
                "total": 0,
                "current": 0,
                "percent": 0,
                "message": "Iniciando processamento...",
                "errors": [],
                "completed_at": None,
            }

        def runner():
            try:
                worker_func(self, *args, **kwargs)
            except Exception as e:
                logger.error(f"Erro fatal na tarefa em background '{task_type}': {e}", exc_info=True)
                with self.lock:
                    self.task_state["errors"].append(str(e))
                    self.task_state["message"] = f"Erro: {e}"
            finally:
                with self.lock:
                    self.task_state["is_running"] = False
                    self.task_state["completed_at"] = time.strftime("%H:%M:%S")
                    if self.stop_requested.is_set():
                        self.task_state["message"] = "Tarefa cancelada pelo usuário."
                    elif not self.task_state["errors"]:
                        self.task_state["message"] = "Processamento concluído com sucesso!"
                logger.info(f"Tarefa em background '{task_type}' finalizada.")

        self.active_thread = threading.Thread(target=runner, daemon=True)
        self.active_thread.start()
        return True

    def update_progress(self, current: int, total: int, message: str = ""):
        with self.lock:
            self.task_state["current"] = current
            self.task_state["total"] = total
            self.task_state["percent"] = int((current / total * 100)) if total > 0 else 0
            if message:
                self.task_state["message"] = message

    def add_error(self, error_msg: str):
        with self.lock:
            self.task_state["errors"].append(error_msg)
            # Mantém no máximo os 10 últimos erros para não sobrecarregar
            if len(self.task_state["errors"]) > 10:
                self.task_state["errors"].pop(0)


# Instância global compartilhada
task_manager = BackgroundTaskManager()
