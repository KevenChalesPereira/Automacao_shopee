#!/usr/bin/env python3
"""Zé Curioso Studio — controle remoto leve para Linux Mint.

O computador local não renderiza vídeo. Ele dispara e acompanha o GitHub Actions,
e baixa o MP4/artifact pronto.

Template final travado:
- visual vertical 1080x1920;
- grupos fixos de até 3 palavras no balão;
- apenas a palavra falada fica destacada;
- um único POP do balão por grupo;
- voz selecionada pelo fingerprint aprovado;
- bordão: "Eu sou o Zé Curioso. E aqui... parece mentira, mas é real."

Comandos que já operam o renderer final:
- `template`: dispara um render real do template travado;
- `status`: mostra o render mais recente;
- `baixar`: baixa o último artifact final aprovado.

`tema` e `auto` continuam registrando a solicitação editorial sem fingir que o
renderer fixo do sapo já é dinâmico. Eles são a interface estável para a próxima
camada (pesquisa/roteiro/imagens dinâmicos).
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
WORKFLOW_ID = 359194374
REQUEST_DIR = Path("studio_requests")
RESULT_DIR = Path("ze_resultados")
TEMPLATE = "ze-final-simple-pop-voice-lock"
ARTIFACT_PREFIX = "ze-postavel-FINAL-VOICELOCK-"
ISSUE_PREFIX = "[Gerar postável final]"
POLL_SECONDS = 20


def token() -> str:
    value = os.environ.get("GITHUB_TOKEN", "").strip()
    if value:
        return value

    # No Linux, se o usuário já fez `gh auth login`, não precisa exportar o token.
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
        "Falta autenticação do GitHub. Use `gh auth login` ou exporte GITHUB_TOKEN "
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


def workflow_runs(per_page: int = 20) -> list[dict]:
    payload = api_request(
        f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW_ID}/runs?per_page={per_page}"
    )
    return payload.get("workflow_runs", [])


def run_artifacts(run_id: int) -> list[dict]:
    return api_request(
        f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/artifacts?per_page=100"
    ).get("artifacts", [])


def final_artifact_for_run(run_id: int) -> dict | None:
    for artifact in run_artifacts(run_id):
        if not artifact.get("expired") and artifact.get("name", "").startswith(ARTIFACT_PREFIX):
            return artifact
    return None


def latest_final_success() -> tuple[dict, dict]:
    for run in workflow_runs(40):
        if run.get("conclusion") != "success":
            continue
        artifact = final_artifact_for_run(int(run["id"]))
        if artifact:
            return run, artifact
    raise SystemExit("Ainda não encontrei um artifact FINAL VOICELOCK aprovado e não expirado.")


def newest_run_after(created_at: str) -> dict | None:
    for run in workflow_runs(20):
        if run.get("created_at", "") >= created_at and str(run.get("display_title", "")).startswith(ISSUE_PREFIX):
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

    mp4s = sorted(run_dir.glob("**/*.mp4"))
    print(f"Artifact: {artifact['name']}")
    print(f"Pasta: {run_dir.resolve()}")
    if not mp4s:
        raise SystemExit("Artifact baixado, mas nenhum MP4 foi localizado dentro dele.")
    print(f"Vídeo: {mp4s[0].resolve()}")
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
                raise SystemExit(f"Render terminou com: {run.get('conclusion')}. Veja {run.get('html_url')}")
            return run
        time.sleep(POLL_SECONDS)


def save_request(mode: str, theme: str | None) -> Path:
    REQUEST_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "version": 2,
        "mode": mode,
        "theme": theme,
        "language": "pt-BR",
        "template": TEMPLATE,
        "editorial_prompt": "prompts/ze_curioso_master.md",
        "final_signoff": "Eu sou o Zé Curioso. E aqui... parece mentira, mas é real.",
        "status": "editorial-request-created",
        "renderer_dynamic": False,
    }
    path = REQUEST_DIR / f"request_{stamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def cmd_template(args: argparse.Namespace) -> None:
    before = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    issue = github_issue(
        f"{ISSUE_PREFIX} Zé Curioso — FINAL VOICELOCK pelo launcher",
        "Solicitação enviada por `ze_studio.py template`. Renderizar exatamente o template final travado: "
        "POP simples aprovado + seleção de voz por fingerprint.",
    )
    print(f"Render solicitado: {issue['html_url']}")

    if not args.aguardar:
        return

    run = None
    for _ in range(18):
        run = newest_run_after(before)
        if run:
            break
        time.sleep(5)
    if not run:
        raise SystemExit("Issue criada, mas o run ainda não apareceu no GitHub Actions.")

    run = wait_for_run(int(run["id"]))
    artifact = final_artifact_for_run(int(run["id"]))
    if not artifact:
        raise SystemExit("Run passou, mas o artifact final não foi encontrado.")
    download_artifact(run, artifact)


def cmd_status(args: argparse.Namespace) -> None:
    if args.run_id:
        run = api_request(f"https://api.github.com/repos/{REPO}/actions/runs/{args.run_id}")
    else:
        runs = workflow_runs(10)
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


def cmd_baixar(args: argparse.Namespace) -> None:
    if args.run_id:
        run = api_request(f"https://api.github.com/repos/{REPO}/actions/runs/{args.run_id}")
        if run.get("conclusion") != "success":
            raise SystemExit("Esse run não terminou com sucesso.")
        artifact = final_artifact_for_run(int(run["id"]))
        if not artifact:
            raise SystemExit("Esse run não possui artifact FINAL VOICELOCK disponível.")
    else:
        run, artifact = latest_final_success()
    download_artifact(run, artifact)


def cmd_tema(args: argparse.Namespace) -> None:
    path = save_request("manual", args.tema)
    print(f"Solicitação editorial criada: {path}")
    print("O template audiovisual/voz já está travado. A camada dinâmica de pesquisa/roteiro/imagens ainda será conectada a este request.")


def cmd_auto(_: argparse.Namespace) -> None:
    path = save_request("auto", None)
    print(f"Solicitação AUTO criada: {path}")
    print("O template audiovisual/voz já está travado. A seleção/pesquisa automática de assunto ainda será conectada a este request.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Zé Curioso Studio — controle remoto do pipeline em nuvem")
    sub = parser.add_subparsers(dest="command", required=True)

    p_template = sub.add_parser("template", help="dispara o template final VOICELOCK no GitHub Actions")
    p_template.add_argument("--aguardar", action="store_true", help="acompanha o run e baixa o MP4 quando terminar")
    p_template.set_defaults(func=cmd_template)

    p_status = sub.add_parser("status", help="mostra o último render ou um run específico")
    p_status.add_argument("run_id", nargs="?", type=int)
    p_status.set_defaults(func=cmd_status)

    p_download = sub.add_parser("baixar", help="baixa o último artifact final ou um run específico")
    p_download.add_argument("run_id", nargs="?", type=int)
    p_download.set_defaults(func=cmd_baixar)

    p_tema = sub.add_parser("tema", help="registra uma solicitação para tema manual")
    p_tema.add_argument("tema", help="assunto desejado")
    p_tema.set_defaults(func=cmd_tema)

    p_auto = sub.add_parser("auto", help="registra uma solicitação para seleção automática de tema")
    p_auto.set_defaults(func=cmd_auto)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
