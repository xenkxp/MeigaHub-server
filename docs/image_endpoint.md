# Integrar generación de imágenes via MeigaHub Server

El servidor MeigaHub expone un endpoint compatible con la API de OpenAI para generación de imágenes.
Necesito que la app lo consuma igual que si fuera la API de OpenAI Images, pero apuntando al servidor local.

## Endpoint

```
POST http://127.0.0.1:3112/v1/images/generations
Content-Type: application/json
```

## Request body (OpenAI-compatible)

```json
{
  "prompt": "a cat sitting on a rainbow",
  "n": 1,
  "size": "512x512",
  "response_format": "b64_json"
}
```

| Campo             | Tipo   | Default      | Descripción                                       |
|-------------------|--------|--------------|---------------------------------------------------|
| `prompt`          | string | (requerido)  | Descripción de la imagen a generar                |
| `n`               | int    | 1            | Número de imágenes a generar                      |
| `size`            | string | "512x512"    | Tamaño de la imagen (e.g. "256x256", "1024x1024") |
| `response_format` | string | "b64_json"   | `"b64_json"` (base64 inline) o `"url"`            |

## Response body

```json
{
  "created": 1739180000,
  "data": [
    {
      "b64_json": "<base64-encoded PNG>",
      "revised_prompt": "a cat sitting on a rainbow"
    }
  ]
}
```

Cada objeto en `data` tiene:
- `b64_json`: imagen PNG codificada en base64 (si `response_format` = `"b64_json"`)
- `url`: URL de la imagen (si `response_format` = `"url"`)
- `revised_prompt`: el prompt que usó el backend

## Notas de integración

- El servidor gestiona VRAM automáticamente. Al llamar a este endpoint, el backend de imágenes se activará y los demás (LLM, Whisper) se detendrán. No necesitas gestionar esto desde el cliente.
- El base URL del servidor es configurable. Usa una variable de entorno o configuración para `MEIGAHUB_URL` (default `http://127.0.0.1:3112`).
- El endpoint es compatible con el SDK de OpenAI. Si la app ya usa `openai` Python/JS, basta con cambiar `base_url`.

## Ejemplos de uso

### Python (openai SDK)

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:3112/v1", api_key="not-needed")

response = client.images.generate(
    prompt="a cat sitting on a rainbow",
    n=1,
    size="512x512",
    response_format="b64_json",
)

image_b64 = response.data[0].b64_json
```

### JavaScript (fetch)

```javascript
const res = await fetch("http://127.0.0.1:3112/v1/images/generations", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    prompt: "a cat sitting on a rainbow",
    n: 1,
    size: "512x512",
    response_format: "b64_json",
  }),
});
const data = await res.json();
const imageBase64 = data.data[0].b64_json;
```

## Verificar estado del servidor

```
GET http://127.0.0.1:3112/status
```

Respuesta:

```json
{
  "backend": "image",
  "model": "stable-diffusion-v1.5",
  "vram": "",
  "busy": false
}
```
