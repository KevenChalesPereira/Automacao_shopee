#!/usr/bin/env python3
"""Zé Curioso Studio — launcher leve para Linux Mint.

O PC só cria/dispara solicitações. Render pesado permanece no GitHub Actions.

Estado atual:
- `template`: dispara o template final travado.
- `tema` e `auto`: montam a solicitação editorial local em JSON, pronta para o
  próximo workflow dinâmico. Não fingem que o renderer atual já troca o tema.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = "KevenChalesPereira/Automacao_shopee"
REQUEST_DIR = Path("studio_requests")
TEMPLATE = "ze-v6.4-locked"


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
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "Falta GITHUB_TOKEN. No Linux, exporte um token com permissão de Issues antes de disparar o GitHub."
        )
    data = json.dumps({"title": title, "body": body}).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/issues",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ze-curioso-studio",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"GitHub recusou a solicitação ({exc.code}): {detail}") from exc
    return payload["html_url"]


def cmd_template(_: argparse.Namespace) -> None:
    url = github_issue(
        "[Gerar postável final] Zé Curioso — template V6.4 pelo launcher",
        "Solicitação enviada por `ze_studio.py template`. Renderizar o template audiovisual travado V6.4.",
    )
    print(f"Render disparado: {url}")


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

    p_tema = sub.add_parser("tema", help="cria uma solicitação para tema manual")
    p_tema.add_argument("tema", help="assunto desejado")
    p_tema.set_defaults(func=cmd_tema)

    p_auto = sub.add_parser("auto", help="cria uma solicitação para escolha automática de tema")
    p_auto.set_defaults(func=cmd_auto)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
