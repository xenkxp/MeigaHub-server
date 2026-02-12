"""
Mock de servidor de imagen compatible con OpenAI /v1/images/generations.
Genera un PNG con un degradado para probar el flujo.
Uso: python scripts/mock_image_server.py
"""

import base64
import io
import time
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from PIL import Image
import uvicorn

app = FastAPI(title="Mock Image Backend")


def _make_gradient_png(width: int = 256, height: int = 256) -> bytes:
    """Genera un PNG con un degradado violeta→cian usando Pillow."""
    img = Image.new("RGB", (width, height))
    pixels = img.load()
    for y in range(height):
        for x in range(width):
            r = int(128 + 127 * (x / width))
            g = int(64 + 191 * (y / height))
            b = 255
            pixels[x, y] = (r, g, b)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [{"id": "mock-image-v1", "object": "model"}]}


@app.post("/v1/images/generations")
async def generate(request: dict):
    prompt = request.get("prompt", "")
    n = request.get("n", 1)
    size = request.get("size", "64x64")
    response_format = request.get("response_format", "b64_json")

    print(f"[mock] prompt={prompt!r}  n={n}  size={size}  format={response_format}")

    # Parsear size (e.g. "256x256", "512x512")
    try:
        w, h = [int(x) for x in size.split("x")]
    except Exception:
        w, h = 256, 256

    images = []
    for _ in range(n):
        png_bytes = _make_gradient_png(w, h)
        b64 = base64.b64encode(png_bytes).decode()
        images.append({"b64_json": b64, "revised_prompt": prompt})

    return JSONResponse(content={
        "created": int(time.time()),
        "data": images,
    })


if __name__ == "__main__":
    print("Mock image server en http://127.0.0.1:8083")
    uvicorn.run(app, host="127.0.0.1", port=8083)
