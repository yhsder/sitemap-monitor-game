#!/usr/bin/env python3
"""Prepare the chosen dated sitemap diff folder for LLM analysis; stdlib only."""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse

LOCALES = set('ar bg cs da de el en es et fi fr he hi id it ja ko ms nl no pl pt ro ru sv th tr uk vi zh nb'.split()) | {'en-us','en-gb','es-mx','pt-br','pt-pt','zh-cn','zh-tw','fr-ca'}
EXCLUDE = {'login','signin','sign-in','signup','sign-up','pricing','privacy','privacy-policy','terms','terms-of-service','contact','account','dashboard','cookie-policy'}

def canonical(url):
    p=urlparse(url.strip())
    if p.scheme not in ('http','https') or not p.netloc: return None
    segments=[s for s in p.path.split('/') if s]
    if segments and segments[0].lower() in LOCALES: segments=segments[1:]
    path='/'+ '/'.join(segments)
    return urlunparse((p.scheme.lower(),p.netloc.lower(),path,'',p.query,''))

def page_type(url):
    segments=[s.lower() for s in urlparse(url).path.split('/') if s]
    if not segments: return 'category'
    s=segments[0]
    if s in ('blog','hub','articles','guides','tutorials','news'): return 'blog'
    if s in ('video-effects','effects'): return 'video_effect'
    if s in ('templates','template'): return 'template' if len(segments)>1 else 'category'
    if s in ('models','model','api','apis','m'): return 'model_api'
    if s in ('community','rooms'): return 'community'
    if s in ('app','tools','tool'): return 'tool' if len(segments)>1 else 'category'
    if len(segments)==1 and (segments[-1].endswith('-maker') or segments[-1].endswith('-generator')): return 'tool'
    return 'other'

def site_record(root, f, raw, invalid, excluded, pages, error=None):
    record={'site':f.stem,'source_file':str(f.relative_to(root)),'raw_url_count':raw,'invalid_count':invalid,'excluded_count':excluded,'canonical_page_count':len(pages),'pages':pages}
    if error: record['error']=error
    return record

def load_site(root, f):
    raw=0; invalid=0; excluded=0; seen={}; pages=[]
    for line in f.read_text(encoding='utf-8-sig').splitlines():
        line=line.strip()
        if not line or line.startswith('---'): continue
        raw+=1
        identity=canonical(line)
        if not identity:
            invalid+=1; continue
        parts=[p.lower() for p in urlparse(identity).path.split('/') if p]
        if parts and parts[0] in EXCLUDE:
            excluded+=1; continue
        if identity in seen:
            seen[identity]['original_urls'].append(line)
            continue
        item={'page_id':f'{f.stem}-{len(pages)+1:04d}','url':line,'canonical_url':identity,'original_urls':[line], 'page_type':page_type(identity),'slug':parts[-1] if parts else ''}
        seen[identity]=item; pages.append(item)
    return site_record(root, f, raw, invalid, excluded, pages)

def prepare(root, date):
    folder=root/'diff'/date
    if not re.fullmatch(r'\d{8}',date): raise ValueError('Date must be YYYYMMDD')
    if not folder.is_dir(): raise FileNotFoundError(folder)
    files=sorted(folder.glob('*.json'))
    if not files: raise ValueError(f'No .json diff files in {folder}')
    sites=[]
    for f in files:
        try:
            sites.append(load_site(root, f))
        except (OSError, UnicodeError) as err:
            sites.append(site_record(root, f, 0, 0, 0, [], f'{type(err).__name__}: {err}'))
    return {'date':date,'sites':sites}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--repo',default='.');ap.add_argument('--date');ap.add_argument('--output')
    a=ap.parse_args();root=Path(a.repo).resolve()
    dates=sorted(p.name for p in (root/'diff').glob('[0-9]*') if p.is_dir())
    date=a.date or (dates[-1] if dates else None)
    if date is None: ap.error('No dated diff folder found')
    data=prepare(root,date)
    target=Path(a.output or f'reports/{date}/prepared.json'); target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    pages=sum(len(x['pages']) for x in data['sites']); bad=sum(1 for x in data['sites'] if x.get('error'))
    print(f'{target} | {len(data["sites"])} sites | {pages} pages | {bad} unreadable')
