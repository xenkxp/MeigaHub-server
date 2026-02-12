"""Prueba rápida del endpoint /v1/images/generations."""
import httpx
import json
import base64

r = httpx.post(
    "http://127.0.0.1:3112/v1/images/generations",
    json={
        "prompt": "a beautiful sunset over the ocean",
        "n": 1,
        "size": "256x256",
        "response_format": "b64_json",
    },
    timeout=30,
)

print("HTTP Status:", r.status_code)
data = r.json()
print("Response keys:", list(data.keys()))

if "data" in data:
    for i, img in enumerate(data["data"]):
        b64 = img.get("b64_json", "")
        prompt = img.get("revised_prompt", "")
        print(f"  Image {i}: {len(b64)} chars base64, revised_prompt={prompt!r}")
        # Decodificar y guardar para verificar que es un PNG válido
        raw = base64.b64decode(b64)
        print(f"  Image {i}: {len(raw)} bytes, magic={raw[:4]}")
        if raw[:4] == b"\x89PNG":
            print(f"  Image {i}: PNG VALIDO")
        fname = f"test_image_{i}.png"
        with open(fname, "wb") as f:
            f.write(raw)
        print(f"  Guardada como {fname}")
else:
    print(json.dumps(data, indent=2))

# Verificar que el backend cambió a "image"
r2 = httpx.get("http://127.0.0.1:3112/status")
print("\nEstado del servidor:", r2.json())
