import httpx
import sys
import os

BASE = os.environ.get("MEIGAHUB_URL", "http://127.0.0.1:3112")

# Obtener modelo: argumento CLI > variable de entorno > preguntar al servidor
MODEL = None
if len(sys.argv) > 1:
    MODEL = sys.argv[1]
else:
    # Intentar obtener el modelo activo del servidor
    try:
        status = httpx.get(f"{BASE}/status", timeout=5.0).json()
        if status.get("model"):
            MODEL = status["model"]
    except Exception:
        pass

if not MODEL:
    print("No se pudo determinar el modelo. Usa: python test_llm.py <nombre-modelo.gguf>")
    print("O asegurate de que el servidor esta corriendo con un modelo activo.")
    sys.exit(1)

print(f"Servidor: {BASE}")
print(f"Modelo:   {MODEL}")
print()

print("status before", httpx.get(f"{BASE}/status", timeout=5.0).text)

chat_payload = {
    "model": MODEL,
    "messages": [{"role": "user", "content": "Di 'hola' en una palabra"}],
    "temperature": 0.2,
    "max_tokens": 8,
}
comp_payload = {
    "model": MODEL,
    "prompt": "Di 'hola' en una palabra:",
    "max_tokens": 8,
    "temperature": 0.2,
}
emb_payload = {
    "model": MODEL,
    "input": "hola",
}

r = httpx.post(f"{BASE}/v1/chat/completions", json=chat_payload, timeout=120.0)
print("chat", r.status_code, r.text[:300])

r = httpx.post(f"{BASE}/v1/completions", json=comp_payload, timeout=120.0)
print("completions", r.status_code, r.text[:300])

r = httpx.post(f"{BASE}/v1/embeddings", json=emb_payload, timeout=120.0)
print("embeddings", r.status_code, r.text[:300])

print("status after", httpx.get(f"{BASE}/status", timeout=5.0).text)
