#!/usr/bin/env python3
import json,re,shutil,subprocess,sys,time,urllib.request
from pathlib import Path
from PIL import Image,ImageEnhance,ImageFilter,ImageOps,ImageDraw,ImageFont
W,H,FPS=1080,1920,30
F='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'; UA='Mozilla/5.0'
def run(c,ok=True):
 p=subprocess.run([str(x) for x in c],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True); print('+',' '.join(map(str,c)),flush=True)
 if ok and p.returncode: print(p.stderr[-6000:]); raise RuntimeError(c[0])
 return p
def dur(p): return float(run(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',p]).stdout.strip())
def dl(u,p):
 for n in range(3):
  try:
   r=urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':UA,'Referer':'https://shopee.com.br/'}),timeout=30); p.write_bytes(r.read())
   with Image.open(p) as im: im.verify()
   return True
  except Exception as e: print('[WARN]',e); time.sleep(n+1)
 return False
def prep(src,out):
 im=Image.open(src).convert('RGB'); im=ImageOps.exif_transpose(im); im=ImageEnhance.Contrast(im).enhance(1.04); im=im.filter(ImageFilter.UnsharpMask(1.2,110,3))
 if max(im.size)<1600:
  k=1600/max(im.size); im=im.resize((int(im.width*k),int(im.height*k)),Image.Resampling.LANCZOS)
 bg=ImageOps.fit(im,(W,H),Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(34)); bg=ImageEnhance.Brightness(bg).enhance(.42).convert('RGBA')
 k=min(1000/im.width,1370/im.height); fg=im.resize((int(im.width*k),int(im.height*k)),Image.Resampling.LANCZOS).convert('RGBA'); x=(W-fg.width)//2; y=max(280,(H-fg.height)//2)
 sh=Image.new('RGBA',(fg.width+60,fg.height+60)); d=ImageDraw.Draw(sh); d.rounded_rectangle((20,20,fg.width+40,fg.height+40),28,fill=(0,0,0,125)); sh=sh.filter(ImageFilter.GaussianBlur(18)); bg.alpha_composite(sh,(x-30,y-30)); bg.alpha_composite(fg,(x,y)); bg.convert('RGB').save(out,quality=94)
def txtpng(text,out,cta=False):
 im=Image.new('RGBA',(W,H)); d=ImageDraw.Draw(im); fs=47 if cta else 62; f=ImageFont.truetype(F,fs); mw=850 if cta else 930
 words=text.upper().split(); lines=[]; s=''
 for w in words:
  t=(s+' '+w).strip()
  if d.textbbox((0,0),t,font=f)[2]<=mw:s=t
  else: lines.append(s); s=w
 if s:lines.append(s)
 lines=lines[:2 if cta else 3]; lh=fs+16
 if cta: y1=H-150; y0=y1-(len(lines)*lh+44); box=(75,y0,W-75,y1); fill=(255,91,40,240)
 else: y0=90; y1=y0+len(lines)*lh+54; box=(55,y0,W-55,y1); fill=(5,8,14,220)
 d.rounded_rectangle(box,34,fill=fill); y=y0+24
 for s in lines:
  ww=d.textbbox((0,0),s,font=f)[2]; d.text(((W-ww)//2,y),s,font=f,fill='white'); y+=lh
 im.save(out)
def tts(text,mp3,srt,voice):
 t=mp3.parent/'script.txt'; t.write_text(text,encoding='utf-8')
 for v in [voice,'pt-BR-FranciscaNeural','pt-BR-AntonioNeural']:
  p=run(['edge-tts','--file',t,'--voice',v,'--rate=-2%','--pitch=+0Hz','--write-media',mp3,'--write-subtitles',srt],False)
  if p.returncode==0 and mp3.exists() and mp3.stat().st_size>1000:return v,'edge-tts'
 wav=mp3.with_suffix('.wav'); run(['espeak-ng','-v','pt-br','-s','155','-w',wav,text]); run(['ffmpeg','-y','-i',wav,'-codec:a','libmp3lame','-q:a','3',mp3]); D=dur(mp3); srt.write_text(f'1\n00:00:00,000 --> 00:00:{D:05.2f}\n{text}\n',encoding='utf-8'); return 'pt-br','espeak-fallback'
def ass_from_srt(srt,ass):
 raw=srt.read_text(encoding='utf-8',errors='ignore').strip(); events=[]
 for block in re.split(r'\n\s*\n',raw):
  lines=[x.strip() for x in block.splitlines() if x.strip()]
  if len(lines)<3 or '-->' not in lines[1]: continue
  a,b=[x.strip() for x in lines[1].split('-->')]; text=' '.join(lines[2:]); words=text.split(); chunks=[]; cur=[]
  for word in words:
   if len(' '.join(cur+[word]))>32 and cur: chunks.append(' '.join(cur)); cur=[word]
   else: cur.append(word)
  if cur: chunks.append(' '.join(cur))
  def sec(t):
   h,m,z=t.replace(',','.').split(':'); return int(h)*3600+int(m)*60+float(z)
  def fmt(v):
   h=int(v//3600); v-=h*3600; m=int(v//60); v-=m*60; return f'{h}:{m:02d}:{v:05.2f}'
  st,en=sec(a),sec(b); weights=[max(1,len(c)) for c in chunks]; total=sum(weights); pos=st
  for i,c in enumerate(chunks):
   end=en if i==len(chunks)-1 else pos+(en-st)*weights[i]/total; events.append(f'Dialogue: 0,{fmt(pos)},{fmt(end)},Caption,,0,0,0,,{c}'); pos=end
 head='''[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Caption,DejaVu Sans,54,&H00FFFFFF,&H000000FF,&H00101010,&H70000000,-1,0,0,0,100,100,0,0,1,4,1,2,70,70,330,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'''
 ass.write_text(head+'\n'.join(events)+'\n',encoding='utf-8')
def render(job,out):
 out.mkdir(parents=True,exist_ok=True); w=out/'_work'; w.mkdir(exist_ok=True); p=json.loads((job/'produto.json').read_text()); imgs=[]
 for i,u in enumerate(p['media_urls'][:6]):
  a=w/f'r{i}.img'; b=w/f'i{i}.jpg'
  if dl(u,a): prep(a,b); imgs.append(b)
 if not imgs: raise RuntimeError('sem mídia real')
 mp3=w/'voz.mp3'; srt=w/'leg.srt'; voice,engine=tts(p['roteiro_tts'],mp3,srt,p.get('voice_id','pt-BR-FranciscaNeural')); D=max(8,dur(mp3)+.45); ass=w/'leg.ass'; ass_from_srt(srt,ass); hook=w/'hook.png'; cta=w/'cta.png'; txtpng(p['hook_visual'],hook); txtpng(p['cta_main'],cta,True)
 segs=[]; each=D/min(5,len(imgs))
 for i,img in enumerate(imgs[:5]):
  frames=int(each*FPS); seg=w/f's{i}.mp4'; z="min(zoom+0.0007,1.075)" if i%2==0 else "if(lte(zoom,1),1.075,max(1,zoom-0.0007))"; vf=f"zoompan=z='{z}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d={frames}:s={W}x{H}:fps={FPS}"; run(['ffmpeg','-y','-loop','1','-i',img,'-vf',vf,'-t',f'{each:.3f}','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p',seg]); segs.append(seg)
 L=w/'list.txt'; L.write_text(''.join(f"file '{x.resolve()}'\n" for x in segs)); base=w/'base.mp4'; run(['ffmpeg','-y','-f','concat','-safe','0','-i',L,'-c','copy',base]); final=out/'anuncio_final.mp4'; cs=max(0,D-2.6)
 fc=f"[0:v][1:v]overlay=0:0:enable='between(t,0,2.9)'[a];[a][2:v]overlay=0:0:enable='gte(t,{cs:.3f})'[b];[b]ass='{ass}'[v]"
 run(['ffmpeg','-y','-i',base,'-loop','1','-i',hook,'-loop','1','-i',cta,'-i',mp3,'-filter_complex',fc,'-map','[v]','-map','3:a','-t',f'{D:.3f}','-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-movflags','+faststart',final]); run(['ffmpeg','-y','-ss','1.2','-i',final,'-frames:v','1',out/'capa_video.jpg'])
 (out/'legendas_shopee.ass').write_text(ass.read_text(encoding='utf-8'),encoding='utf-8'); (out/'legenda_post.txt').write_text(p['post_text_render']); (out/'roteiro_narracao.txt').write_text(p['roteiro_tts']); meta={'version':'23.1-auto99','tts_engine':engine,'voice':voice,'duration':round(D,2),'media':len(imgs),'facts':p.get('fatos_verificados',[]),'source':p['url_origem']}; (out/'diagnostico_render.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)); pr=json.loads(run(['ffprobe','-v','error','-show_entries','stream=codec_type,width,height:format=duration','-of','json',final]).stdout); ss=pr['streams']; v=next(x for x in ss if x['codec_type']=='video'); qa={'postable_standard':v.get('width')==1080 and v.get('height')==1920 and any(x['codec_type']=='audio' for x in ss),'width':v.get('width'),'height':v.get('height'),'duration':float(pr['format']['duration']),'has_audio':any(x['codec_type']=='audio' for x in ss),'media_downloaded':len(imgs),'tts_engine':engine}; (out/'qa_report.json').write_text(json.dumps(qa,indent=2)); print('[OK]',p['titulo_curto'])
if __name__=='__main__': render(Path(sys.argv[1]),Path(sys.argv[2]))
