from __future__ import annotations

import asyncio
import logging
import os
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

import httpx

from .config import settings

logger = logging.getLogger("uvicorn.error")


# ---------------------------------------------------------------------------
# Datos de estado público
# ---------------------------------------------------------------------------

@dataclass
class BackendState:
    backend: str
    model: str
    vram: str
    busy: bool


# ---------------------------------------------------------------------------
# Descriptor interno de cada backend registrado
# ---------------------------------------------------------------------------

@dataclass
class _BackendDescriptor:
    """Toda la información que BackendManager necesita para gestionar un backend."""

    name: str

    # Callables que devuelven el valor actual de settings (lectura lazy).
    get_url: callable           # () -> str
    get_health_path: callable   # () -> str
    get_model_name: callable    # () -> str
    get_start_command: callable # () -> str
    get_stop_command: callable  # () -> str

    # Si True, el modelo se puede cambiar dinámicamente y se inserta como
    # argumento --model al arrancar (patrón llama.cpp).
    supports_dynamic_model: bool = False

    # Proceso gestionado internamente (si se lanza desde aquí).
    process: Optional[subprocess.Popen] = field(default=None, repr=False)

    # Modelo que está cargado actualmente.
    current_model: Optional[str] = None


# ---------------------------------------------------------------------------
# BackendManager — genérico para N backends mutuamente excluyentes
# ---------------------------------------------------------------------------

class BackendManager:
    """Gestiona N backends mutuamente excluyentes (solo uno activo a la vez)."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active_backend: Optional[str] = None
        self._busy = False

        # Registro de backends — orden no importa.
        self._backends: Dict[str, _BackendDescriptor] = {}
        self._register_defaults()

    # ------------------------------------------------------------------
    # Registro
    # ------------------------------------------------------------------

    def _register_defaults(self) -> None:
        """Registra los backends conocidos leyendo settings."""

        self.register_backend(_BackendDescriptor(
            name="llm",
            get_url=lambda: settings.llm_backend_url,
            get_health_path=lambda: settings.llm_health_path,
            get_model_name=lambda: settings.llm_model_name,
            get_start_command=lambda: settings.llm_start_command,
            get_stop_command=lambda: settings.llm_stop_command,
            supports_dynamic_model=True,
        ))

        self.register_backend(_BackendDescriptor(
            name="whisper",
            get_url=lambda: settings.whisper_backend_url,
            get_health_path=lambda: settings.whisper_health_path,
            get_model_name=lambda: settings.whisper_model_name,
            get_start_command=lambda: settings.whisper_start_command,
            get_stop_command=lambda: settings.whisper_stop_command,
            supports_dynamic_model=False,
        ))

        self.register_backend(_BackendDescriptor(
            name="image",
            get_url=lambda: settings.image_backend_url,
            get_health_path=lambda: settings.image_health_path,
            get_model_name=lambda: settings.image_model_name,
            get_start_command=lambda: settings.image_start_command,
            get_stop_command=lambda: settings.image_stop_command,
            supports_dynamic_model=False,
        ))

    def register_backend(self, descriptor: _BackendDescriptor) -> None:
        """Registra (o reemplaza) un descriptor de backend."""
        self._backends[descriptor.name] = descriptor

    @property
    def known_backends(self) -> list[str]:
        """Nombres de todos los backends registrados."""
        return list(self._backends.keys())

    # ------------------------------------------------------------------
    # Propiedades públicas
    # ------------------------------------------------------------------

    @property
    def active_backend(self) -> Optional[str]:
        return self._active_backend

    @property
    def busy(self) -> bool:
        return self._busy

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    async def get_status(self) -> BackendState:
        backend = self._active_backend or "none"
        model = ""
        if backend in self._backends:
            desc = self._backends[backend]
            model = desc.current_model or desc.get_model_name()
        return BackendState(backend=backend, model=model, vram="", busy=self._busy)

    def get_all_backends_info(self) -> list[dict]:
        """Devuelve info de cada backend registrado para la UI."""
        result = []
        for name, desc in self._backends.items():
            running = False
            if desc.process and desc.process.poll() is None:
                running = True
            result.append({
                "name": name,
                "active": self._active_backend == name,
                "running": running,
                "model": desc.current_model or desc.get_model_name(),
                "url": desc.get_url(),
                "has_start_command": bool(desc.get_start_command()),
                "has_stop_command": bool(desc.get_stop_command()),
            })
        return result

    async def activate_backend(self, name: str) -> None:
        """Activa un backend desde la UI (equivale a ensure_backend)."""
        await self.ensure_backend(name)

    async def stop_active_backend(self) -> None:
        """Detiene el backend activo y deja el servidor sin backend."""
        async with self._lock:
            if self._active_backend and self._active_backend in self._backends:
                desc = self._backends[self._active_backend]
                await asyncio.to_thread(self._stop_one, desc)
            self._active_backend = None

    # ------------------------------------------------------------------
    # Ensure (API pública)
    # ------------------------------------------------------------------

    async def ensure_backend(self, target_backend: str) -> None:
        await self.ensure_backend_with_model(target_backend, None)

    async def ensure_backend_with_model(
        self, target_backend: str, model_name: Optional[str],
    ) -> None:
        if target_backend not in self._backends:
            raise ValueError(f"backend inválido: {target_backend}")

        desc = self._backends[target_backend]

        async with self._lock:
            logger.info(
                "ensure_backend_with_model target=%s model=%s active=%s",
                target_backend, model_name, self._active_backend,
            )

            # Ya activo — verificar si hay cambio de modelo dinámico
            if self._active_backend == target_backend:
                if (
                    desc.supports_dynamic_model
                    and model_name
                    and model_name != desc.current_model
                ):
                    logger.info(
                        "cambio de modelo %s: %s → %s",
                        target_backend, desc.current_model, model_name,
                    )
                    await asyncio.to_thread(self._stop_one, desc)
                    await asyncio.to_thread(self._start_one, desc, model_name)
                    await self._wait_ready(desc.get_url(), desc.get_health_path())
                    desc.current_model = model_name
                return

            # No hay backend activo — comprobar si ya corre externamente
            if self._active_backend is None:
                if await self._probe_descriptor(desc):
                    logger.info(
                        "backend '%s' ya está corriendo externamente",
                        target_backend,
                    )
                    self._active_backend = target_backend
                    desc.current_model = model_name or desc.get_model_name()
                    return

            if not settings.auto_switch_backend:
                raise RuntimeError("cambio automático deshabilitado")

            # ── Pre-verificación: ¿el target puede arrancar? ──
            # Si no tiene comando de arranque, comprobar si ya corre externamente.
            # Si no está corriendo, fallar ANTES de detener los demás backends.
            has_start_cmd = bool(desc.get_start_command())
            if not has_start_cmd:
                already_running = await self._probe_descriptor(desc)
                if not already_running:
                    raise RuntimeError(
                        f"no se puede activar '{target_backend}': "
                        f"sin comando de arranque y no está corriendo externamente"
                    )

            # Cambio de backend — detener todos los demás, arrancar el objetivo
            self._busy = True
            try:
                for name, other in self._backends.items():
                    if name != target_backend:
                        await asyncio.to_thread(self._stop_one, other)

                started = await asyncio.to_thread(self._start_one, desc, model_name)

                # Si no se pudo arrancar, comprobar si corre externamente
                if not started:
                    if not await self._probe_descriptor(desc):
                        raise RuntimeError(
                            f"no se puede activar '{target_backend}': "
                            f"sin comando de arranque y no está corriendo externamente"
                        )
                else:
                    await self._wait_ready(desc.get_url(), desc.get_health_path())

                self._active_backend = target_backend
                desc.current_model = model_name or desc.get_model_name()

                logger.info("backend activo ahora: %s", self._active_backend)
            finally:
                self._busy = False

    # ------------------------------------------------------------------
    # Probe
    # ------------------------------------------------------------------

    async def _probe_descriptor(self, desc: _BackendDescriptor) -> bool:
        """Comprueba si el backend ya responde sin intentar arrancarlo."""
        url = desc.get_url().rstrip("/") + desc.get_health_path()
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(url, timeout=3.0)
                return r.status_code < 500
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Start / Stop genéricos
    # ------------------------------------------------------------------

    def _start_one(
        self, desc: _BackendDescriptor, model_name: Optional[str] = None,
    ) -> bool:
        """Inicia el proceso de un backend. Devuelve True si se arrancó o ya corría."""
        if desc.process and desc.process.poll() is None:
            logger.info("%s ya está corriendo (pid %s)", desc.name, desc.process.pid)
            return True

        start_cmd = desc.get_start_command()
        if not start_cmd:
            logger.warning(
                "%s_START_COMMAND vacío, no se inicia proceso", desc.name.upper(),
            )
            return False

        command = self._build_command(desc, start_cmd, model_name)
        logger.info("iniciando %s: %s", desc.name, command)
        desc.process = subprocess.Popen(command)
        return True

    def _stop_one(self, desc: _BackendDescriptor) -> None:
        """Detiene el proceso de un backend (solo si hay algo que detener)."""
        has_process = desc.process and desc.process.poll() is None
        has_stop_cmd = bool(desc.get_stop_command())

        if not has_process and not has_stop_cmd:
            return  # nada que hacer
        if not has_process and has_stop_cmd:
            # Solo ejecutar stop_cmd si realmente creemos que corre
            # (evita "no se encontró el proceso" innecesario)
            return

        logger.info("deteniendo %s...", desc.name)

        if has_stop_cmd:
            command = self._split_command(desc.get_stop_command())
            subprocess.run(
                command, check=False, timeout=15,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

        if has_process:
            desc.process.terminate()
            desc.process.wait(timeout=10)

        desc.process = None

    # ------------------------------------------------------------------
    # Construcción de comandos
    # ------------------------------------------------------------------

    def _build_command(
        self,
        desc: _BackendDescriptor,
        start_cmd: str,
        model_name: Optional[str],
    ) -> list[str]:
        base = self._split_command(start_cmd)

        if not desc.supports_dynamic_model or not model_name:
            return base

        # Insertar / reemplazar --model <path> (patrón llama.cpp)
        safe_name = self._safe_filename(model_name)
        model_path = os.path.join(settings.models_dir, safe_name)

        if "--model" in base:
            idx = base.index("--model")
            if idx + 1 < len(base):
                base[idx + 1] = model_path
                return base

        return base + ["--model", model_path]

    @staticmethod
    def _safe_filename(name: str) -> str:
        filename = os.path.basename(name)
        if not filename.lower().endswith(".gguf"):
            raise ValueError("modelo inválido")
        if filename in {".", ".."}:
            raise ValueError("modelo inválido")
        return filename

    # ------------------------------------------------------------------
    # Wait ready
    # ------------------------------------------------------------------

    async def _wait_ready(self, base_url: str, path: str) -> None:
        deadline = time.time() + settings.switch_timeout_seconds
        url = base_url.rstrip("/") + path
        logger.info(
            "esperando backend en %s (timeout %ss)",
            url, settings.switch_timeout_seconds,
        )
        async with httpx.AsyncClient() as client:
            while time.time() < deadline:
                try:
                    response = await client.get(url, timeout=5.0)
                    if response.status_code < 500:
                        logger.info("backend listo (%s)", response.status_code)
                        return
                except Exception:
                    await asyncio.sleep(0.5)
            raise RuntimeError(
                f"backend no disponible tras {settings.switch_timeout_seconds}s en {url}",
            )

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------

    @staticmethod
    def _split_command(command: str) -> list[str]:
        if not command:
            return []
        return shlex.split(command, posix=False)


backend_manager = BackendManager()
