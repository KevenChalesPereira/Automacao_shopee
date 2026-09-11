#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path

FCC_URL = os.getenv("FCC_URL", "http://127.0.0.1:8082/v1/messages")
FCC_API_KEY = os.getenv("FCC_API_KEY", "freecc")
FCC_MODEL = os.getenv("FCC_MODEL", "claude-sonnet-4-20250514")
DEFAULT_REPO = os.getenv("ZE_CURIOSO_GITHUB_REPO", "KevenChalesPereira/Automacao_shopee")
DEFAULT_BRANCH = os.getenv("ZE_CURIOSO_BRANCH", "ze-curioso-v24")
WORKFLOW = "ze_curioso_v24.yml"
CONFIG_CANDIDATES = [
    Path.home() / ".config" / "ze-curioso" / "config.json",
    Path.home() / ".config" / "shopee-video-v3" / "config.json",
]


def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def slugify(value: str) -> str:
    value = clean(value).lower()
    value = re.sub(r"[^a-z0-9à-ÿ]+", "-", value, flags=re.I)
    value = re.sub(r"-+", "-", value).strip("-")
    return value[:70] or "curiosidade"


def emit(msg: str):
    print(msg, flush=True)


def http_json(url: str, method="GET", data=None, headers=None, timeout=120):
    payload = None
    req_headers = {"User-Agent": "ze-curioso-v24"}
    if headers:
        req_headers.update(headers)
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=payload, method=method, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return resp.status, {}
            return resp.status, json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            body = json.loads(raw)
        except Exception:
            body = {"raw": raw}
        return exc.code, body


def extract_json_object(text: str):
    text = str(text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start:end+1])
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return None


def fcc_generate_topic(tema: str, timeout=120):
    prompt = f"""
Você é o roteirista do Zé Curioso Studio V24.
Crie um vídeo vertical curto em português do Brasil sobre o tema abaixo.

PERSONAGEM E TOM
- Zé Curioso é um apresentador adulto, simpático e curioso.
- Pode usar naturalmente expressões como "Oxente...", "Rapaz...", "Mas pera aí..." e "Agora olha isso...".
- Não caricature sotaque nem escreva palavras propositalmente erradas.
- O texto deve soar natural em voz TTS brasileira.

REGRAS DE CONTEÚDO
- Priorize fatos amplamente aceitos e explicações simples.
- Não invente números, pesquisas, instituições ou estatísticas.
- Não faça diagnóstico médico, promessa de saúde ou afirmação extraordinária.
- Se o tema for controverso ou depender de informação atual, mantenha o texto cauteloso e marque precisa_verificacao=true.
- O hook precisa prender atenção sem clickbait falso.
- Roteiro entre 75 e 125 palavras.
- Exatamente 5 cenas.
- Cada cena deve ter titulo curto e texto de no máximo 18 palavras.
- O CTA deve convidar a seguir o Zé Curioso, sem vender produto.

TEMA:
{tema}

Responda SOMENTE JSON válido neste formato:
{{
  "tema": "...",
  "titulo": "...",
  "hook": "...",
  "roteiro": "...",
  "voz": "pt-BR-AntonioNeural",
  "cta": "Segue o Zé Curioso para mais curiosidades rápidas.",
  "precisa_verificacao": false,
  "cenas": [
    {{"titulo":"...","texto":"..."}},
    {{"titulo":"...","texto":"..."}},
    {{"titulo":"...","texto":"..."}},
    {{"titulo":"...","texto":"..."}},
    {{"titulo":"...","texto":"..."}}
  ]
}}
""".strip()

    body = {
        "model": FCC_MODEL,
        "max_tokens": 3500,
        "temperature": 0.25,
        "stream": False,
        "messages": [{"role": "user", "content": prompt}],
    }
    emit("[>] Zé Curioso: pedindo roteiro estruturado ao FCC...")
    status, data = http_json(
        FCC_URL,
        method="POST",
        data=body,
        headers={
            "x-api-key": FCC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        timeout=timeout,
    )
    if status != 200:
        raise RuntimeError(f"FCC retornou HTTP {status}: {str(data)[:800]}")

    blocks = data.get("content") or []
    text_parts = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(str(block.get("text") or ""))
    result = extract_json_object("\n".join(text_parts))
    if not result:
        raise RuntimeError("FCC não retornou JSON utilizável.")
    return validate_job(result, tema)


def validate_job(job: dict, tema_original: str):
    roteiro = clean(job.get("roteiro"))
    hook = clean(job.get("hook"))
    titulo = clean(job.get("titulo"))
    scenes = [x for x in (job.get("cenas") or []) if isinstance(x, dict)]
    if not titulo or not hook or len(roteiro.split()) < 45:
        raise RuntimeError("Roteiro do FCC veio incompleto.")
    if len(scenes) != 5:
        raise RuntimeError(f"FCC retornou {len(scenes)} cenas; esperado: 5.")
    normalized_scenes = []
    for scene in scenes:
        title = clean(scene.get("titulo"))[:70]
        text = clean(scene.get("texto"))[:180]
        if not title or not text:
            raise RuntimeError("Uma das cenas veio incompleta.")
        normalized_scenes.append({"titulo": title, "texto": text})
    return {
        "versao": "24.0.1",
        "tema": clean(job.get("tema")) or clean(tema_original),
        "titulo": titulo[:110],
        "hook": hook[:240],
        "roteiro": roteiro,
        "voz": clean(job.get("voz")) or "pt-BR-AntonioNeural",
        "cta": clean(job.get("cta")) or "Segue o Zé Curioso para mais curiosidades rápidas.",
        "precisa_verificacao": bool(job.get("precisa_verificacao")),
        "cenas": normalized_scenes,
    }


def _find_recursive(data, keys):
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key).lower() in keys and isinstance(value, str) and value.strip():
                return value.strip()
        for value in data.values():
            found = _find_recursive(value, keys)
            if found:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _find_recursive(value, keys)
            if found:
                return found
    return None


def load_github_settings():
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    repo = DEFAULT_REPO
    for path in CONFIG_CANDIDATES:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not token:
            token = _find_recursive(data, {"github_token", "token_github", "gh_token", "token"})
        repo_found = _find_recursive(data, {"github_repo", "repo", "repository", "repositorio"})
        if repo_found and "/" in repo_found:
            repo = repo_found
    if not token:
        raise RuntimeError(
            "Token do GitHub não encontrado. Use o mesmo arquivo de configuração já usado pelo projeto antigo ou GITHUB_TOKEN no ambiente."
        )
    return token, repo


def gh_api(repo: str, token: str, path: str, method="GET", data=None, timeout=120):
    url = f"https://api.github.com/repos/{repo}{path}"
    status, body = http_json(
        url,
        method=method,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=timeout,
    )
    if status not in {200, 201, 202, 204}:
        raise RuntimeError(f"GitHub HTTP {status}: {str(body)[:900]}")
    return body


def upload_job(repo: str, token: str, job_id: str, job: dict):
    path = f"jobs/{job_id}/curiosidade.json"
    content = base64.b64encode(json.dumps(job, ensure_ascii=False, indent=2).encode("utf-8")).decode("ascii")
    gh_api(
        repo, token, f"/contents/{path}", method="PUT",
        data={
            "message": f"ze curioso v24 job {job_id}",
            "content": content,
            "branch": DEFAULT_BRANCH,
        },
    )
    return path


def dispatch(repo: str, token: str, job_id: str):
    gh_api(
        repo, token, f"/actions/workflows/{WORKFLOW}/dispatches", method="POST",
        data={"ref": DEFAULT_BRANCH, "inputs": {"job_id": job_id}},
    )


def find_run(repo: str, token: str, started_at: float, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        query = urllib.parse.urlencode({"branch": DEFAULT_BRANCH, "event": "workflow_dispatch", "per_page": 20})
        data = gh_api(repo, token, f"/actions/workflows/{WORKFLOW}/runs?{query}")
        runs = data.get("workflow_runs") or []
        for run in runs:
            created = str(run.get("created_at") or "")
            # O job_id não aparece no resumo; a janela temporal evita pegar runs antigos.
            if run.get("status") in {"queued", "in_progress", "completed"}:
                return int(run["id"])
        time.sleep(2)
    raise RuntimeError("Workflow do Zé Curioso não apareceu no GitHub.")


def wait_run(repo: str, token: str, run_id: int, timeout=1200):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = gh_api(repo, token, f"/actions/runs/{run_id}")
        status = run.get("status")
        conclusion = run.get("conclusion")
        emit(f"[>] Workflow {run_id}: {status}" + (f" / {conclusion}" if conclusion else ""))
        if status == "completed":
            if conclusion != "success":
                raise RuntimeError(f"Workflow terminou com conclusão: {conclusion}")
            return
        time.sleep(5)
    raise RuntimeError("Tempo de espera do render excedido.")


def download_artifact(repo: str, token: str, run_id: int, destination: Path):
    data = gh_api(repo, token, f"/actions/runs/{run_id}/artifacts")
    artifacts = data.get("artifacts") or []
    if not artifacts:
        raise RuntimeError("Workflow terminou sem artifact.")
    artifact = next((x for x in artifacts if str(x.get("name", "")).startswith("ze-curioso-v24-")), artifacts[0])
    artifact_id = artifact["id"]

    url = f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}/zip"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ze-curioso-v24",
    })
    zip_path = destination / "resultado.zip"
    with urllib.request.urlopen(req, timeout=120) as resp:
        zip_path.write_bytes(resp.read())
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(destination)
    zip_path.unlink(missing_ok=True)


def cleanup_job(repo: str, token: str, remote_path: str):
    try:
        data = gh_api(repo, token, f"/contents/{remote_path}?ref={urllib.parse.quote(DEFAULT_BRANCH)}")
        sha = data.get("sha")
        if sha:
            gh_api(
                repo, token, f"/contents/{remote_path}", method="DELETE",
                data={"message": f"cleanup {remote_path}", "sha": sha, "branch": DEFAULT_BRANCH},
            )
    except Exception as exc:
        emit(f"[!] Não consegui limpar o job remoto: {exc}")


def main():
    ap = argparse.ArgumentParser(description="Zé Curioso Studio V24")
    ap.add_argument("tema", nargs="*", help="tema ou pergunta da curiosidade")
    ap.add_argument("--somente-json", action="store_true", help="gera o roteiro com FCC sem disparar render")
    args = ap.parse_args()
    tema = clean(" ".join(args.tema))
    if not tema:
        tema = clean(input("Tema/curiosidade: "))
    if not tema:
        raise SystemExit("Nenhum tema informado.")

    job = fcc_generate_topic(tema)
    root = Path.cwd() / "saida_ze_curioso" / slugify(job["titulo"])
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / "curiosidade.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    emit(f"[OK] Roteiro FCC salvo em {root / 'curiosidade.json'}")

    if job.get("precisa_verificacao"):
        emit("[!] O FCC marcou este tema como dependente de verificação factual. Revise antes de publicar.")

    if args.somente_json:
        return

    token, repo = load_github_settings()
    job_id = uuid.uuid4().hex
    remote_path = upload_job(repo, token, job_id, job)
    started = time.time()
    try:
        emit("[>] Disparando render na nuvem...")
        dispatch(repo, token, job_id)
        run_id = find_run(repo, token, started)
        wait_run(repo, token, run_id)
        emit("[>] Baixando resultado...")
        download_artifact(repo, token, run_id, root)
        final = root / "anuncio_final.mp4"
        if not final.is_file():
            raise RuntimeError("Artifact baixado, mas anuncio_final.mp4 não foi encontrado.")
        emit(f"[OK] ZÉ CURIOSO PRONTO: {final}")
    finally:
        cleanup_job(repo, token, remote_path)


if __name__ == "__main__":
    main()
