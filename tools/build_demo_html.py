#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_demo_html.py — 读取 plot.json，内联生成可交互演示页 demo.html
演示页用 ECharts 展示扰动前后曲线对比，支持通道切换、强度调节、换种子实时重算。
用法: python build_demo_html.py plot.json demo.html
"""
import json
import sys

TPL_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NaturalIdle · 数字人去AI味微扰演示</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
<style>
  :root{--bg:#0f1420;--card:#171e2e;--line:#2a3550;--txt:#e8ecf5;--sub:#9aa7c0;--acc:#4ea1ff;--ok:#3ecf8e;}
  *{box-sizing:border-box;margin:0;padding:0;}
  body{background:var(--bg);color:var(--txt);font:14px/1.6 "Microsoft YaHei",system-ui,sans-serif;padding:24px;}
  h1{font-size:20px;margin-bottom:4px;}
  .sub{color:var(--sub);font-size:12px;margin-bottom:18px;}
  .grid{display:grid;grid-template-columns:280px 1fr;gap:16px;max-width:1280px;margin:0 auto;}
  .panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;}
  .panel h3{font-size:13px;color:var(--sub);margin-bottom:10px;border-bottom:1px solid var(--line);padding-bottom:6px;}
  .field{margin-bottom:12px;}
  .field label{display:block;font-size:12px;color:var(--sub);margin-bottom:4px;}
  .field select,.field input[type=number]{width:100%;background:#0f1420;color:var(--txt);border:1px solid var(--line);border-radius:6px;padding:6px 8px;font-size:13px;}
  .field input[type=range]{width:100%;accent-color:var(--acc);}
  .val{float:right;color:var(--acc);font-weight:600;}
  .btn{width:100%;background:var(--acc);border:0;color:#0a101c;font-weight:700;border-radius:6px;padding:8px;cursor:pointer;margin-top:4px;}
  .btn:hover{filter:brightness(1.1);}
  .note{font-size:11px;color:var(--sub);margin-top:10px;line-height:1.5;}
  .charts{display:flex;flex-direction:column;gap:16px;}
  .chart{height:300px;}
  .tag{display:inline-block;background:#123a2a;color:var(--ok);border-radius:4px;padding:1px 8px;font-size:11px;margin-left:6px;vertical-align:2px;}
  .no-echarts{display:none;color:#f0a05a;font-size:12px;margin:8px 0;}
</style>
</head>
<body>
<h1>NaturalIdle<span class="tag">v1.0 演示</span></h1>
<div class="sub">数字人动作「去AI味」自然微扰 · 分层低频随机扰动 · 纯后处理不替换唇形同步 · 演示数据为模拟口播</div>
<div class="no-echarts" id="noEcharts">ECharts 未能从 CDN 加载（需要网络）。核心结论：扰动后曲线在原始曲线上叠加了低频平滑随机偏移，口型/表情幅度被克制。</div>
<div class="grid">
  <div class="panel">
    <h3>参数面板</h3>
    <div class="field"><label>对比通道 <span class="val" id="curChan">jawOpen</span></label>
      <select id="chanSel"></select></div>
    <div class="field"><label>头部扰动强度 <span class="val" id="vHead">0.12</span></label>
      <input type="range" id="headStr" min="0" max="0.3" step="0.01" value="0.12"></div>
    <div class="field"><label>面部扰动强度 <span class="val" id="vFace">0.08</span></label>
      <input type="range" id="faceStr" min="0" max="0.3" step="0.01" value="0.08"></div>
    <div class="field"><label>嘴部扰动强度 <span class="val" id="vMouth">0.15</span></label>
      <input type="range" id="mouthStr" min="0" max="0.3" step="0.01" value="0.15"></div>
    <div class="field"><label>躯干扰动强度 <span class="val" id="vBody">0.06</span></label>
      <input type="range" id="bodyStr" min="0" max="0.2" step="0.01" value="0.06"></div>
    <div class="field"><label>情绪上限 <span class="val" id="vEmo">0.60</span></label>
      <input type="range" id="emoMax" min="0.1" max="1.0" step="0.05" value="0.6"></div>
    <div class="field"><label>随机种子 <span class="val" id="vSeed">42</span></label>
      <input type="number" id="seedInp" value="42" step="1"></div>
    <button class="btn" id="randSeed">🎲 换随机种子</button>
    <div class="note">原理：在原始动作（确定性、刻板）上叠加<strong>低频平滑随机噪声</strong>——嘴部同一字每次开合大小有区别、头部各方向轻微漂移、情绪上限锁死不夸张、躯干极弱跟动。<br>正式处理以 Python 版 natural_idle.py 为准，本页为效果演示与调参预览。</div>
  </div>
  <div class="charts">
    <div class="panel"><h3>扰动前后对比（同一输入，红线=扰动后）</h3><div class="chart" id="c1"></div></div>
    <div class="panel"><h3>各通道扰动幅度（RMS，越大=动得越多）</h3><div class="chart" id="c2"></div></div>
  </div>
</div>
<script>
const DATA = __DATA__;
</script>
"""

TPL_TAIL = """
/* 列分类（与 Python 版一致） */
const KEYWORDS = {
  body:['body','spine','chest','torso','hip','pelvis'],
  shoulder:['shoulder','clavicle'],
  head:['head','neck','pitch','yaw','roll'],
  face:['brow','cheek','eye','blink','squint','smile','nose'],
  mouth:['mouth','lip','jaw','tongue'],
  emotion:['emotion','express','happy','angry','surprise']
};
function classify(cols){
  const m={body:[],shoulder:[],head:[],face:[],mouth:[],emotion:[]};
  cols.forEach((c,i)=>{const cl=c.toLowerCase();let hit=null;
    for(const cat of Object.keys(KEYWORDS)){ if(KEYWORDS[cat].some(k=>cl.includes(k))){hit=cat;break;} }
    if(hit)m[hit].push(i);});
  return m;
}
/* 平滑噪声（等价 Python 实现） */
function gk(sigma){const r=Math.max(1,Math.ceil(3*sigma));const k=[];let s=0;
  for(let i=-r;i<=r;i++){const v=Math.exp(-i*i/(2*sigma*sigma));k.push(v);s+=v;}
  return k.map(v=>v/s);}
function smoothNoise(n,scale,seed,amp=1){
  let st=seed>>>0;const rnd=()=>{st=(Math.imul(st,1664525)+1013904223)>>>0;return (st/4294967296)*2-1;};
  const raw=Array.from({length:n},rnd);
  const sigma=Math.max(0.75,scale*n);const k=gk(sigma);const pad=Math.floor(k.length/2);
  const sm=new Array(n).fill(0);
  for(let i=0;i<n;i++){let acc=0,wt=0;
    for(let j=0;j<k.length;j++){const src=i-pad+j;if(src>=0&&src<n){acc+=raw[src]*k[j];wt+=k[j];}}
    sm[i]=wt?acc/wt:0;}
  let peak=0;sm.forEach(v=>peak=Math.max(peak,Math.abs(v)));if(peak===0)peak=1;
  return sm.map(v=>v/peak*amp);
}
function clip(x,a,b){return Math.min(b,Math.max(a,x));}
function applyPerturb(seq,cols,p){
  const n=seq.length,nc=seq[0].length,m=classify(cols);
  const out=seq.map(r=>r.slice());
  const nb=smoothNoise(n,p.bodyScale||0.12,p.seed,1);
  const nsl=smoothNoise(n,0.10,p.seed+1,1), nsr=smoothNoise(n,0.10,p.seed+2,1);
  const nh=smoothNoise(n,p.headScale||0.06,p.seed+3,1);
  const nf=smoothNoise(n,0.08,p.seed+4,1);
  const nm=smoothNoise(n,0.10,p.seed+5,1);
  const ne=smoothNoise(n,0.12,p.seed+6,1);
  m.body.forEach(i=>{for(let t=0;t<n;t++)out[t][i]=clip(out[t][i]+nb[t]*p.body,0,1);});
  m.shoulder.forEach(i=>{const nn=(cols[i].toLowerCase().includes('l')||cols[i].includes('左'))?nsl:nsr;
    for(let t=0;t<n;t++)out[t][i]=clip(out[t][i]+nn[t]*p.shoulder,0,1);});
  const hc=0.2;
  m.head.forEach(i=>{for(let t=0;t<n;t++)out[t][i]=clip(out[t][i]+nh[t]*p.head+nb[t]*p.head*hc,0,1);});
  m.face.forEach(i=>{for(let t=0;t<n;t++)out[t][i]=clip(out[t][i]+nf[t]*p.face,0,1);});
  m.mouth.forEach(i=>{for(let t=0;t<n;t++)out[t][i]=clip(out[t][i]+clip(nm[t]*p.mouth,-0.25,0.25),0,1);});
  m.emotion.forEach(i=>{const w=1+0.2*ne[t];for(let t=0;t<n;t++)out[t][i]=clip(out[t][i]*w,0,p.emo);});
  return out;
}
/* 初始化 */
const cols=DATA.columns, inp=DATA.input, refOut=DATA.output, map=classify(cols);
const catName={body:'躯干',shoulder:'双肩',head:'头部',face:'面部',mouth:'嘴部',emotion:'情绪'};
const chanSel=document.getElementById('chanSel');
cols.forEach((c,i)=>{const cat=Object.keys(map).find(k=>map[k].includes(i))||'other';
  chanSel.add(new Option((catName[cat]||'其他')+' · '+c,i));});
let c1=null,c2=null;
function initCharts(){
  if(!window.echarts){document.getElementById('noEcharts').style.display='block';return;}
  c1=echarts.init(document.getElementById('c1'));
  c2=echarts.init(document.getElementById('c2'));
  window.addEventListener('resize',()=>{c1.resize();c2.resize();});
}
function render(){
  if(!c1)return;
  const p={head:+document.getElementById('headStr').value,face:+document.getElementById('faceStr').value,
    mouth:+document.getElementById('mouthStr').value,body:+document.getElementById('bodyStr').value,
    shoulder:0.05,emo:+document.getElementById('emoMax').value,seed:+document.getElementById('seedInp').value};
  document.getElementById('vHead').textContent=p.head.toFixed(2);
  document.getElementById('vFace').textContent=p.face.toFixed(2);
  document.getElementById('vMouth').textContent=p.mouth.toFixed(2);
  document.getElementById('vBody').textContent=p.body.toFixed(2);
  document.getElementById('vEmo').textContent=p.emo.toFixed(2);
  document.getElementById('vSeed').textContent=p.seed;
  const idx=+chanSel.value;document.getElementById('curChan').textContent=cols[idx];
  const out=applyPerturb(inp,cols,p);
  const frames=inp.length, xs=Array.from({length:frames},(_,i)=>i);
  const raw=inp.map(r=>r[idx]), pert=out.map(r=>r[idx]);
  const step=Math.max(1,Math.floor(frames/600));
  const xsD=xs.filter((_,i)=>i%step===0), rawD=raw.filter((_,i)=>i%step===0), pertD=pert.filter((_,i)=>i%step===0);
  c1.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis',triggerOn:'mousemove|click',renderMode:'richText',confine:true},
    legend:{data:['原始（AI味）','扰动后'],top:0,textStyle:{color:'#9aa7c0'}},
    grid:{left:46,right:16,top:34,bottom:46,containLabel:true},
    xAxis:{type:'category',data:xsD,name:'帧',nameTextStyle:{color:'#9aa7c0'},axisLine:{lineStyle:{color:'#2a3550'}},axisLabel:{color:'#9aa7c0'}},
    yAxis:{type:'value',min:0,max:1,axisLine:{lineStyle:{color:'#2a3550'}},axisLabel:{color:'#9aa7c0'},splitLine:{lineStyle:{color:'#1d2740'}}},
    dataZoom:[{type:'inside'},{type:'slider',height:16,bottom:4}],
    series:[
      {name:'原始（AI味）',type:'line',data:rawD,symbol:'none',lineStyle:{width:1.5,color:'#6b7694'}},
      {name:'扰动后',type:'line',data:pertD,symbol:'none',lineStyle:{width:2,color:'#3ecf8e'}}
    ]},{notMerge:true});
  /* RMS 统计 */
  const cats=['body','shoulder','head','face','mouth','emotion'];
  const rms=cats.map(cat=>{const idxs=map[cat];if(!idxs.length)return 0;
    let ss=0,cnt=0;for(let t=0;t<frames;t++)for(const i of idxs){const d=out[t][i]-inp[t][i];ss+=d*d;cnt++;}
    return Math.sqrt(ss/cnt);});
  c2.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis',triggerOn:'mousemove|click',renderMode:'richText',confine:true},
    grid:{left:46,right:16,top:24,bottom:30,containLabel:true},
    xAxis:{type:'category',data:cats.map(c=>catName[c]),axisLabel:{color:'#9aa7c0'},axisLine:{lineStyle:{color:'#2a3550'}}},
    yAxis:{type:'value',name:'RMS',nameTextStyle:{color:'#9aa7c0'},axisLabel:{color:'#9aa7c0'},splitLine:{lineStyle:{color:'#1d2740'}}},
    series:[{type:'bar',data:rms,itemStyle:{color:'#4ea1ff',borderRadius:[4,4,0,0]},label:{show:true,position:'top',color:'#9aa7c0',fontSize:11,formatter:v=>v.value.toFixed(3)}}]},
    {notMerge:true});
}
document.getElementById('chanSel').onchange=render;
['headStr','faceStr','mouthStr','bodyStr','emoMax','seedInp'].forEach(id=>{document.getElementById(id).addEventListener('input',render);});
document.getElementById('randSeed').onclick=()=>{document.getElementById('seedInp').value=Math.floor(Math.random()*100000);render();};
initCharts();render();
</script>
</body>
</html>
"""


def main():
    if len(sys.argv) < 3:
        print("用法: python build_demo_html.py plot.json demo.html")
        return 1
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        data = json.load(f)
    html = TPL_HEAD.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    html += TPL_TAIL
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[ok] 已生成 {sys.argv[2]}（{len(html)//1024} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
