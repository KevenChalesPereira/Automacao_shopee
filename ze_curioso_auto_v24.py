#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import base64
import json
import os
import random
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import ze_curioso_v24 as core
from ze_curioso_v24_2 import fcc_generate_topic_v24_2

WORKFLOW = "ze_curioso_auto_v24.yml"
CF_MODEL = "@cf/black-forest-labs/flux-1-schnell"

ACCOUNT_KEYS = {
    "cloudflare_account_id", "cf_account_id", "workers_ai_account_id",
    "cloudflare_account", "account_id"
}
TOKEN_KEYS = {
    "cloudflare_api_token", "cf_api_token", "workers_ai_token",
    "cloudflare_token", "cf_token", "api_token"
}


def _find_value(data, keys):
    if isinstance(data, dict):
        for k, v in data.items():
            lk = str(k).lower()
            if lk in keys and isinstance(v, str) and v.strip():
                return v.strip()
        for v in data.values():
            found = _find_value(v, keys)
            if found:
                return found
    elif isinstance(data, list):
        for v in data:
            found = _find_value(v, keys)
            if found:
                return found
    return None


def load_cloudflare_settings():
    account = os.getenv("CLOUDFLARE_ACCOUNT_ID") or os.getenv("CF_ACCOUNT_ID")
    token = os.getenv("CLOUDFLARE_API_TOKEN") or os.getenv("CF_API_TOKEN")

    for path in core.CONFIG_CANDIDATES:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not account:
            account = _find_value(data, ACCOUNT_KEYS)
        if not token:
            token = _find_value(data, TOKEN_KEYS)

    if not account or not token:
        raise RuntimeError(
            "Credenciais do Cloudflare Workers AI não encontradas no config antigo. "
            "A V24 Auto não pede fundo manual: ela precisa do Cloudflare já configurado para gerar o fundo sozinha."
        )
    return account, token


def scene_background_prompt(job: dict, scene: dict, index: int) -> str:
    tema = core.clean(job.get("tema"))
    titulo = core.clean(scene.get("titulo"))
    texto = core.clean(scene.get("texto"))
    mood = [
        "mysterious curiosity hook",
        "clear explanatory moment",
        "unexpected visual detail",
        "emotional connection",
        "satisfying conclusion",
    ][min(index, 4)]
    return (
        "Vertical 9:16 cinematic background for a dark TikTok curiosity channel. "
        f"Topic: {tema}. Scene idea: {titulo}. Context: {texto}. "
        f"Mood: {mood}. Create a visually striking scene that instantly communicates the idea. "
        "High contrast, strong depth, dramatic but believable lighting, rich detail, clean focal subject, "
        "composition suitable for a short-form video. Leave some visual breathing room near the top and bottom "
        "for captions and the Zé Curioso mascot overlay. No written text, no letters, no watermark, no logo, "
        "no UI, no infographic, no presentation card."
    )[:2000]


def generate_cloudflare_image(account: str, token: str, prompt: str, destination: Path, seed: int):
    url = (
        "https://api.cloudflare.com/client/v4/accounts/"
        + urllib.parse.quote(account)
        + "/ai/run/"
        + CF_MODEL
    )
    payload = json.dumps({"prompt": prompt, "seed": int(seed), "steps": 6}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ze-curioso-auto-v24",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"Cloudflare imagem HTTP {exc.code}: {detail[:700]}") from exc

    result = data.get("result")
    image_b64 = result.get("image") if isinstance(result, dict) else None
    if not image_b64 and isinstance(result, str):
        image_b64 = result
    if not image_b64:
        raise RuntimeError(f"Cloudflare não retornou imagem: {str(data)[:700]}")
    if "," in image_b64 and image_b64.startswith("data:"):
        image_b64 = image_b64.split(",", 1)[1]
    destination.write_bytes(base64.b64decode(image_b64))


def generate_backgrounds(job: dict, workdir: Path):
    account, token = load_cloudflare_settings()
    scenes = [x for x in (job.get("cenas") or []) if isinstance(x, dict)]
    if not scenes:
        raise RuntimeError("Nenhuma cena para gerar background.")

    generated = []
    seed_base = random.randint(10000, 999999)
    core.emit(f"[>] Gerando {len(scenes)} backgrounds com IA automaticamente...")
    for i, scene in enumerate(scenes):
        prompt = scene_background_prompt(job, scene, i)
        scene["background_prompt"] = prompt
        scene["background_source"] = "cloudflare_flux"
        dest = workdir / f"scene_{i+1:02d}.jpg"
        core.emit(f"[>] Background IA {i+1}/{len(scenes)}...")
        generate_cloudflare_image(account, token, prompt, dest, seed_base + i * 97)
        if not dest.is_file() or dest.stat().st_size < 1000:
            raise RuntimeError(f"Background IA da cena {i+1} ficou inválido.")
        generated.append(dest)
    core.emit("[OK] Backgrounds de IA prontos.")
    return generated


def upload_binary(repo: str, token: str, branch: str, remote_path: str, local_path: Path):
    content = base64.b64encode(local_path.read_bytes()).decode("ascii")
    core.gh_api(
        repo,
        token,
        f"/contents/{remote_path}",
        method="PUT",
        data={
            "message": f"ze curioso auto asset {remote_path}",
            "content": content,
            "branch": branch,
        },
        timeout=180,
    )


def upload_text(repo: str, token: str, branch: str, remote_path: str, text: str):
    content = base64.b64encode(text.encode("utf-8")).decode("ascii")
    core.gh_api(
        repo,
        token,
        f"/contents/{remote_path}",
        method="PUT",
        data={
            "message": f"ze curioso auto job {remote_path}",
            "content": content,
            "branch": branch,
        },
        timeout=180,
    )


def dispatch(repo: str, token: str, job_id: str):
    core.gh_api(
        repo,
        token,
        f"/actions/workflows/{WORKFLOW}/dispatches",
        method="POST",
        data={"ref": core.DEFAULT_BRANCH, "inputs": {"job_id": job_id}},
    )


def find_run(repo: str, token: str, started: float, timeout=100):
    deadline = time.time() + timeout
    while time.time() < deadline:
        query = urllib.parse.urlencode({
            "branch": core.DEFAULT_BRANCH,
            "event": "workflow_dispatch",
            "per_page": 20,
        })
        data = core.gh_api(repo, token, f"/actions/workflows/{WORKFLOW}/runs?{query}")
        for run in data.get("workflow_runs") or []:
            created = str(run.get("created_at") or "")
            if created:
                try:
                    created_ts = time.mktime(time.strptime(created, "%Y-%m-%dT%H:%M:%SZ"))
                except Exception:
                    created_ts = started
                if created_ts + 10 >= started:
                    return int(run["id"])
        time.sleep(2)
    raise RuntimeError("Workflow Auto V24 não apareceu no GitHub.")


def cleanup_remote(repo: str, token: str, paths: list[str]):
    for remote_path in reversed(paths):
        core.cleanup_job(repo, token, remote_path)


def generate_video(tema: str):
    tema = core.clean(tema)
    if not tema:
        raise RuntimeError("Tema vazio.")

    job = fcc_generate_topic_v24_2(tema)
    job["versao"] = "24.auto"
    job["visual_mode"] = "ai_background_plus_mascot"
    job["manual_background_required"] = False

    root = Path.cwd() / "saida_ze_curioso" / core.slugify(job["titulo"])
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    local_job = root / "_job"
    local_job.mkdir()

    backgrounds = generate_backgrounds(job, local_job)
    (local_job / "curiosidade.json").write_text(
        json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    gh_token, repo = core.load_github_settings()
    job_id = uuid.uuid4().hex
    uploaded = []
    try:
        remote_json = f"jobs/{job_id}/curiosidade.json"
        upload_text(repo, gh_token, core.DEFAULT_BRANCH, remote_json, json.dumps(job, ensure_ascii=False, indent=2))
        uploaded.append(remote_json)

        for bg in backgrounds:
            remote = f"jobs/{job_id}/{bg.name}"
            upload_binary(repo, gh_token, core.DEFAULT_BRANCH, remote, bg)
            uploaded.append(remote)

        core.emit("[>] Renderizando automaticamente na nuvem...")
        started = time.time()
        dispatch(repo, gh_token, job_id)
        run_id = find_run(repo, gh_token, started)
        core.wait_run(repo, gh_token, run_id)
        core.emit("[>] Baixando vídeo pronto...")
        core.download_artifact(repo, gh_token, run_id, root)

        final = root / "anuncio_final.mp4"
        if not final.is_file():
            raise RuntimeError("Render terminou sem anuncio_final.mp4.")
        core.emit(f"[OK] ZÉ CURIOSO AUTO PRONTO: {final}")
        return final
    finally:
        cleanup_remote(repo, gh_token, uploaded)
        shutil.rmtree(local_job, ignore_errors=True)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Zé Curioso Auto V24 — aperta e gera")
    ap.add_argument("tema", nargs="*", help="tema/pergunta")
    args = ap.parse_args()
    tema = core.clean(" ".join(args.tema))
    if not tema:
        tema = core.clean(input("Tema/curiosidade: "))
    generate_video(tema)


if __name__ == "__main__":
    main()
