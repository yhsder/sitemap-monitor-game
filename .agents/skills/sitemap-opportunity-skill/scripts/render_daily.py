#!/usr/bin/env python3
"""Render one self-contained, offline HTML daily report from AI analysis JSON."""
import argparse
import html
import json
from pathlib import Path


CATEGORIES = ('tool', 'trend_template', 'model_api', 'content_strategy', 'platform_update', 'other')
CONFIDENCE = ('high', 'medium', 'low')
OPPORTUNITY = ('worth_researching', 'watch', 'low_priority')
EVIDENCE = ('observed', 'inferred')

def esc(v): return html.escape(str(v if v is not None else ''), quote=True)
def link(url):
    if not str(url).startswith(('http://','https://')): return esc(url)
    return f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(url)}</a>'

CSS = """
:root{color-scheme:light;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;background:#f6f7f8;color:#17232f}*{box-sizing:border-box}body{margin:0}header{background:#132b38;color:white;padding:30px max(22px,calc((100vw - 1120px)/2))}h1{margin:0 0 8px;font-size:29px}h2{font-size:22px;margin:0 0 14px}h3{font-size:17px;margin:0 0 8px}p{line-height:1.6;margin:7px 0}.sub{color:#b9cbd2}.layout{max-width:1120px;margin:22px auto;padding:0 16px;display:grid;grid-template-columns:190px minmax(0,1fr);gap:18px}aside{position:sticky;top:16px;align-self:start;background:white;border-radius:12px;padding:15px;box-shadow:0 1px 8px #0001}aside a{display:block;padding:9px 8px;color:#21546a;text-decoration:none;border-radius:6px;overflow-wrap:anywhere}aside a:hover{background:#f1f5f7}main{min-width:0}.panel{background:white;border:1px solid #e3e9ec;border-radius:14px;padding:22px;margin-bottom:17px}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}.stat{background:#f1f6f8;padding:14px;border-radius:9px}.stat strong{display:block;font-size:25px}.stat small{color:#587180}.card{padding:16px;border:1px solid #e2e9ec;border-radius:11px;margin-top:12px}.card p{color:#314756}.meta{font-size:12px;color:#698091;margin-bottom:10px}.tag{display:inline-block;background:#ecf3f7;color:#27556c;padding:3px 8px;border-radius:5px;margin-right:6px;margin-bottom:5px;font-size:12px}.source{font-size:13px;line-height:1.6;overflow-wrap:anywhere;margin:5px 0}.source a{color:#156e97}.muted{color:#637988}.warning{color:#8c5a13}.controls{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}.controls input,.controls select{padding:9px;border:1px solid #cdd8dc;border-radius:8px;font:inherit;max-width:100%}.hide{display:none!important}ul{padding-left:20px}li{margin:6px 0}details{margin-top:10px}summary{cursor:pointer;color:#236e91}footer{text-align:center;color:#698091;padding:20px}@media(max-width:720px){.layout{display:block}aside{position:static;margin-bottom:15px}.stats{grid-template-columns:repeat(2,1fr)}header{padding:22px}}
"""
JS = """
const q=document.getElementById('search'), f=document.getElementById('category');function filter(){const term=q.value.trim().toLowerCase(),cat=f.value;for(const x of document.querySelectorAll('.card')){const ok=x.textContent.toLowerCase().includes(term)&&(!cat||x.dataset.category===cat);x.classList.toggle('hide',!ok)}for(const site of document.querySelectorAll('.site')){site.querySelector('.visible-count').textContent=site.querySelectorAll('.card:not(.hide)').length}}q.addEventListener('input',filter);f.addEventListener('change',filter);
"""

def validate(data):
    assert isinstance(data.get('sites'),list), 'sites must be array'
    by_site={}
    for site in data['sites']:
        name=site.get('site')
        pages={p['page_id']:p for p in site.get('pages',[])}
        assert len(pages)==len(site.get('pages',[])), f'duplicate page IDs in {name}'
        assignments={}; ids=set()
        for demand in site.get('demands',[]):
            demand_id=demand.get('id')
            assert demand_id and demand_id not in ids, f'duplicate or missing demand id in {name}'
            ids.add(demand_id)
            assert demand.get('category') in CATEGORIES, f'bad category on {demand_id}'
            assert demand.get('confidence') in CONFIDENCE, f'bad confidence on {demand_id}'
            assert demand.get('opportunity') in OPPORTUNITY, f'bad opportunity on {demand_id}'
            if 'evidence' in demand: assert demand['evidence'] in EVIDENCE, f'bad evidence on {demand_id}'
            assert demand.get('page_ids'), f'demand missing page_ids: {demand.get("name")}'
            for pid in demand['page_ids']:
                assert pid in pages, f'unknown page ID {pid}'
                assert pid not in assignments, f'duplicate assignment {pid}'
                assignments[pid]=demand_id
        uncertain=site.get('uncertain_page_ids',[])
        for pid in uncertain:
            assert pid in pages and pid not in assignments, f'invalid uncertain page {pid}'
        missing=set(pages)-set(assignments)-set(uncertain)
        if missing: raise ValueError(f'{name}: {len(missing)} unaccounted page IDs, e.g. {sorted(missing)[:3]}')
        by_site[name]=ids
    for item in data.get('highlights',[]):
        assert item.get('site') in by_site, f'highlight site {item.get("site")}'
        assert item.get('demand_id') in by_site[item.get('site')], f'highlight demand {item.get("demand_id")}'
    for theme in data.get('cross_site_themes',[]):
        assert theme.get('demand_ids'), f'theme missing source demands: {theme.get("name")}'
        for site_name in theme.get('sites',[]):
            assert site_name in by_site, f'theme site {site_name}'
        for demand_id in theme['demand_ids']:
            owner=next((site for site,ids in by_site.items() if demand_id in ids), None)
            assert owner in theme.get('sites',[]), f'theme demand {demand_id}'


def demand_urls(sites):
    index={}
    for site in sites:
        pages={p['page_id']:p.get('url','') for p in site.get('pages',[])}
        for demand in site.get('demands',[]):
            index[demand.get('id')]=[pages[pid] for pid in demand.get('page_ids',[]) if pages.get(pid)]
    return index

def source_list(urls):
    if not urls: return ''
    items=''.join(f'<li class="source">{link(url)}</li>' for url in urls)
    return f'<div class="muted">数据源</div><ul>{items}</ul>'

def render(data):
    validate(data)
    sites=data['sites']; date=data.get('date','unknown')
    urls_by_demand=demand_urls(sites)
    pieces=[f'<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(date)} Sitemap 每日需求</title><style>{CSS}</style></head><body>',f'<header><h1>Sitemap 每日需求雷达 · {esc(date)}</h1><div class="sub">按网站独立分析 · 单日快照 · URL 新增不代表市场需求刚出现</div></header>']
    pieces.append('<div class="layout"><aside><strong>网站目录</strong><a href="#overview">当日汇总</a>')
    for i,s in enumerate(sites): pieces.append(f'<a href="#site-{i}">{esc(s.get("site","unknown"))} ({len(s.get("demands",[]))})</a>')
    pieces.append('</aside><main><section class="panel" id="overview"><h2>当日汇总</h2>')
    total_raw=sum(s.get('raw_url_count',len(s.get('pages',[]))) for s in sites)
    total_unique=sum(len(s.get('pages',[])) for s in sites)
    total_demands=sum(len(s.get('demands',[])) for s in sites)
    total_uncertain=sum(len(s.get('uncertain_page_ids',[])) for s in sites)
    pieces.append('<div class="stats">')
    for label,val in [('网站',len(sites)),('原始 URL',total_raw),('归一化页面',total_unique),('需求方向',total_demands)]: pieces.append(f'<div class="stat"><strong>{val}</strong><small>{label}</small></div>')
    pieces.append('</div>')
    pieces.append(f'<p class="muted">待判断页面 {total_uncertain} 条。仅汇总当天新增记录，不推断真实发布日期、搜索量或收入。</p>')
    highs=data.get('highlights',[])
    if highs:
        pieces.append('<h3>重点关注</h3><ul>')
        for x in highs:
            urls=urls_by_demand.get(x.get('demand_id'),[])
            pieces.append(f'<li><b>{esc(x.get("site"))}</b> · {esc(x.get("demand_id"))} — {esc(x.get("reason"))}{source_list(urls)}</li>')
        pieces.append('</ul>')
    themes=data.get('cross_site_themes',[])
    if themes:
        pieces.append('<h3>跨站相似主题（仅总览，不合并网站记录）</h3><ul>')
        for x in themes:
            urls=[]
            for demand_id in x.get('demand_ids',[]):
                for url in urls_by_demand.get(demand_id,[]):
                    if url not in urls: urls.append(url)
            pieces.append(f'<li><b>{esc(x.get("name"))}</b> · {esc(", ".join(x.get("sites",[])))} — {esc(x.get("description"))}{source_list(urls)}</li>')
        pieces.append('</ul>')
    for note in data.get('notes',[]): pieces.append(f'<p class="muted">{esc(note)}</p>')
    pieces.append('</section><section class="panel"><h2>筛选需求</h2><div class="controls"><input id="search" type="search" placeholder="搜索需求、场景、URL" aria-label="搜索需求"><select id="category" aria-label="选择需求类型"><option value="">所有类型</option>')
    for name in CATEGORIES:
        pieces.append(f'<option value="{name}">{name}</option>')
    pieces.append('</select></div><p class="muted">下方每个网站独立分组；筛选仅影响需求卡片，不隐藏网站。</p></section>')
    for i,s in enumerate(sites):
        pages={p['page_id']:p for p in s.get('pages',[])}
        pieces.append(f'<section class="panel site" id="site-{i}"><h2>{esc(s.get("site"))}</h2><p class="muted">来源：{esc(s.get("source_file",""))} · 原始 {s.get("raw_url_count",0)} 条 · 有效归一化 {len(pages)} 条 · 排除 {s.get("excluded_count",0)} 条 · 无法判断 {len(s.get("uncertain_page_ids",[]))} 条 · 显示 <span class="visible-count">{len(s.get("demands",[]))}</span> 个需求</p>')
        for d in s.get('demands',[]):
            category=d.get('category','other')
            tags=[category, d.get('confidence','unknown'), d.get('opportunity','unknown')]
            if d.get('evidence'): tags.append(d['evidence'])
            tag_html=''.join(f'<span class="tag">{esc(t)}</span>' for t in tags)
            pieces.append(f'<article class="card" data-category="{esc(category)}"><h3>{esc(d.get("name"))}</h3><div class="meta">{tag_html}<span class="tag">{len(d.get("page_ids",[]))} 个页面</span></div>')
            for label,key in [('需求概述','summary'),('目标用户','audience'),('用户任务','job_to_be_done'),('页面信号','signal')]:
                if d.get(key): pieces.append(f'<p><b>{label}：</b>{esc(d[key])}</p>')
            if d.get('caveats'): pieces.append('<p class="warning"><b>待核实：</b>'+esc('；'.join(d['caveats']))+'</p>')
            pieces.append('<details><summary>来源 URL（证据）</summary><ul>')
            for pid in d.get('page_ids',[]):
                p=pages[pid]; pieces.append(f'<li class="source"><span class="tag">{esc(p.get("page_type","other"))}</span>{link(p.get("url",""))}</li>')
            pieces.append('</ul></details></article>')
        if not s.get('demands'): pieces.append('<p class="muted">该文件未识别出明确的新需求方向。</p>')
        if s.get('uncertain_page_ids'):
            pieces.append('<details><summary>未归类页面</summary><ul>')
            for pid in s['uncertain_page_ids']:
                p=pages[pid]; pieces.append(f'<li class="source">{link(p.get("url",""))}</li>')
            pieces.append('</ul></details>')
        if s.get('error'): pieces.append(f'<p class="warning">处理异常：{esc(s["error"])}</p>')
        pieces.append('</section>')
    pieces.append('</main></div><footer>本报告基于指定日期 Sitemap diff；仅供选题初筛，不构成 SEO 或市场验证。</footer>')
    pieces.append(f'<script>{JS}</script></body></html>')
    return ''.join(pieces)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--output');a=ap.parse_args()
    data=json.loads(Path(a.input).read_text(encoding='utf-8'))
    output=Path(a.output or f'reports/{data.get("date") or "unknown"}/index.html')
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(render(data),encoding='utf-8')
    print(f'Created {output} ({len(data["sites"])} sites)')
