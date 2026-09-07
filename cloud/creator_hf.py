#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cria a referência visual do Creator IA via Hugging Face.

Na V20.3 os endpoints ZeroGPU de talking-head são opcionais, porque os Spaces
públicos observados estavam solicitando uma duração de GPU acima do limite.
O vídeo falante confiável é gerado pelo fallback SadTalker CPU no GitHub Actions.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
import traceback
from pathlib import Path


def log(msg):
    print(msg, flush=True)


def _client(space, download_dir):
    from gradio_client import Client
    token = (os.getenv('HF_TOKEN') or '').strip() or None
    kwargs = {'download_files': str(download_dir), 'verbose': False}
    if token:
        # Gradio 6 usa token; versões antigas usavam hf_token.
        try:
            return Client(space, token=token, **kwargs)
        except TypeError:
            return Client(space, hf_token=token, **kwargs)
    return Client(space, **kwargs)


def _file(path):
    try:
        from gradio_client import file
        return file(str(path))
    except Exception:
        from gradio_client import handle_file
        return handle_file(str(path))


def _extract_paths(value):
    out = []
    if value is None:
        return out
    if isinstance(value, (str, Path)):
        out.append(str(value))
        return out
    if isinstance(value, dict):
        for key in ('path', 'name', 'url', 'video', 'image'):
            if value.get(key):
                out.extend(_extract_paths(value[key]))
        for v in value.values():
            if isinstance(v, (dict, list, tuple)):
                out.extend(_extract_paths(v))
        return out
    if isinstance(value, (list, tuple)):
        for item in value:
            out.extend(_extract_paths(item))
        return out
    for attr in ('path', 'name', 'url'):
        candidate = getattr(value, attr, None)
        if candidate:
            out.extend(_extract_paths(candidate))
    return out


def _copy_result(value, destination, allowed_exts):
    destination = Path(destination)
    for raw in _extract_paths(value):
        p = Path(raw)
        if p.is_file() and p.suffix.lower() in allowed_exts and p.stat().st_size > 5000:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, destination)
            return True
    return False


def generate_creator_image(prompt, destination, temp_dir):
    log('[creator] Gerando pessoa sintética no FLUX ZeroGPU...')
    client = _client('black-forest-labs/FLUX.1-schnell', temp_dir)
    attempts = [
        lambda: client.predict(prompt, 0, True, 768, 768, 4, api_name='/infer'),
        lambda: client.predict(prompt=prompt, seed=0, randomize_seed=True, width=768, height=768, num_inference_steps=4, api_name='/infer'),
        lambda: client.predict(prompt, 0, True, 768, 768, 4),
    ]
    last = None
    for fn in attempts:
        try:
            result = fn()
            if _copy_result(result, destination, {'.png', '.jpg', '.jpeg', '.webp'}):
                log('[creator] Imagem do creator criada.')
                return True
        except Exception as exc:
            last = exc
            log(f'[creator] FLUX tentativa falhou: {exc}')
    if last:
        raise RuntimeError(f'FLUX não gerou imagem utilizável: {last}')
    return False


def try_echomimic_v2(image, audio, destination, temp_dir):
    log('[creator] Tentando EchoMimicV2 Accelerated (meio corpo)...')
    client = _client('henrybit/EchoMimicV2-Accelerated', temp_dir)
    # 96 frames / 24fps ~= 4 s: melhor compromisso com quota gratuita.
    attempts = []
    for pose in ('good', '01', '02'):
        attempts.extend([
            lambda pose=pose: client.predict(_file(image), _file(audio), pose, 96, -1, api_name='/generate'),
            lambda pose=pose: client.predict(_file(image), _file(audio), pose, 96, -1),
        ])
    last = None
    for fn in attempts:
        try:
            result = fn()
            if _copy_result(result, destination, {'.mp4', '.mov', '.webm', '.m4v'}):
                return {'ok': True, 'engine': 'echomimic_v2_accelerated'}
        except Exception as exc:
            last = exc
            log(f'[creator] EchoMimicV2 falhou nesta tentativa: {exc}')
    return {'ok': False, 'engine': 'echomimic_v2_accelerated', 'error': str(last or 'sem saída')}


def try_echomimic_v1(image, audio, destination, temp_dir):
    log('[creator] Tentando EchoMimic V1 (fallback retrato)...')
    client = _client('fffiloni/EchoMimic', temp_dir)
    args = [
        _file(image), _file(audio),
        512, 512, 100, random.randint(1, 9999),
        0.10, 0.50, 12, 3, 2.5, 12, 16000, 24, 'cuda'
    ]
    last = None
    for api_name in ('/generate_video', None):
        try:
            if api_name:
                result = client.predict(*args, api_name=api_name)
            else:
                result = client.predict(*args)
            if _copy_result(result, destination, {'.mp4', '.mov', '.webm', '.m4v'}):
                return {'ok': True, 'engine': 'echomimic_v1'}
        except Exception as exc:
            last = exc
            log(f'[creator] EchoMimic V1 falhou: {exc}')
    return {'ok': False, 'engine': 'echomimic_v1', 'error': str(last or 'sem saída')}



def try_wan_latentsync(image, audio, destination, temp_dir):
    """Fallback mais natural: Wan 2.2 anima o creator e LatentSync sincroniza a boca."""
    log('[creator] Tentando Wan 2.2 I2V + LatentSync...')
    motion = Path(temp_dir) / 'wan_creator_motion.mp4'
    try:
        wan = _client('zerogpu-aoti/wan2-2-fp8da-aoti-faster', temp_dir)
        prompt = (
            'realistic Brazilian social media creator speaking directly to camera, half body, '
            'natural hand gestures, subtle head movement, friendly persuasive ecommerce presentation, '
            'smartphone UGC video, realistic body motion, steady face identity, no text, no logos, '
            'no product appearing in hands, natural blinking, natural shoulders and arms'
        )
        negative = (
            'distorted face, extra fingers, deformed hands, duplicate person, text, watermark, '
            'camera shake, identity change, warped mouth, frozen pose, low quality'
        )
        result = wan.predict(
            _file(image), prompt, 4, negative, 3.5, 1.0, 1.0, 42, True,
            api_name='/generate_video'
        )
        if not _copy_result(result, motion, {'.mp4', '.mov', '.webm', '.m4v'}):
            return {'ok': False, 'engine': 'wan2.2_latentsync', 'error': 'Wan 2.2 não devolveu vídeo'}
    except Exception as exc:
        log(f'[creator] Wan 2.2 falhou: {exc}')
        return {'ok': False, 'engine': 'wan2.2_latentsync', 'error': f'Wan: {exc}'}

    try:
        lipsync = _client('fffiloni/LatentSync', temp_dir)
        result = lipsync.predict(
            _file(motion), _file(audio),
            api_name='/generate_lip_sync_video'
        )
        if _copy_result(result, destination, {'.mp4', '.mov', '.webm', '.m4v'}):
            return {'ok': True, 'engine': 'wan2.2_latentsync'}
        return {'ok': False, 'engine': 'wan2.2_latentsync', 'error': 'LatentSync não devolveu vídeo'}
    except Exception as exc:
        log(f'[creator] LatentSync falhou: {exc}')
        return {'ok': False, 'engine': 'wan2.2_latentsync', 'error': f'LatentSync: {exc}'}


def try_sadtalker(image, audio, destination, temp_dir):
    log('[creator] Tentando SadTalker (fallback final)...')
    client = _client('henrybit/SadTalker-Demo', temp_dir)
    args = [_file(image), _file(audio), 'full', False, 0, 1.0]
    last = None
    for api_name in ('/generate', None):
        try:
            if api_name:
                result = client.predict(*args, api_name=api_name)
            else:
                result = client.predict(*args)
            if _copy_result(result, destination, {'.mp4', '.mov', '.webm', '.m4v'}):
                return {'ok': True, 'engine': 'sadtalker'}
        except Exception as exc:
            last = exc
            log(f'[creator] SadTalker falhou: {exc}')
    return {'ok': False, 'engine': 'sadtalker', 'error': str(last or 'sem saída')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', default='')
    parser.add_argument('--audio', required=True)
    parser.add_argument('--prompt', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--reference-output', required=True)
    parser.add_argument('--info-output', required=True)
    args = parser.parse_args()

    output = Path(args.output).resolve()
    reference = Path(args.reference_output).resolve()
    info_path = Path(args.info_output).resolve()
    temp_dir = output.parent / '_hf_creator_cache'
    temp_dir.mkdir(parents=True, exist_ok=True)

    info = {
        'ok': False,
        'engine': 'none',
        'reference_source': '',
        'hf_authenticated': bool((os.getenv('HF_TOKEN') or '').strip()),
        'attempts': [],
        'note': 'V20.3 usa o Hugging Face principalmente para criar a referência; o talking-head confiável roda em CPU no GitHub.'
    }

    try:
        supplied = Path(args.image).resolve() if args.image else None
        if supplied and supplied.is_file() and supplied.stat().st_size > 5000:
            shutil.copy2(supplied, reference)
            info['reference_source'] = 'job_presenter'
        else:
            generate_creator_image(args.prompt, reference, temp_dir)
            info['reference_source'] = 'flux_1_schnell_zerogpu'

        if (os.getenv('SHOPEE_TRY_ZEROGPU_VIDEO') or '').strip() == '1':
            for engine in (try_echomimic_v2, try_wan_latentsync, try_echomimic_v1, try_sadtalker):
                result = engine(reference, Path(args.audio).resolve(), output, temp_dir)
                info['attempts'].append(result)
                if result.get('ok'):
                    info['ok'] = True
                    info['engine'] = result.get('engine') or 'unknown'
                    break
        else:
            info['attempts'].append({
                'ok': False,
                'engine': 'zerogpu_video_skipped',
                'error': 'Spaces públicos de talking-head estavam pedindo duração de GPU acima do limite; V20.3 usa fallback CPU no GitHub.'
            })

    except Exception as exc:
        info['error'] = str(exc)
        info['traceback'] = traceback.format_exc()[-5000:]
        log(f'[creator] Falha geral: {exc}')

    info_path.parent.mkdir(parents=True, exist_ok=True)
    info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(info, ensure_ascii=False), flush=True)
    return 0 if info.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
