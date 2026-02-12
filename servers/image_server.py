"""
Servidor de generación de imagen con diffusers.

Expone endpoints compatibles con OpenAI:
  - GET  /v1/models          → lista del modelo cargado
  - POST /v1/images/generations → genera imagen(es)

Uso:
  python servers/image_server.py
  python servers/image_server.py --port 8083 --model C:/models/sd_xl_base_1.0.safetensors
"""

from __future__ import annotations

import argparse
import base64
import io
import logging
import time
import uuid
from pathlib import Path
from contextlib import asynccontextmanager

import torch
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel, Field
from typing import Optional, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("image_server")

# ── Estado global ──

pipe: Optional[object] = None
model_id: str = ""
device: str = "cuda" if torch.cuda.is_available() else "cpu"
dtype = torch.float16 if device == "cuda" else torch.float32
is_sdxl: bool = False  # Se detecta al cargar el modelo


def load_pipeline(model_path: str) -> None:
    """Carga el pipeline de diffusers desde un safetensors/ckpt o repo HF."""
    global pipe, model_id, is_sdxl

    # Import lazy para evitar problemas de compatibilidad entre diffusers/transformers
    from diffusers import (
        StableDiffusionPipeline,
        StableDiffusionXLPipeline,
        EulerDiscreteScheduler,
    )

    model_id = model_path
    logger.info("Cargando modelo: %s  (device=%s, dtype=%s)", model_path, device, dtype)

    p = Path(model_path)

    if p.is_file():
        size_gb = p.stat().st_size / (1024 ** 3)
        if size_gb > 4.0 or "xl" in p.name.lower():
            logger.info("Archivo (%.1f GB) — cargando como SDXL...", size_gb)
            pipe = StableDiffusionXLPipeline.from_single_file(
                str(p), torch_dtype=dtype, use_safetensors=str(p).endswith(".safetensors"),
            )
            is_sdxl = True
        else:
            logger.info("Archivo (%.1f GB) — cargando como SD 1.x/2.x...", size_gb)
            pipe = StableDiffusionPipeline.from_single_file(
                str(p), torch_dtype=dtype, use_safetensors=str(p).endswith(".safetensors"),
            )
    else:
        # Repo de HuggingFace o directorio local — intentar SDXL primero
        logger.info("Cargando como repo/directorio...")
        try:
            pipe = StableDiffusionXLPipeline.from_pretrained(
                model_path, torch_dtype=dtype,
            )
            is_sdxl = True
        except Exception:
            logger.info("No es SDXL, intentando como SD 1.x/2.x...")
            pipe = StableDiffusionPipeline.from_pretrained(
                model_path, torch_dtype=dtype,
            )

    # ── Scheduler óptimo ──
    # EulerDiscrete da mejor calidad + velocidad que el scheduler por defecto
    pipe.scheduler = EulerDiscreteScheduler.from_config(pipe.scheduler.config)
    logger.info("Scheduler configurado: EulerDiscreteScheduler")

    pipe = pipe.to(device)

    # ── FIX CRÍTICO: VAE de SDXL en float16 produce NaN → imágenes basura ──
    # No convertimos manualmente el VAE; dejamos que el pipeline lo haga
    # durante la inferencia cuando detecta force_upcast=True.
    # Esto asegura que los latents fp16 del UNet también se castean a fp32.
    if is_sdxl:
        pipe.vae.config.force_upcast = True
        logger.info("VAE force_upcast=True (el pipeline cast a fp32 en cada decode)")

    # Optimizaciones de memoria
    if device == "cuda":
        try:
            pipe.enable_xformers_memory_efficient_attention()
            logger.info("xformers habilitado")
        except Exception:
            logger.info("xformers no disponible, usando attention slicing")
            pipe.enable_attention_slicing()
        # VAE tiling + slicing para reducir VRAM en resoluciones altas
        pipe.enable_vae_tiling()
        pipe.enable_vae_slicing()
        logger.info("VAE tiling + slicing habilitado")
    else:
        pipe.enable_attention_slicing()

    logger.info(
        "Modelo cargado correctamente en %s (tipo=%s, resolución nativa=%s)",
        device, "SDXL" if is_sdxl else "SD1.x/2.x",
        "1024x1024" if is_sdxl else "512x512",
    )


# ── Modelos de request/response ──

# Negative prompt por defecto para mejorar calidad
DEFAULT_NEGATIVE = (
    "lowres, bad anatomy, bad hands, text, error, missing fingers, "
    "extra digit, fewer digits, cropped, worst quality, low quality, "
    "normal quality, jpeg artifacts, signature, watermark, username, blurry, "
    "deformed, ugly, duplicate, morbid, mutilated"
)


class ImageGenRequest(BaseModel):
    prompt: str
    n: int = Field(default=1, ge=1, le=4)
    size: Optional[str] = None  # None = autodetectar según modelo
    response_format: str = "b64_json"  # "b64_json" o "url"
    model: Optional[str] = None
    negative_prompt: Optional[str] = None
    num_inference_steps: Optional[int] = None
    guidance_scale: Optional[float] = None
    seed: Optional[int] = None


# ── App ──

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title="MeigaHub Image Server", lifespan=lifespan)


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": model_id,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "local",
            }
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok", "model": model_id, "device": device}


@app.post("/v1/images/generations")
async def images_generations(req: ImageGenRequest):
    if pipe is None:
        return JSONResponse(
            status_code=503,
            content={"error": {"message": "modelo no cargado", "code": "model_not_loaded"}},
        )

    # Resolución: SDXL nativa = 1024x1024, SD1.x = 512x512
    default_size = 1024 if is_sdxl else 512
    if req.size:
        try:
            w, h = (int(x) for x in req.size.split("x"))
        except ValueError:
            w, h = default_size, default_size
    else:
        w, h = default_size, default_size

    # Asegurar múltiplo de 8 (requerido por diffusers)
    w = (w // 8) * 8
    h = (h // 8) * 8

    # SDXL: mínimo 768 para calidad aceptable
    if is_sdxl and (w < 768 or h < 768):
        logger.warning(
            "SDXL con resolución %dx%d es muy baja, escalando a mínimo 768",
            w, h,
        )
        scale = 768 / min(w, h)
        w = (int(w * scale) // 8) * 8
        h = (int(h * scale) // 8) * 8

    # Defaults de calidad según modelo
    if is_sdxl:
        steps = req.num_inference_steps or 25
        guidance = req.guidance_scale or 7.0
    else:
        steps = req.num_inference_steps or 30
        guidance = req.guidance_scale or 7.5

    generator = None
    if req.seed is not None:
        generator = torch.Generator(device=device).manual_seed(req.seed)

    logger.info(
        "Generando %d imagen(es): prompt=%r, size=%dx%d, steps=%d, guidance=%.1f",
        req.n, req.prompt[:80], w, h, steps, guidance,
    )

    t0 = time.time()

    # Negative prompt: usar el del usuario si lo envía, si no el default
    neg = req.negative_prompt if req.negative_prompt else DEFAULT_NEGATIVE

    kwargs = {
        "prompt": req.prompt,
        "negative_prompt": neg,
        "num_images_per_prompt": req.n,
        "width": w,
        "height": h,
        "num_inference_steps": steps,
        "guidance_scale": guidance,
    }
    if generator:
        kwargs["generator"] = generator

    with torch.inference_mode():
        result = pipe(**kwargs)

    elapsed = time.time() - t0
    logger.info("Generación completada en %.1fs", elapsed)

    # Codificar resultado
    data_items: List[dict] = []
    for img in result.images:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        data_items.append({
            "b64_json": b64,
            "revised_prompt": req.prompt,
        })

    return {
        "created": int(time.time()),
        "data": data_items,
    }


# ── Main ──

def main():
    parser = argparse.ArgumentParser(description="MeigaHub Image Server (diffusers)")
    parser.add_argument("--port", type=int, default=8083, help="Puerto (default: 8083)")
    parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    parser.add_argument(
        "--model",
        default=None,
        help="Ruta al modelo .safetensors/.ckpt o nombre de repo HF",
    )
    args = parser.parse_args()

    if args.model:
        load_pipeline(args.model)
    else:
        logger.warning("Sin --model, el servidor arrancará sin modelo cargado")

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
