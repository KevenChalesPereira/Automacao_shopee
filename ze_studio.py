#!/usr/bin/env python3
"""Zé Curioso Studio — launcher leve para Linux Mint.

O PC local é só controle. Pesquisa, voz, Whisper, render e FFmpeg rodam no
GitHub Actions.

Comandos principais:
  python3 ze_studio.py tema "axolote"
  python3 ze_studio.py auto

Por padrão `tema` e `auto` esperam o GitHub Actions terminar e baixam o MP4.
Use `--nao-aguardar` para apenas disparar o job.

Template aprovado:
- 1080x1920;
- grupos de até 3 palavras no balão do Zé;
- palavra falada destacada;
- POP do balão por grupo;
- voz VoxCPM2 com seleção por fingerprint;
- bordão: "Eu sou o Zé Curioso. E aqui... parece mentira, mas é real."

Pendência não bloqueante: endurecer depois o QA contra rouquidão/aspereza.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO = "KevenChalesPereira/Automacao_shopee"
FINAL_WORKFLOW = "ze_postavel_final.yml"
DYNAMIC_WORKFLOW = "ze_studio_dynamic.yml"
REQUEST_DIR = Path("studio_requests")
RESULT_DIR = Path("ze_resultados")
TEMPLATE = "ze-final-simple-pop-voice-lock"
FINAL_ARTIFACT_PREFIX = "ze-postavel-FINAL-VOICELOCK-"
DYNAMIC_ARTIFACT_PREFIX = "ze-studio-DYNAMIC-"
FINAL_ISSUE_PREFIX = "[Gerar postável final]"
DYNAMIC_ISSUE_PREFIX = "[Gerar Zé dinâmico]"
POLL_SECONDS = 20


def token() -> str:
    value = os.environ.get("GITHUB_TOKEN", "").strip()
    if value:
        return value
    try:
        proc = subprocess.run(
            ["gh", "auth", "token"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
        value = proc.stdout.strip()
        if value:
            return value
    except (OSError, subprocess.SubprocessError):
        pass
    raise SystemExit(
        "Falta autenticação do GitHub. Rode `gh auth login` ou exporte GITHUB_TOKEN "
        "com Issues:write e Actions:read."
    )


def api_request(url: str, *, method: str = "GET", payload: dict | None = None, binary: bool = False):
    headers = {
        "Authorization": f"Bearer {token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ze-curioso-studio",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"GitHub recusou a solicitação ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Falha de conexão com o GitHub: {exc}") from exc
    return raw if binary else json.loads(raw.decode("utf-8"))


def github_issue(title: str, body: str) -> dict:
    return api_request(
        f"https://api.github.com/repos/{REPO}/issues",
        method="POST",
        payload={"title": title, "body": body},
    )


def workflow_runs(workflow: str, per_page: int = 20) -> list[dict]:
    payload = api_request(
        f"https://api.github.com/repos/{REPO}/actions/workflows/{workflow}/runs?per_page={per_page}"
    )
    return payload.get("workflow_runs", [])


def run_artifacts(run_id: int) -> list[dict]:
    return api_request(
        f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/artifacts?per_page=100"
    ).get("artifacts", [])


def artifact_for_run(run_id: int, prefix: str) -> dict | None:
    for artifact in run_artifacts(run_id):
        if not artifact.get("expired") and artifact.get("name", "").startswith(prefix):
            return artifact
    return None


def latest_success(workflow: str, prefix: str) -> tuple[dict, dict]:
    for run in workflow_runs(workflow, 40):
        if run.get("conclusion") != "success":
            continue
        artifact = artifact_for_run(int(run["id"]), prefix)
        if artifact:
            return run, artifact
    raise SystemExit(f"Ainda não encontrei artifact disponível com prefixo {prefix}")


def newest_matching_run(workflow: str, created_at: str, title_fragment: str) -> dict | None:
    for run in workflow_runs(workflow, 20):
        if run.get("created_at", "") < created_at:
            continue
        if title_fragment in str(run.get("display_title", "")):
            return run
    return None


def download_artifact(run: dict, artifact: dict) -> Path:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = RESULT_DIR / f"run_{run['id']}"
    run_dir.mkdir(parents=True, exist_ok=True)
    zip_path = run_dir / f"{artifact['name']}.zip"
    data = api_request(
        f"https://api.github.com/repos/{REPO}/actions/artifacts/{artifact['id']}/zip",
        binary=True,
    )
    zip_path.write_bytes(data)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(run_dir)

    preferred = list(run_dir.glob("**/ze_curioso_final.mp4"))
    mp4s = preferred or sorted(run_dir.glob("**/*.mp4"))
    print(f"Artifact: {artifact['name']}")
    print(f"Pasta: {run_dir.resolve()}")
    if not mp4s:
        raise SystemExit("Artifact baixado, mas nenhum MP4 foi localizado.")
    print(f"Vídeo pronto: {mp4s[0].resolve()}")
    return mp4s[0]


def wait_for_run(run_id: int) -> dict:
    print(f"Acompanhando run {run_id}...")
    last = None
    while True:
        run = api_request(f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}")
        state = (run.get("status"), run.get("conclusion"))
        if state != last:
            print(f"Status: {state[0]} | conclusão: {state[1] or '-'}")
            last = state
        if run.get("status") == "completed":
            if run.get("conclusion") != "success":
                raise SystemExit(f"Render terminou com {run.get('conclusion')}. Veja {run.get('html_url')}")
            return run
        time.sleep(POLL_SECONDS)


def make_request(mode: str, theme: str | None) -> tuple[dict, Path]:
    REQUEST_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    request_id = f"{stamp}-{mode}"
    payload = {
        "version": 3,
        "request_id": request_id,
        "mode": mode,
        "theme": theme,
        "language": "pt-BR",
        "template": TEMPLATE,
        "editorial_prompt": "prompts/ze_curioso_master.md",
        "final_signoff": "Eu sou o Zé Curioso. E aqui... parece mentira, mas é real.",
        "voice_roughness_correction": "todo-nonblocking",
        "renderer_dynamic": True,
    }
    path = REQUEST_DIR / f"request_{request_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload, path


def submit_dynamic(mode: str, theme: str | None, *, wait: bool) -> None:
    payload, path = make_request(mode, theme)
    before = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    rid = payload["request_id"]
    label = theme if theme else "AUTO"
    issue = github_issue(
        f"{DYNAMIC_ISSUE_PREFIX} {rid} — {label}",
        json.dumps(payload, ensure_ascii=False),
    )
    print(f"Request: {path}")
    print(f"Job solicitado: {issue['html_url']}")
    if not wait:
        print("Use `python3 ze_studio.py status-dinamico` para acompanhar.")
        return

    run = None
    for _ in range(24):
        run = newest_matching_run(DYNAMIC_WORKFLOW, before, rid)
        if run:
            break
        time.sleep(5)
    if not run:
        raise SystemExit("Issue criada, mas o workflow dinâmico ainda não apareceu.")

    run = wait_for_run(int(run["id"]))
    artifact = artifact_for_run(int(run["id"]), DYNAMIC_ARTIFACT_PREFIX)
    if not artifact:
        raise SystemExit("Workflow passou, mas o artifact dinâmico não foi encontrado.")
    download_artifact(run, artifact)


def cmd_template(args: argparse.Namespace) -> None:
    before = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    marker = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    issue = github_issue(
        f"{FINAL_ISSUE_PREFIX} template {marker}",
        "Renderizar exatamente o template final travado: POP aprovado + VOICELOCK.",
    )
    print(f"Render solicitado: {issue['html_url']}")
    if not args.aguardar:
        return
    run = None
    for _ in range(18):
        run = newest_matching_run(FINAL_WORKFLOW, before, marker)
        if run:
            break
        time.sleep(5)
    if not run:
        raise SystemExit("Issue criada, mas o run não apareceu.")
    run = wait_for_run(int(run["id"]))
    artifact = artifact_for_run(int(run["id"]), FINAL_ARTIFACT_PREFIX)
    if not artifact:
        raise SystemExit("Run passou, mas o artifact final não foi encontrado.")
    download_artifact(run, artifact)


def show_status(workflow: str, run_id: int | None) -> None:
    if run_id:
        run = api_request(f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}")
    else:
        runs = workflow_runs(workflow, 10)
        if not runs:
            print("Nenhum render encontrado.")
            return
        run = runs[0]
    print(f"Run: {run['id']}")
    print(f"Título: {run.get('display_title', '-')}")
    print(f"Status: {run.get('status', '-')}")
    print(f"Conclusão: {run.get('conclusion') or 'ainda executando'}")
    print(f"Commit: {run.get('head_sha', '-')}")
    print(f"GitHub: {run.get('html_url', '-')}")


def cmd_status(args: argparse.Namespace) -> None:
    show_status(FINAL_WORKFLOW, args.run_id)


def cmd_status_dynamic(args: argparse.Namespace) -> None:
    show_status(DYNAMIC_WORKFLOW, args.run_id)


def cmd_baixar(args: argparse.Namespace) -> None:
    if args.run_id:
        run = api_request(f"https://api.github.com/repos/{REPO}/actions/runs/{args.run_id}")
        artifact = artifact_for_run(int(run["id"]), FINAL_ARTIFACT_PREFIX)
        if not artifact:
            raise SystemExit("Esse run não possui artifact FINAL VOICELOCK.")
    else:
        run, artifact = latest_success(FINAL_WORKFLOW, FINAL_ARTIFACT_PREFIX)
    download_artifact(run, artifact)


def cmd_baixar_dynamic(args: argparse.Namespace) -> None:
    if args.run_id:
        run = api_request(f"https://api.github.com/repos/{REPO}/actions/runs/{args.run_id}")
        artifact = artifact_for_run(int(run["id"]), DYNAMIC_ARTIFACT_PREFIX)
        if not artifact:
            raise SystemExit("Esse run não possui artifact dinâmico.")
    else:
        run, artifact = latest_success(DYNAMIC_WORKFLOW, DYNAMIC_ARTIFACT_PREFIX)
    download_artifact(run, artifact)


def cmd_tema(args: argparse.Namespace) -> None:
    submit_dynamic("manual", args.tema, wait=not args.nao_aguardar)


def cmd_auto(args: argparse.Namespace) -> None:
    submit_dynamic("auto", None, wait=not args.nao_aguardar)


def main() -> None:
    parser = argparse.ArgumentParser(description="Zé Curioso Studio — pipeline em nuvem")
    sub = parser.add_subparsers(dest="command", required=True)

    p_tema = sub.add_parser("tema", help="gera um vídeo completo a partir de um tema")
    p_tema.add_argument("tema", help="tema desejado, ex.: axolote")
    p_tema.add_argument("--nao-aguardar", action="store_true", help="apenas dispara o job")
    p_tema.set_defaults(func=cmd_tema)

    p_auto = sub.add_parser("auto", help="escolhe um tema automaticamente e gera o vídeo")
    p_auto.add_argument("--nao-aguardar", action="store_true", help="apenas dispara o job")
    p_auto.set_defaults(func=cmd_auto)

    p_template = sub.add_parser("template", help="renderiza o template fixo aprovado")
    p_template.add_argument("--aguardar", action="store_true")
    p_template.set_defaults(func=cmd_template)

    p_status = sub.add_parser("status", help="status do renderer fixo")
    p_status.add_argument("run_id", nargs="?", type=int)
    p_status.set_defaults(func=cmd_status)

    p_status_d = sub.add_parser("status-dinamico", help="status do último episódio dinâmico")
    p_status_d.add_argument("run_id", nargs="?", type=int)
    p_status_d.set_defaults(func=cmd_status_dynamic)

    p_download = sub.add_parser("baixar", help="baixa o último template fixo")
    p_download.add_argument("run_id", nargs="?", type=int)
    p_download.set_defaults(func=cmd_baixar)

    p_download_d = sub.add_parser("baixar-dinamico", help="baixa o último episódio dinâmico")
    p_download_d.add_argument("run_id", nargs="?", type=int)
    p_download_d.set_defaults(func=cmd_baixar_dynamic)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
