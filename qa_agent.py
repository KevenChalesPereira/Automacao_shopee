#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageStat
except Exception:
    Image = ImageDraw = ImageStat = None

GRAMMAR_PATTERNS = (
    (r'\besse areia\b', 'Concordância: usar “essa areia”.'),
    (r'\bolha esse areia\b', 'Hook com artigo errado para “areia”.'),
    (r'\b4kg a\.?$', 'Título/roteiro parece truncado depois de 4 kg.'),
    (r'\buso prático, visual limpo, dia a dia\b', 'Destaques genéricos demais para um produto específico.'),
)

WEAK_PHRASES = (
    'dá uma olhada', 'gostou da proposta', 'faz sentido para quem', 'é o tipo de produto',
    'mostrei os detalhes', 'antes de fechar', 'vale conferir', 'se atende sua rotina',
    'produto com visual forte', 'ótimo potencial', 'decidir melhor',
)
GENERIC_CTA = (
    'confere preço, avaliações e condições atualizadas',
    'confira os detalhes', 'veja mais detalhes', 'abre o produto',
)
RISKY_MARKERS = (
    'frete grátis', 'últimas unidades', 'só hoje', 'cura ', 'trata ', 'garantido',
    '100% garantido', 'o melhor do brasil',
)


def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='replace')


def clean(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def ffprobe(path: Path):
    data = {'ok': False}
    if not path.is_file() or not shutil.which('ffprobe'):
        return data
    p = run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)])
    if p.returncode != 0:
        data['error'] = p.stderr[-1500:]
        return data
    try:
        raw = json.loads(p.stdout)
    except Exception as exc:
        data['error'] = str(exc)
        return data
    video = next((x for x in raw.get('streams',[]) if x.get('codec_type')=='video'), {})
    audio = next((x for x in raw.get('streams',[]) if x.get('codec_type')=='audio'), {})
    try:
        dur = float(raw.get('format',{}).get('duration') or video.get('duration') or 0)
    except Exception:
        dur = 0.0
    data.update({
        'ok': True,
        'duration_seconds': round(dur, 2),
        'width': int(video.get('width') or 0),
        'height': int(video.get('height') or 0),
        'video_codec': video.get('codec_name') or '',
        'has_audio': bool(audio),
        'audio_codec': audio.get('codec_name') or '',
    })
    return data


def extract_frames(video: Path, out_dir: Path, count=6):
    meta = ffprobe(video)
    dur = float(meta.get('duration_seconds') or 0)
    if dur <= 0 or not shutil.which('ffmpeg'):
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    times = []
    if count <= 1:
        times = [dur/2]
    else:
        # avoid exact first/last frame
        times = [dur*(0.08 + (0.84*i/(count-1))) for i in range(count)]
    paths=[]
    for i,t in enumerate(times):
        p=out_dir/f'frame_{i+1:02d}.jpg'
        r=run(['ffmpeg','-y','-ss',f'{t:.3f}','-i',str(video),'-frames:v','1','-q:v','3',str(p)])
        if r.returncode==0 and p.is_file() and p.stat().st_size>1000:
            paths.append(p)
    return paths


def motion_metric(frames):
    if not Image or len(frames)<2:
        return None
    vals=[]
    prev=None
    for p in frames:
        im=Image.open(p).convert('L').resize((96,170))
        if prev is not None:
            a=prev.tobytes(); b=im.tobytes()
            vals.append(sum(abs(x-y) for x,y in zip(a,b))/max(1,len(a)))
        prev=im
    if not vals:
        return None
    return round(sum(vals)/len(vals),2)


def make_contact_sheet(frames, output):
    if not Image or not frames:
        return None
    thumb_w, thumb_h = 270, 480
    cols=3; rows=math.ceil(len(frames)/cols)
    sheet=Image.new('RGB',(cols*thumb_w,rows*thumb_h),(18,18,18))
    draw=ImageDraw.Draw(sheet)
    for i,p in enumerate(frames):
        im=Image.open(p).convert('RGB')
        im.thumbnail((thumb_w,thumb_h))
        canvas=Image.new('RGB',(thumb_w,thumb_h),(0,0,0))
        x=(thumb_w-im.width)//2; y=(thumb_h-im.height)//2
        canvas.paste(im,(x,y))
        sx=(i%cols)*thumb_w; sy=(i//cols)*thumb_h
        sheet.paste(canvas,(sx,sy))
        draw.rectangle((sx,sy,sx+70,sy+27),fill=(0,0,0))
        draw.text((sx+6,sy+6),f'F{i+1}',fill=(255,255,255))
    sheet.save(output, quality=90)
    return output


def script_checks(product):
    script=clean(product.get('roteiro_comercial') or product.get('roteiro_tts'))
    hook=clean(product.get('hook_visual'))
    points=[clean(x) for x in (product.get('pontos_visuais') or []) if clean(x)]
    low=script.lower()
    words=script.split()
    issues=[]; good=[]; recommendations=[]

    if 30 <= len(words) <= 65:
        good.append(f'Roteiro curto: {len(words)} palavras.')
    else:
        issues.append(f'Roteiro fora da faixa preferida de 30–65 palavras: {len(words)}.')

    hook_words=len(hook.split())
    if hook and hook_words<=11:
        good.append(f'Hook curto: {hook_words} palavras.')
    else:
        issues.append(f'Hook longo ou ausente: {hook_words} palavras.')

    matched=[]
    for pt in points:
        norm=pt.lower().replace(',', '.')
        if norm in low or any(tok in low for tok in re.findall(r'[a-zà-ÿ0-9,.]+',norm) if len(tok)>=5):
            matched.append(pt)
    if points and len(matched)>=min(2,len(points)):
        good.append('Roteiro usa características do produto em vez de só texto genérico.')
    elif points:
        issues.append('Poucas características visuais do produto aparecem no roteiro.')

    grammar=[]
    for pat,msg in GRAMMAR_PATTERNS:
        if re.search(pat, low, flags=re.I):
            grammar.append(msg)
    if grammar:
        issues.extend(grammar)
        recommendations.append('Regerar a copy com concordância e categoria do produto antes de publicar.')
    else:
        good.append('Sem erros gramaticais conhecidos do gerador.')

    weak=[p for p in WEAK_PHRASES if p in low]
    if weak:
        issues.append('Frases genéricas detectadas: ' + ', '.join(weak[:5]) + '.')
        recommendations.append('Trocar frases de marketplace por problema concreto + benefício observável.')
    else:
        good.append('Sem principais frases genéricas da lista de bloqueio.')

    generic=[p for p in GENERIC_CTA if p in low]
    if generic:
        recommendations.append('Encurtar CTA para uma ação simples: “toca no produto e vê a oferta”.')

    risky=[p for p in RISKY_MARKERS if p in low]
    if risky:
        issues.append('Alegações que exigem verificação: ' + ', '.join(risky) + '.')
    else:
        good.append('Nenhuma alegação promocional de alto risco foi detectada.')

    # repeated nouns / filler
    if low.count('produto')>3:
        issues.append('A palavra “produto” aparece demais; soa como locução automática.')
    if len(script)>0 and script.count('.')>=5:
        recommendations.append('Testar cortes de frase mais curtos para ritmo de vídeo curto.')

    return {
        'script':script,
        'hook':hook,
        'word_count':len(words),
        'hook_word_count':hook_words,
        'matched_points':matched,
        'passed':good,
        'warnings':issues,
        'recommendations':recommendations,
    }


def video_checks(output_dir: Path):
    video=output_dir/'anuncio_final.mp4'
    meta=ffprobe(video)
    issues=[]; good=[]; rec=[]
    frames=[]; motion=None; contact=None
    if not meta.get('ok'):
        issues.append('anuncio_final.mp4 ausente ou ilegível.')
        return {'metadata':meta,'passed':good,'warnings':issues,'recommendations':rec}
    dur=meta.get('duration_seconds',0)
    if 8 <= dur <= 35: good.append(f'Duração adequada para short-form: {dur}s.')
    else: issues.append(f'Duração fora da faixa 8–35s: {dur}s.')
    w,h=meta.get('width',0),meta.get('height',0)
    if h>w and w>=720 and h>=1280: good.append(f'Formato vertical adequado: {w}x{h}.')
    else: issues.append(f'Formato/resolução não ideal para vídeo vertical: {w}x{h}.')
    if meta.get('has_audio'): good.append('Faixa de áudio presente.')
    else: issues.append('Vídeo final está sem áudio.')

    tmp=output_dir/'qa_frames'
    frames=extract_frames(video,tmp,6)
    if frames:
        motion=motion_metric(frames)
        contact=output_dir/'qa_contact_sheet.jpg'
        make_contact_sheet(frames,contact)
        if motion is not None:
            if motion < 5.0:
                issues.append(f'Pouca variação visual entre amostras (motion={motion}); pode parecer slideshow.')
                rec.append('Usar mais vídeo real, mudanças de enquadramento ou creator em movimento.')
            else:
                good.append(f'Variação visual detectada entre cenas (motion={motion}).')
    return {
        'metadata':meta,
        'motion_metric':motion,
        'sample_frames': [str(x.name) for x in frames],
        'contact_sheet': str(contact.name) if contact and contact.exists() else '',
        'passed':good,
        'warnings':issues,
        'recommendations':rec,
    }


def creator_checks(product, output_dir:Path):
    requested=bool(product.get('creator_ai_enabled'))
    creator=output_dir/'creator_ai.mp4'
    info={}
    info_path=output_dir/'creator_info.json'
    if info_path.is_file():
        try: info=json.loads(info_path.read_text(encoding='utf-8'))
        except Exception: pass
    passed=[]; warnings=[]; rec=[]
    if requested and creator.is_file() and creator.stat().st_size>20_000:
        passed.append('Creator IA foi gerado e entrou no artifact.')
    elif requested:
        warnings.append('Creator IA solicitado, mas não foi gerado; anúncio caiu no fallback padrão.')
        err=clean(info.get('error') or (info.get('cpu_fallback') or {}).get('error'))
        if err:
            warnings.append('Erro creator: ' + err[:450])
        rec.append('Para o 9.9, não bloquear publicação por isso: usar vídeo real + edição Shopee-first e tratar creator como bônus.')
    else:
        passed.append('Creator IA não era requisito deste job.')
    return {'requested':requested,'exists':creator.is_file(),'info':info,'passed':passed,'warnings':warnings,'recommendations':rec}


def main():
    ap=argparse.ArgumentParser(description='QA automático do Shopee Video Cloud V22.1')
    ap.add_argument('--output-dir',required=True)
    ap.add_argument('--strict',action='store_true')
    a=ap.parse_args()
    out=Path(a.output_dir).resolve()
    product_path=out/'produto.json'
    product={}
    if product_path.is_file():
        try: product=json.loads(product_path.read_text(encoding='utf-8'))
        except Exception: pass

    s=script_checks(product)
    v=video_checks(out)
    c=creator_checks(product,out)
    warnings=[*s['warnings'],*v['warnings'],*c['warnings']]
    passed=[*s['passed'],*v['passed'],*c['passed']]
    rec=[]
    for x in [*s['recommendations'],*v['recommendations'],*c['recommendations']]:
        if x not in rec: rec.append(x)

    hard_fail = (not v.get('metadata',{}).get('ok')) or (not v.get('metadata',{}).get('has_audio'))
    report={
        'version':'22.1',
        'hard_fail':hard_fail,
        'postable_standard':not hard_fail,
        'creator_ready':c['exists'],
        'script':s,
        'video':v,
        'creator':c,
        'passed_checks':passed,
        'warnings':warnings,
        'recommendations':rec,
        'note':'Este QA mede integridade técnica e sinais de copy/ritmo. Não estima CTR, conversão ou vendas.'
    }
    (out/'qa_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['QA SHOPEE VIDEO CLOUD V22.1','']
    lines.append('STATUS: ' + ('FALHA TÉCNICA' if hard_fail else 'POSTÁVEL TECNICAMENTE'))
    lines.append('CREATOR IA: ' + ('OK' if c['exists'] else ('FALHOU/FALLBACK' if c['requested'] else 'NÃO SOLICITADO')))
    lines += ['', 'PASSOU:'] + [f'- {x}' for x in passed]
    lines += ['', 'ALERTAS:'] + ([f'- {x}' for x in warnings] or ['- Nenhum alerta principal.'])
    lines += ['', 'RECOMENDAÇÕES:'] + ([f'- {x}' for x in rec] or ['- Nenhuma recomendação adicional.'])
    lines += ['', report['note']]
    (out/'qa_report.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('\n'.join(lines))
    if a.strict and hard_fail:
        raise SystemExit(2)

if __name__=='__main__':
    main()
