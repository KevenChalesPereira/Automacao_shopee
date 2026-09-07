#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys, time
from pathlib import Path


def run(cmd, cwd=None, env=None, check=True):
    print('[cpu-creator] > ' + ' '.join(str(x) for x in cmd), flush=True)
    p = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace')
    print(p.stdout[-12000:], flush=True)
    if check and p.returncode != 0:
        raise RuntimeError(f'Comando falhou ({p.returncode}): {cmd[0]}')
    return p


def ensure_runtime(root: Path):
    repo = root / 'SadTalker'
    venv = root / 'venv'
    marker = root / '.ready_v20_3'
    root.mkdir(parents=True, exist_ok=True)

    if not repo.is_dir():
        run(['git','clone','--depth','1','https://github.com/OpenTalker/SadTalker.git', str(repo)])

    if not venv.is_dir():
        run([sys.executable, '-m', 'venv', str(venv)])

    py = venv / 'bin' / 'python'
    pip = venv / 'bin' / 'pip'

    if not marker.is_file():
        run([str(py), '-m', 'pip', 'install', '--upgrade', 'pip', 'setuptools', 'wheel'])
        run([str(pip), 'install', '--index-url', 'https://download.pytorch.org/whl/cpu',
             'torch==2.0.1+cpu', 'torchvision==0.15.2+cpu', 'torchaudio==2.0.2+cpu'])
        # CLI-only dependencies; avoids installing the optional TTS stack.
        run([str(pip), 'install', '-r', str(repo/'requirements.txt')])
        marker.write_text('ready\n', encoding='utf-8')

    checkpoints = repo / 'checkpoints'
    needed = checkpoints / 'SadTalker_V0.0.2_256.safetensors'
    if not needed.is_file():
        run(['bash', 'scripts/download_models.sh'], cwd=repo)

    return repo, py


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--image', required=True)
    ap.add_argument('--audio', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--info-output', required=True)
    ap.add_argument('--runtime-dir', default='')
    args = ap.parse_args()

    image = Path(args.image).resolve()
    audio = Path(args.audio).resolve()
    output = Path(args.output).resolve()
    info_path = Path(args.info_output).resolve()
    runtime = Path(args.runtime_dir).expanduser().resolve() if args.runtime_dir else Path.home()/'.cache'/'shopee-sadtalker-cpu'
    result_dir = output.parent / '_sadtalker_cpu_results'
    result_dir.mkdir(parents=True, exist_ok=True)

    info = {
        'ok': False,
        'engine': 'sadtalker_cpu_github_actions',
        'runtime_dir': str(runtime),
        'note': 'Fallback CPU executado no GitHub Actions; é mais lento, mas não depende de quota ZeroGPU.'
    }
    started = time.time()
    try:
        repo, py = ensure_runtime(runtime)
        cmd = [
            str(py), 'inference.py',
            '--driven_audio', str(audio),
            '--source_image', str(image),
            '--result_dir', str(result_dir),
            '--checkpoint_dir', str(repo/'checkpoints'),
            '--size', '256',
            '--preprocess', 'crop',
            '--batch_size', '1',
            '--expression_scale', '1.05',
            '--cpu',
        ]
        run(cmd, cwd=repo)
        candidates = sorted(result_dir.glob('*.mp4'), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            candidates = sorted(result_dir.rglob('*.mp4'), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            raise RuntimeError('SadTalker CPU terminou sem gerar MP4.')
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidates[0], output)
        info['ok'] = output.is_file() and output.stat().st_size > 20000
        info['output_bytes'] = output.stat().st_size if output.is_file() else 0
    except Exception as exc:
        info['error'] = str(exc)
    info['elapsed_seconds'] = round(time.time() - started, 1)
    info_path.parent.mkdir(parents=True, exist_ok=True)
    info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(info, ensure_ascii=False), flush=True)
    return 0 if info.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
