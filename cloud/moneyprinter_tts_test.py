#!/usr/bin/env python3
"""Teste isolado do motor TikTok TTS usado pelo MoneyPrinter.

Mantém os mesmos endpoints e IDs de voz do projeto upstream, mas valida a
resposta de forma mais robusta para o GitHub Actions.

Upstream: https://github.com/FujiwaraChoki/MoneyPrinter
Arquivo de referência: Backend/tiktokvoice.py
Licença upstream: MIT.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import re
import sys

import requests

ENDPOINTS = [
    "https://tiktok-tts.weilnet.workers.dev/api/generation",
    "https://tiktoktts.com/api/tiktok-tts",
]

VOICES = {
    "br_001": "Português BR - Feminina 1",
    "br_003": "Português BR - Feminina 2",
    "br_004": "Português BR - Feminina 3",
    "br_005": "Português BR - Masculina",
}

TEXT = (
    "Esse animal parece impossível, mas existe de verdade. "
    "Ele consegue sobreviver em condições que derrubariam quase qualquer outro animal. "
    "Eu sou o Zé Curioso. E aqui... parece mentira, mas é real."
)

OUT = Path("moneyprinter_tts_test")


def _looks_like_b64(value: str) -> bool:
    value = value.strip()
    if value.startswith("data:") and "," in value:
        value = value.split(",", 1)[1]
    if len(value) < 500:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9+/=\s]+", value))


def _find_audio_b64(obj):
    if isinstance(obj, str):
        if obj.startswith("data:") and "," in obj:
            candidate = obj.split(",", 1)[1]
            if _looks_like_b64(candidate):
                return candidate
        if _looks_like_b64(obj):
            return obj
        return None
    if isinstance(obj, dict):
        # Campos comuns nesses wrappers.
        for key in ("data", "audio", "audio_data", "base64", "base64_data"):
            if key in obj:
                found = _find_audio_b64(obj[key])
                if found:
                    return found
        for value in obj.values():
            found = _find_audio_b64(value)
            if found:
                return found
    if isinstance(obj, list):
        for value in obj:
            found = _find_audio_b64(value)
            if found:
                return found
    return None


def synth(endpoint: str, voice: str) -> tuple[bytes, dict]:
    r = requests.post(
        endpoint,
        headers={"Content-Type": "application/json", "User-Agent": "ZeCurioso-MoneyPrinter-TTS-Test/1.0"},
        json={"text": TEXT, "voice": voice},
        timeout=90,
    )
    meta = {
        "endpoint": endpoint,
        "http_status": r.status_code,
        "content_type": r.headers.get("content-type", ""),
        "response_bytes": len(r.content),
    }
    r.raise_for_status()

    # Alguns proxies podem devolver áudio diretamente.
    ctype = meta["content_type"].lower()
    if "audio/" in ctype and len(r.content) > 1000:
        return r.content, meta

    try:
        data = r.json()
    except Exception:
        data = None

    audio_b64 = _find_audio_b64(data)
    if not audio_b64:
        preview = r.text[:500] if "text" in ctype or "json" in ctype else repr(r.content[:120])
        raise RuntimeError(f"resposta sem áudio reconhecível: {preview}")

    raw = base64.b64decode(audio_b64)
    if len(raw) < 1000:
        raise RuntimeError(f"áudio muito pequeno: {len(raw)} bytes")
    return raw, meta


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report = {
        "engine": "MoneyPrinter TikTok TTS",
        "upstream": "FujiwaraChoki/MoneyPrinter Backend/tiktokvoice.py",
        "text": TEXT,
        "voices": {},
    }

    success = 0
    for voice, label in VOICES.items():
        errors = []
        for endpoint in ENDPOINTS:
            try:
                audio, meta = synth(endpoint, voice)
                dest = OUT / f"{voice}.mp3"
                dest.write_bytes(audio)
                report["voices"][voice] = {
                    "label": label,
                    "ok": True,
                    "file": dest.name,
                    **meta,
                }
                print(f"OK {voice}: {label} -> {dest} ({len(audio)} bytes)")
                success += 1
                break
            except Exception as exc:
                errors.append(f"{endpoint}: {type(exc).__name__}: {exc}")
                print(f"FAIL {voice} via {endpoint}: {exc}", file=sys.stderr)
        else:
            report["voices"][voice] = {
                "label": label,
                "ok": False,
                "errors": errors,
            }

    (OUT / "texto_teste.txt").write_text(TEXT + "\n", encoding="utf-8")
    (OUT / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # O teste é útil se pelo menos uma voz brasileira funcionar.
    if success == 0:
        print("Nenhuma voz brasileira do MoneyPrinter respondeu.", file=sys.stderr)
        return 2
    print(f"MONEYPRINTER_TTS_TEST_OK voices={success}/{len(VOICES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
