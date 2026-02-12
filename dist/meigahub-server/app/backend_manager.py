from __future__ import annotations

import asyncio
import logging
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

import httpx

from .config import settings

logger = logging.getLogger("uvicorn.error")


@dataclass
class BackendState:
    backend: str
    model: str
    vram: str
    busy: bool


class BackendManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active_backend: Optional[str] = None
        self._busy = False
        self._llm_process: Optional[subprocess.Popen] = None
        self._whisper_process: Optional[subprocess.Popen] = None
        self._llm_model_name: Optional[str] = None

    @property
    def active_backend(self) -> Optional[str]:
        return self._active_backend

    @property
    def busy(self) -> bool:
        return self._busy

    async def get_status(self) -> BackendState:
        backend = self._active_backend or "none"
        model = ""
        vram = ""
        if backend == "llm":
            model = settings.llm_model_name
        if backend == "whisper":
            model = settings.whisper_model_name
        return BackendState(backend=backend, model=model, vram=vram, busy=self._busy)

    async def ensure_backend(self, target_backend: str) -> None:
        await self.ensure_backend_with_model(target_backend, None)

    async def ensure_backend_with_model(self, target_backend: str, model_name: Optional[str]) -> None:
        if target_backend not in {"llm", "whisper"}:
            raise ValueError("backend inválido")
        async with self._lock:
            logger.info(
                "ensure_backend_with_model target=%s model=%s active=%s",
                target_backend, model_name, self._active_backend,
            )
            if self._active_backend == target_backend:
                if target_backend == "llm" and model_name and model_name != self._llm_model_name:
                    logger.info("cambio de modelo LLM: %s → %s", self._llm_model_name, model_name)
                    await asyncio.to_thread(self._stop_llm)
                    await asyncio.to_thread(self._start_llm, model_name)
                    await self._wait_ready(settings.llm_backend_url, settings.llm_health_path)
                    self._llm_model_name = model_name
                return

            # Si no hay backend activo, verificar si ya está corriendo externamente
            if self._active_backend is None:
                already_up = await self._probe(target_backend)
                if already_up:
                    logger.info("backend '%s' ya está corriendo externamente", target_backend)
                    self._active_backend = target_backend
                    if target_backend == "llm":
                        self._llm_model_name = model_name or settings.llm_model_name
                    return

            if not settings.auto_switch_backend:
                raise RuntimeError("cambio automático deshabilitado")
            self._busy = True
            try:
                if target_backend == "llm":
                    await asyncio.to_thread(self._stop_whisper)
                    await asyncio.to_thread(self._start_llm, model_name)
                    await self._wait_ready(settings.llm_backend_url, settings.llm_health_path)
                    self._active_backend = "llm"
                    self._llm_model_name = model_name or settings.llm_model_name
                else:
                    await asyncio.to_thread(self._stop_llm)
                    await asyncio.to_thread(self._start_whisper)
                    await self._wait_ready(settings.whisper_backend_url, settings.whisper_health_path)
                    self._active_backend = "whisper"
                logger.info("backend activo ahora: %s", self._active_backend)
            finally:
                self._busy = False

    async def _probe(self, target_backend: str) -> bool:
        """Comprueba si el backend ya responde sin intentar arrancarlo."""
        if target_backend == "llm":
            url = settings.llm_backend_url.rstrip("/") + settings.llm_health_path
        else:
            url = settings.whisper_backend_url.rstrip("/") + settings.whisper_health_path
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(url, timeout=3.0)
                return r.status_code < 500
        except Exception:
            return False

    def _start_llm(self, model_name: Optional[str]) -> None:
        if self._llm_process and self._llm_process.poll() is None:
            logger.info("llm ya está corriendo (pid %s)", self._llm_process.pid)
            return
        if not settings.llm_start_command:
            logger.warning("LLM_START_COMMAND vacío, no se inicia proceso")
            return
        command = self._build_llm_command(model_name)
        logger.info("iniciando LLM: %s", command)
        self._llm_process = subprocess.Popen(command)

    def _build_llm_command(self, model_name: Optional[str]) -> list[str]:
        if not model_name:
            return self._split_command(settings.llm_start_command)
        safe_name = self._safe_filename(model_name)
        model_path = os.path.join(settings.models_dir, safe_name)
        base = self._split_command(settings.llm_start_command)
        if "--model" in base:
            idx = base.index("--model")
            if idx + 1 < len(base):
                base[idx + 1] = model_path
                return base
        return base + ["--model", model_path]

    def _safe_filename(self, name: str) -> str:
        filename = os.path.basename(name)
        if not filename.lower().endswith(".gguf"):
            raise ValueError("modelo inválido")
        if filename in {".", ".."}:
            raise ValueError("modelo inválido")
        return filename

    def _start_whisper(self) -> None:
        if self._whisper_process and self._whisper_process.poll() is None:
            logger.info("whisper ya está corriendo (pid %s)", self._whisper_process.pid)
            return
        if not settings.whisper_start_command:
            logger.warning("WHISPER_START_COMMAND vacío, no se inicia proceso")
            return
        command = self._split_command(settings.whisper_start_command)
        logger.info("iniciando Whisper: %s", command)
        self._whisper_process = subprocess.Popen(command)

    def _stop_llm(self) -> None:
        logger.info("deteniendo LLM...")
        if settings.llm_stop_command:
            command = self._split_command(settings.llm_stop_command)
            subprocess.run(command, check=False, timeout=15)
        if self._llm_process and self._llm_process.poll() is None:
            self._llm_process.terminate()
            self._llm_process.wait(timeout=10)
        self._llm_process = None

    def _stop_whisper(self) -> None:
        logger.info("deteniendo Whisper...")
        if settings.whisper_stop_command:
            command = self._split_command(settings.whisper_stop_command)
            subprocess.run(command, check=False, timeout=15)
        if self._whisper_process and self._whisper_process.poll() is None:
            self._whisper_process.terminate()
            self._whisper_process.wait(timeout=10)
        self._whisper_process = None

    async def _wait_ready(self, base_url: str, path: str) -> None:
        deadline = time.time() + settings.switch_timeout_seconds
        url = base_url.rstrip("/") + path
        logger.info("esperando backend en %s (timeout %ss)", url, settings.switch_timeout_seconds)
        async with httpx.AsyncClient() as client:
            while time.time() < deadline:
                try:
                    response = await client.get(url, timeout=5.0)
                    if response.status_code < 500:
                        logger.info("backend listo (%s)", response.status_code)
                        return
                except Exception:
                    await asyncio.sleep(0.5)
            raise RuntimeError(f"backend no disponible tras {settings.switch_timeout_seconds}s en {url}")

    def _split_command(self, command: str) -> list[str]:
        if not command:
            return []
        return shlex.split(command, posix=False)


backend_manager = BackendManager()
