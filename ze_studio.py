#!/usr/bin/env python3
"""Zé Curioso Studio — controle remoto leve para Linux Mint.

O PC não renderiza vídeo: ele dispara/acompanha o GitHub Actions e baixa os
resultados. A etapa pesada continua na nuvem.

Estado atual:
- `template`: dispara o template audiovisual V6.4.
- `status`: mostra o último render do pipeline final.
- `baixar`: baixa o artifact V6.4 aprovado mais recente.
- `tema` e `auto`: criam requests editoriais para a próxima camada dinâmica;
  não fingem que o renderer atual já troca o assunto sozinho.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO = "KevenChalesPereira/Automacao_shopee"
WORKFLOW_ID = 359194374
REQUEST_DIR = Path("studio_requests")
RESULT_DIR = Path("ze_resultados")
TEMPLATE = "ze-v6.4-locked"
ARTIFACT_PREFIX = "ze-postavel-LOCKED-v6-4-"


def token() -> str:
    value = os.environ.get("GITHUB_TOKEN", "").strip()
    if not value:
        raise SystemExit(
            "Falta GITHUB_TOKEN. Exporte um token do GitHub com Issues:write e Actions:read."
        )
    return value


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
    return raw if binary else json.loads(raw.decode("utf-8"))


def save_request(mode: str, theme: str | None) -> Path:
    REQUEST_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "version": 1,
        "mode": mode,
        "theme": theme,
        "language": "pt-BR",
        "template": TEMPLATE,
        "editorial_prompt": "prompts/ze_curioso_master.md",
        "status": "editorial-request-created",
        "note": "Dynamic topic workflow is the next milestone; current locked renderer is still the wood-frog template test.",
    }
    path = REQUEST_DIR / f"request_{stamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def github_issue(title: str, body: str) -> str:
    payload = api_request(
        f"https://api.github.com/repos/{REPO}/issues",
        method="POST",
        payload={"title": title, "body": body},
    )
    return payload["html_url"]


def workflow_runs(per_page: int = 20) -> list[dict]:
    payload = api_request(
        f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW_ID}/runs?per_page={per_page}"
    )
    return payload.get("workflow_runs", [])


def latest_v64_success() -> tuple[dict, dict]:
    for run in workflow_runs(30):
        if run.get("conclusion") != "success":
            continue
        artifacts = api_request(
            f"https://api.github.com/repos/{REPO}/actions/runs/{run['id']}/artifacts?per_page=100"
        ).get("artifacts", [])
        for artifact in artifacts:
            if not artifact.get("expired") and artifact.get("name", "").startswith(ARTIFACT_PREFIX):
                return run, artifact
    raise SystemExit("Ainda não encontrei um artifact V6.4 aprovado e não expirado.")


def cmd_template(_: argparse.Namespace) -> None:
    url = github_issue(
        "[Gerar postável final] Zé Curioso — template V6.4 pelo launcher",
        "Solicitação enviada por `ze_studio.py template`. Renderizar o template audiovisual travado V6.4.",
    )
    print(f"Render disparado: {url}")


def cmd_status(_: argparse.Namespace) -> None:
    runs = workflow_runs(5)
    if not runs:
        print("Nenhum render encontrado.")
        return
    run = runs[0]
    print(f"Run: {run['id']}")
    print(f"Título: {run.get('display_title', '-')}")
    print(f"Status: {run.get('status', '-')}")
    print(f"Conclusão: {run.get('conclusion') or 'ainda executando'}")
    print(f"GitHub: {run.get('html_url', '-')}")


def cmd_baixar(_: argparse.Namespace) -> None:
    run, artifact = latest_v64_success()
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
    if mp4s:
        print(f"Vídeo: {mp4s[0].resolve()}")
    else:
        print("Artifact baixado, mas nenhum MP4 foi localizado dentro dele.")


def cmd_tema(args: argparse.Namespace) -> None:
    path = save_request("manual", args.tema)
    print(f"Solicitação editorial criada: {path}")
    print("Próximo milestone: conectar esse JSON ao workflow dinâmico. O renderer atual ainda NÃO troca o tema sozinho.")


def cmd_auto(_: argparse.Namespace) -> None:
    path = save_request("auto", None)
    print(f"Solicitação AUTO criada: {path}")
    print("Ela aponta para prompts/ze_curioso_master.md. O pesquisador/editor dinâmico será a próxima camada do pipeline.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Zé Curioso Studio — controle remoto do pipeline em nuvem")
    sub = parser.add_subparsers(dest="command", required=True)

    p_template = sub.add_parser("template", help="dispara o template V6.4 atual no GitHub Actions")
    p_template.set_defaults(func=cmd_template)

    p_status = sub.add_parser("status", help="mostra o último render do workflow final")
    p_status.set_defaults(func=cmd_status)

    p_download = sub.add_parser("baixar", help="baixa e extrai o último artifact V6.4 aprovado")
    p_download.set_defaults(func=cmd_baixar)

    p_tema = sub.add_parser("tema", help="cria uma solicitação para tema manual")
    p_tema.add_argument("tema", help="assunto desejado")
    p_tema.set_defaults(func=cmd_tema)

    p_auto = sub.add_parser("auto", help="cria uma solicitação para escolha automática de tema")
    p_auto.set_defaults(func=cmd_auto)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
