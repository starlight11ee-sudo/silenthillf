#!/usr/bin/env python3
"""
SILENT HILL f - minimal VLESS over WebSocket server.

- No pip packages needed (pure Python standard library).
- Open the domain in a browser: shows the VLESS WS TLS and non-TLS links
  with copy buttons.
- UUID: env UUID if set, otherwise the built-in DEFAULT_UUID (no setup needed).
"""
import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import socket
import struct
import uuid as uuidlib
from urllib.parse import parse_qs, quote

PORT = int(os.environ.get("PORT", "8080"))
NAME = os.environ.get("CONFIG_NAME", "SILENT HILL f")
TLS_PORT = int(os.environ.get("TLS_PORT", "443"))
# Non-TLS: Railway TCP Proxy host/port are picked up automatically (or set PLAIN_HOST / PLAIN_PORT).
PLAIN_HOST = (os.environ.get("PLAIN_HOST") or os.environ.get("RAILWAY_TCP_PROXY_DOMAIN") or "").strip()
PLAIN_PORT = int(os.environ.get("PLAIN_PORT") or os.environ.get("RAILWAY_TCP_PROXY_PORT") or "80")
ACCESS_KEY = os.environ.get("ACCESS_KEY", "")  # optional: if set, links need this key
ALLOW_PRIVATE = os.environ.get("ALLOW_PRIVATE", "") == "1"  # only for local tests
MAX_FRAME = 16 * 1024 * 1024
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
READ_SIZE = 64 * 1024


# Built-in UUID: works out of the box on any platform (Back4App, Railway, ...) with no variables.
# Keep your GitHub repo PRIVATE, because this value is the "password" of the proxy.
DEFAULT_UUID = "b9a55760-8495-5c53-81b2-5306e999e850"


def get_uuid() -> str:
    env = os.environ.get("UUID", "").strip()
    if env:
        try:
            return str(uuidlib.UUID(env))
        except ValueError:
            pass
    if DEFAULT_UUID:
        return DEFAULT_UUID
    seed = os.environ.get("RAILWAY_SERVICE_ID") or os.environ.get("RAILWAY_PROJECT_ID")
    if seed:
        return str(uuidlib.uuid5(uuidlib.NAMESPACE_DNS, "vless-ws-" + seed))
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".uuid")
    try:
        with open(path) as f:
            return str(uuidlib.UUID(f.read().strip()))
    except Exception:
        u = str(uuidlib.uuid4())
        try:
            with open(path, "w") as f:
                f.write(u)
        except OSError:
            pass
        return u


UUID = get_uuid()
UUID_BYTES = uuidlib.UUID(UUID).bytes
WS_PATH = "/ws/" + UUID


# ---------------------------------------------------------------- links + web page
def build_links(req_host: str):
    tls_host = os.environ.get("TLS_HOST") or req_host or os.environ.get("RAILWAY_PUBLIC_DOMAIN") or "YOUR-DOMAIN"
    plain_host = PLAIN_HOST
    p = quote(WS_PATH, safe="")
    tls = (
        f"vless://{UUID}@{tls_host}:{TLS_PORT}?encryption=none&security=tls"
        f"&sni={tls_host}&alpn=http%2F1.1&fp=chrome&type=ws&host={tls_host}&path={p}"
        f"#{quote(NAME + '-TLS')}"
    )
    plain = None
    note = ""
    if plain_host:
        plain = (
            f"vless://{UUID}@{plain_host}:{PLAIN_PORT}?encryption=none&security=none"
            f"&type=ws&host={plain_host}&path={p}#{quote(NAME + '-NonTLS')}"
        )
    else:
        note = "Is platform par non-TLS available nahi (raw TCP port nahi hai). Sirf TLS link use karo."
    return {
        "tls": tls,
        "plain": plain,
        "tls_port": TLS_PORT,
        "plain_port": PLAIN_PORT,
        "note": note,
    }


PAGE = r"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0b0c0b">
<title>__NAME__</title>
<style>
:root{--red:#c1121f;--blood:#7a0b12;--bone:#ebe4d2;--ink:#0b0c0b;--mut:#8d8b80;--moss:#6f7d6e;
  --mincho:"Hiragino Mincho ProN","Yu Mincho","Noto Serif JP","Noto Serif CJK JP","Source Han Serif JP","MS PMincho",serif}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{height:100%}
body{margin:0;background:var(--ink);color:var(--bone);overflow:hidden;
  font:15px/1.6 var(--mincho);padding:env(safe-area-inset-top,0) 0 env(safe-area-inset-bottom,0)}

/* ---------- atmosphere ---------- */
.sky{position:fixed;inset:0;z-index:0;
  background:
   radial-gradient(70% 45% at 50% 38%,rgba(193,18,31,.20),transparent 70%),
   linear-gradient(180deg,#1b1e1b 0%,#111311 45%,#070807 100%)}
.fog{position:fixed;left:-30%;width:160%;height:46%;z-index:1;pointer-events:none;opacity:.55;
  background:radial-gradient(50% 50% at 50% 50%,rgba(190,196,184,.20),transparent 70%)}
.fog.f1{top:18%;animation:drift 26s ease-in-out infinite alternate}
.fog.f2{top:48%;opacity:.45;animation:drift 34s ease-in-out infinite alternate-reverse}
.fog.f3{top:70%;height:40%;opacity:.6;animation:drift 22s ease-in-out infinite alternate}
@keyframes drift{from{transform:translateX(-9%)}to{transform:translateX(9%)}}
#fx{position:fixed;inset:0;z-index:2;pointer-events:none}
.tone{position:fixed;inset:0;z-index:3;pointer-events:none;opacity:.5;
  background-image:radial-gradient(rgba(235,228,210,.16) 1px,transparent 1.6px);background-size:7px 7px;
  -webkit-mask-image:linear-gradient(180deg,#000 0%,transparent 28%,transparent 70%,#000 100%);
  mask-image:linear-gradient(180deg,#000 0%,transparent 28%,transparent 70%,#000 100%)}
.grain{position:fixed;inset:0;z-index:4;pointer-events:none;opacity:.12;mix-blend-mode:overlay;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>")}
.vig{position:fixed;inset:0;z-index:5;pointer-events:none;
  background:radial-gradient(circle at 50% 44%,transparent 38%,rgba(0,0,0,.82) 100%)}
.frame{position:fixed;inset:10px;z-index:6;pointer-events:none;border:1px solid rgba(235,228,210,.22)}
.frame i{position:absolute;width:16px;height:16px;border:2px solid var(--red)}
.frame i:nth-child(1){left:-2px;top:-2px;border-right:0;border-bottom:0}
.frame i:nth-child(2){right:-2px;top:-2px;border-left:0;border-bottom:0}
.frame i:nth-child(3){left:-2px;bottom:-2px;border-right:0;border-top:0}
.frame i:nth-child(4){right:-2px;bottom:-2px;border-left:0;border-top:0}

/* ---------- main ---------- */
main{position:relative;z-index:7;height:100%;display:flex;flex-direction:column;align-items:center;
  justify-content:center;text-align:center;padding:76px 46px 60px}
.vt{position:absolute;top:50%;transform:translateY(-50%);writing-mode:vertical-rl;text-orientation:upright;
  font-size:13px;letter-spacing:.55em;color:rgba(235,228,210,.62);white-space:nowrap}
.vt.l{left:24px}.vt.r{right:24px;color:rgba(193,18,31,.85)}
.vt::before{content:"";position:absolute;left:50%;top:-58px;width:1px;height:46px;background:linear-gradient(transparent,rgba(235,228,210,.4))}

.gate{position:relative;width:min(66vw,270px);aspect-ratio:6/5;margin-bottom:22px;animation:float 10s ease-in-out infinite}
@keyframes float{50%{transform:translateY(-6px)}}
.gate svg{width:100%;height:100%;overflow:visible}
.sun{fill:var(--red);filter:blur(1px) drop-shadow(0 0 22px rgba(193,18,31,.8));animation:breathe 6s ease-in-out infinite}
@keyframes breathe{50%{opacity:.72}}
.torii{fill:#050605;stroke:rgba(235,228,210,.18);stroke-width:.8}

h1{position:relative;margin:0;font-family:var(--mincho);font-weight:600;font-size:clamp(25px,8.2vw,40px);
  letter-spacing:.2em;text-indent:.2em;text-transform:uppercase;color:var(--bone);
  text-shadow:0 0 18px rgba(193,18,31,.35);animation:glitch 7s steps(1) infinite}
h1 i{font-style:italic;text-transform:lowercase;color:var(--red);font-weight:500;padding-left:.12em}
@keyframes glitch{
  0%,92%,100%{text-shadow:0 0 18px rgba(193,18,31,.35)}
  93%{text-shadow:3px 0 var(--red),-3px 0 #4a7a8a;transform:translateX(1px)}
  95%{text-shadow:-3px 0 var(--red),3px 0 #4a7a8a;transform:translateX(-1px)}
  97%{text-shadow:0 0 18px rgba(193,18,31,.35);transform:none}}
.kana{margin-top:8px;font-size:clamp(14px,4.4vw,19px);letter-spacing:.42em;text-indent:.42em;color:rgba(235,228,210,.82)}
.sub{margin:14px 0 26px;display:flex;align-items:center;justify-content:center;gap:12px;
  color:var(--mut);font-size:11px;letter-spacing:.3em;text-transform:uppercase}
.hanko{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;background:var(--red);
  color:var(--bone);font-size:15px;line-height:1;letter-spacing:0;border-radius:2px;transform:rotate(-7deg);
  box-shadow:0 0 12px rgba(193,18,31,.5)}
.stat{display:flex;align-items:center;justify-content:center;flex-wrap:wrap;gap:6px 0;font-size:11px;
  letter-spacing:.18em;color:var(--mut)}
.stat span{padding:0 12px}
.stat span+span{border-left:1px solid rgba(235,228,210,.18)}
.stat b{font-weight:600;color:var(--bone)}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--red);margin-right:8px;
  box-shadow:0 0 10px var(--red);animation:blink 1.8s ease-in-out infinite;vertical-align:1px}
@keyframes blink{50%{opacity:.25}}
.lily{position:fixed;left:-8px;bottom:-6px;z-index:6;width:min(46vw,190px);pointer-events:none;opacity:.9;
  filter:drop-shadow(0 0 10px rgba(193,18,31,.55))}
.lily.r2{left:auto;right:-14px;bottom:-10px;width:min(34vw,140px);transform:scaleX(-1) rotate(-12deg);opacity:.7}
.hint{position:absolute;left:0;right:0;bottom:calc(24px + env(safe-area-inset-bottom,0));text-align:center;
  color:rgba(235,228,210,.38);font-size:10px;letter-spacing:.4em}

/* ---------- top button ---------- */
#tab{position:fixed;top:calc(18px + env(safe-area-inset-top,0));left:50%;transform:translateX(-50%);z-index:20;
  width:74px;height:62px;padding:12px 0 0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;
  cursor:pointer;border:0;color:var(--blood);font-family:var(--mincho);
  background:linear-gradient(180deg,#f3ecda,#d8cfb8);
  clip-path:polygon(0 24%,50% 0,100% 24%,100% 100%,0 100%);
  filter:drop-shadow(0 0 14px rgba(193,18,31,.55));animation:tabpulse 3.4s ease-in-out infinite}
#tab b{font-size:24px;line-height:1;font-weight:700}
#tab small{font-size:8px;letter-spacing:.3em;text-indent:.3em;color:var(--blood);opacity:.8}
#tab::after{content:"";position:absolute;left:50%;top:9px;width:6px;height:6px;margin-left:-3px;border-radius:50%;background:var(--blood)}
#tab:active{transform:translateX(-50%) scale(.95)}
@keyframes tabpulse{50%{filter:drop-shadow(0 0 24px rgba(193,18,31,.9))}}

/* ---------- drawer (drops from top) ---------- */
#scrim{position:fixed;inset:0;z-index:15;background:rgba(0,0,0,.74);opacity:0;pointer-events:none;transition:opacity .35s}
#scrim.on{opacity:1;pointer-events:auto}
#drawer{position:fixed;top:0;left:50%;z-index:16;width:min(100%,440px);max-height:94vh;overflow-y:auto;
  transform:translate(-50%,-106%);transition:transform .5s cubic-bezier(.2,.9,.2,1);
  padding:calc(92px + env(safe-area-inset-top,0)) 20px 22px;
  background:
   repeating-linear-gradient(90deg,rgba(235,228,210,.025) 0 1px,transparent 1px 9px),
   linear-gradient(180deg,#0f100f,#080908);
  border:1px solid rgba(235,228,210,.2);border-top:0;border-bottom:3px solid var(--red);
  box-shadow:0 26px 70px rgba(193,18,31,.28)}
#drawer.open{transform:translate(-50%,0)}
.dh{display:flex;align-items:center;justify-content:space-between;margin-bottom:4px}
.dh h2{margin:0;font-size:15px;font-weight:600;letter-spacing:.5em;color:var(--bone)}
.dh h2 em{font-style:normal;color:var(--red);margin-right:10px}
#x{width:34px;height:34px;border:1px solid rgba(235,228,210,.3);background:transparent;color:var(--bone);font-size:20px;line-height:1;border-radius:2px}
.dp{color:var(--mut);font-size:12px;margin:0 0 20px;letter-spacing:.08em}
.btn{width:100%;padding:15px;border:0;color:var(--bone);font:700 14px var(--mincho);
  letter-spacing:.36em;text-indent:.36em;text-transform:uppercase;cursor:pointer;
  background:linear-gradient(90deg,var(--blood),var(--red),var(--blood));background-size:200% 100%;
  clip-path:polygon(4% 0,100% 0,96% 100%,0 100%);animation:sweep 5s linear infinite alternate}
@keyframes sweep{to{background-position:100% 0}}
.btn:active{filter:brightness(1.25)}
.btn:disabled{opacity:.6}
.btn.sm{padding:11px;font-size:12px;margin-top:10px}
#key{width:100%;margin-bottom:12px;padding:13px;border:1px solid rgba(235,228,210,.35);border-radius:2px;
  background:#050605;color:var(--bone);font:15px ui-monospace,Menlo,monospace;text-align:center;letter-spacing:.3em}
#err{min-height:18px;margin:12px 0 0;color:var(--red);font-size:12px;text-align:center;letter-spacing:.28em}
#links{display:none}
#links.show{display:block;animation:rise .5s ease}
@keyframes rise{from{opacity:0;transform:translateY(-14px)}}
.card{position:relative;margin-top:14px;padding:16px 16px 16px 20px;border:1px solid rgba(235,228,210,.18);background:#0a0b0a}
.card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--red)}
.card.alt::before{background:var(--moss)}
.card h3{margin:0 0 2px;font-size:13px;font-weight:600;letter-spacing:.22em;color:var(--bone)}
.card h3 s{text-decoration:none;color:var(--red);margin-left:6px}
.card.alt h3 s{color:var(--moss)}
.card p{margin:0 0 10px;font-size:11px;color:var(--mut);letter-spacing:.2em}
textarea{width:100%;height:96px;resize:none;border:1px solid rgba(235,228,210,.12);border-radius:2px;background:#000;
  color:#d9d4c2;padding:10px;font:11px/1.4 ui-monospace,Menlo,monospace;word-break:break-all}
.note{margin-top:12px;font-size:11px;color:#d9a441;text-align:center}
.hide{margin-top:18px;width:100%;padding:12px;background:transparent;border:1px solid rgba(235,228,210,.25);border-radius:2px;
  color:var(--mut);font:12px var(--mincho);letter-spacing:.3em;cursor:pointer}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head>
<body>
<div class="sky"></div>
<div class="fog f1"></div><div class="fog f2"></div><div class="fog f3"></div>
<canvas id="fx"></canvas><div class="tone"></div><div class="grain"></div><div class="vig"></div>
<div class="frame"><i></i><i></i><i></i><i></i></div>

<svg class="lily" id="lily1" viewBox="0 0 200 200" aria-hidden="true"></svg>
<svg class="lily r2" id="lily2" viewBox="0 0 200 200" aria-hidden="true"></svg>

<main>
  <div class="vt l">サイレントヒル</div>
  <div class="vt r">霧の中で君を待つ</div>

  <div class="gate">
    <svg viewBox="0 0 240 200" aria-hidden="true">
      <circle class="sun" cx="120" cy="86" r="54"/>
      <g class="torii">
        <path d="M6 34 Q120 12 234 34 L228 50 Q120 32 12 50 Z"/>
        <rect x="26" y="58" width="188" height="11"/>
        <rect x="40" y="46" width="15" height="150"/>
        <rect x="185" y="46" width="15" height="150"/>
        <rect x="112" y="40" width="16" height="20"/>
      </g>
    </svg>
  </div>

  <h1 id="ttl">__NAME__</h1>
  <div class="kana">サイレントヒル エフ</div>
  <div class="sub"><span class="hanko">霧</span><span>fog &middot; spider lily &middot; silence</span></div>
  <div class="stat">
    <span><i class="dot"></i><b>オンライン</b></span>
    <span>Ping <b id="ping">--</b></span>
    <span>WS <b>Ready</b></span>
  </div>
  <div class="hint">▲ 上の「開」を押す</div>
</main>

<button id="tab" aria-label="Open menu"><b id="tabk">開</b><small>LINK</small></button>
<div id="scrim"></div>
<aside id="drawer" aria-hidden="true">
  <div class="dh"><h2><em>鍵</em>ACCESS</h2><button id="x" aria-label="Close">&times;</button></div>
  <p class="dp">Links chhupay hain. Neeche button dabao.</p>
  <div id="gate">
    <input id="key" type="password" placeholder="ACCESS KEY" autocomplete="off" style="display:none">
    <button id="open" class="btn"><span>Open Link</span></button>
    <div id="err"></div>
  </div>
  <div id="links">
    <div class="card"><h3>VLESS WS &middot; TLS<s>暗号</s></h3><p id="tlsp"></p>
      <textarea id="tls" readonly></textarea>
      <button class="btn sm" data-copy="tls">Copy</button></div>
    <div class="note" id="gnote"></div>
    <div class="card alt" id="plaincard"><h3>VLESS WS &middot; NON-TLS<s>平文</s></h3><p id="plainp"></p>
      <textarea id="plain" readonly></textarea>
      <button class="btn sm" data-copy="plain">Copy</button>
      <div class="note" id="note"></div></div>
    <button class="hide" id="hide">Hide links &middot; 隠す</button>
  </div>
</aside>

<script>
var LOCK=__LOCK__;
var $=function(s){return document.querySelector(s)};
var drawer=$('#drawer'),scrim=$('#scrim'),tab=$('#tab'),tabk=$('#tabk');

/* title: last lone "f" becomes the red italic f */
(function(){var t=$('#ttl'),s=t.textContent,m=s.match(/^(.*\S)\s+f$/i);
  if(m){t.textContent=m[1]+' ';var i=document.createElement('i');i.textContent='f';t.appendChild(i)}})();

function openD(){drawer.classList.add('open');scrim.classList.add('on');drawer.setAttribute('aria-hidden','false');tabk.textContent='閉'}
function closeD(){drawer.classList.remove('open');scrim.classList.remove('on');drawer.setAttribute('aria-hidden','true');tabk.textContent='開'}
tab.onclick=function(){drawer.classList.contains('open')?closeD():openD()};
$('#x').onclick=closeD;scrim.onclick=closeD;
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeD()});
if(LOCK)$('#key').style.display='block';

function hideLinks(){
  $('#links').classList.remove('show');$('#gate').style.display='block';
  $('#tls').value='';$('#plain').value='';$('#err').textContent='';
}
$('#hide').onclick=hideLinks;

$('#open').onclick=function(){
  var b=$('#open'),lab=b.querySelector('span'),err=$('#err');
  err.textContent='';b.disabled=true;lab.textContent='Opening...';
  var url='/api/links';
  if(LOCK)url+='?k='+encodeURIComponent($('#key').value.trim());
  fetch(url,{cache:'no-store'}).then(function(r){
    if(!r.ok)throw new Error(r.status);return r.json();
  }).then(function(d){
    $('#tls').value=d.tls;$('#plain').value=d.plain||'';
    $('#tlsp').textContent='PORT '+d.tls_port;$('#plainp').textContent='PORT '+d.plain_port;
    $('#plaincard').style.display=d.plain?'block':'none';
    $('#gnote').textContent=d.plain?'':(d.note||'');
    $('#note').textContent='';
    $('#gate').style.display='none';$('#links').classList.add('show');
  }).catch(function(){
    err.textContent='ACCESS DENIED';
  }).then(function(){b.disabled=false;lab.textContent='Open Link'});
};

function done(btn){var t=btn.textContent;btn.textContent='Copied ✓';setTimeout(function(){btn.textContent=t},1500)}
document.querySelectorAll('[data-copy]').forEach(function(btn){
  btn.onclick=function(){
    var el=document.getElementById(btn.getAttribute('data-copy'));
    function fb(){el.focus();el.select();el.setSelectionRange(0,99999);try{document.execCommand('copy')}catch(e){}done(btn)}
    if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(el.value).then(function(){done(btn)},fb)}else{fb()}
  };
});

/* live ping */
(function(){
  function p(){var t=performance.now();
    fetch('/health',{cache:'no-store'}).then(function(){$('#ping').textContent=Math.round(performance.now()-t)+' ms'})
    .catch(function(){$('#ping').textContent='--'})}
  p();setInterval(function(){if(!document.hidden)p()},15000);
})();

/* red spider lilies (higanbana) drawn in svg */
(function(){
  var NS='http://www.w3.org/2000/svg';
  function mk(svg,seed){
    var g='',i,a,r,cx=100,cy=150;
    function R(){seed=(seed*9301+49297)%233280;return seed/233280}
    g+='<path d="M100 200 C98 180 102 165 100 150" stroke="#2a3a2a" stroke-width="3" fill="none"/>';
    for(i=0;i<9;i++){
      a=-Math.PI*(0.08+0.84*i/8)+(R()-.5)*.12;r=70+R()*34;
      var ex=cx+Math.cos(a)*r,ey=cy+Math.sin(a)*r*.9;
      var c1x=cx+Math.cos(a)*r*.35,c1y=cy+Math.sin(a)*r*.9-18;
      var c2x=cx+Math.cos(a)*r*.85,c2y=cy+Math.sin(a)*r*.9-34;
      g+='<path d="M'+cx+' '+cy+' C'+c1x.toFixed(1)+' '+c1y.toFixed(1)+' '+c2x.toFixed(1)+' '+c2y.toFixed(1)+' '+ex.toFixed(1)+' '+ey.toFixed(1)+'" stroke="#c1121f" stroke-width="2.4" stroke-linecap="round" fill="none"/>';
      if(i%2===0)g+='<path d="M'+ex.toFixed(1)+' '+ey.toFixed(1)+' q'+((R()-.5)*18).toFixed(1)+' -10 '+((R()-.5)*26).toFixed(1)+' -6" stroke="#e4343f" stroke-width="1.6" stroke-linecap="round" fill="none"/>';
      g+='<circle cx="'+ex.toFixed(1)+'" cy="'+ey.toFixed(1)+'" r="2.3" fill="#ff5560"/>';
    }
    for(i=0;i<5;i++){
      a=-Math.PI*(0.18+0.64*i/4);r=42+R()*14;
      g+='<path d="M'+cx+' '+cy+' Q'+(cx+Math.cos(a)*r*.6).toFixed(1)+' '+(cy+Math.sin(a)*r-14).toFixed(1)+' '+(cx+Math.cos(a)*r).toFixed(1)+' '+(cy+Math.sin(a)*r*.8).toFixed(1)+'" stroke="#7a0b12" stroke-width="3.2" stroke-linecap="round" fill="none"/>';
    }
    svg.innerHTML=g;
  }
  mk($('#lily1'),7);mk($('#lily2'),23);
})();

/* falling petals + ash */
(function(){
  if(window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  var c=$('#fx'),x=c.getContext('2d'),W,H,dpr=Math.min(window.devicePixelRatio||1,2),P=[],N=46;
  function size(){W=innerWidth;H=innerHeight;c.width=W*dpr;c.height=H*dpr;x.setTransform(dpr,0,0,dpr,0,0)}
  size();addEventListener('resize',size);
  function mkp(top){var ash=Math.random()<.35;
    return{x:Math.random()*W,y:top?-10-Math.random()*H*.3:Math.random()*H,ash:ash,
      s:ash?Math.random()*1.4+.5:Math.random()*5+3,v:Math.random()*.7+.25,
      w:Math.random()*6.28,ws:Math.random()*.02+.008,r:Math.random()*6.28,rs:(Math.random()-.5)*.04,
      al:ash?Math.random()*.4+.15:Math.random()*.45+.35}}
  for(var i=0;i<N;i++)P.push(mkp(false));
  function f(){
    if(!document.hidden){
      x.clearRect(0,0,W,H);
      for(var i=0;i<N;i++){var p=P[i];
        p.w+=p.ws;p.y+=p.v;p.x+=Math.sin(p.w)*.5-.12;p.r+=p.rs;
        if(p.y>H+12||p.x<-12){P[i]=mkp(true);continue}
        if(p.ash){x.fillStyle='rgba(215,212,198,'+p.al+')';x.beginPath();x.arc(p.x,p.y,p.s,0,6.283);x.fill()}
        else{x.save();x.translate(p.x,p.y);x.rotate(p.r);x.fillStyle='rgba(193,18,31,'+p.al+')';
          x.beginPath();x.moveTo(0,-p.s*1.6);x.quadraticCurveTo(p.s*.9,0,0,p.s*1.6);x.quadraticCurveTo(-p.s*.9,0,0,-p.s*1.6);x.fill();x.restore()}
      }
    }
    requestAnimationFrame(f)
  }
  f();
})();
</script></body></html>
"""


def render_page() -> bytes:
    out = (
        PAGE.replace("__NAME__", NAME.replace("<", "").replace(">", "").replace("&", ""))
        .replace("__LOCK__", "true" if ACCESS_KEY else "false")
    )
    return out.encode()


def json_bytes(obj) -> bytes:
    return json.dumps(obj).encode()


async def http_reply(writer, status: str, body: bytes, ctype="text/plain; charset=utf-8"):
    head = (
        f"HTTP/1.1 {status}\r\nContent-Type: {ctype}\r\n"
        f"Content-Length: {len(body)}\r\nCache-Control: no-store\r\n"
        f"Connection: close\r\n\r\n"
    ).encode()
    writer.write(head + body)
    try:
        await writer.drain()
    except Exception:
        pass


# ---------------------------------------------------------------- websocket
def unmask(data: bytes, mask: bytes) -> bytes:
    n = len(data)
    if n == 0:
        return data
    m = (mask * (n // 4 + 1))[:n]
    return (int.from_bytes(data, "big") ^ int.from_bytes(m, "big")).to_bytes(n, "big")


def make_frame(op: int, data: bytes) -> bytes:
    n = len(data)
    b0 = 0x80 | op
    if n < 126:
        head = bytes([b0, n])
    elif n < 65536:
        head = bytes([b0, 126]) + struct.pack(">H", n)
    else:
        head = bytes([b0, 127]) + struct.pack(">Q", n)
    return head + data


class WS:
    def __init__(self, reader, writer):
        self.r = reader
        self.w = writer
        self.lock = asyncio.Lock()
        self.closed = False

    async def _write(self, data: bytes):
        async with self.lock:
            self.w.write(data)
            await self.w.drain()

    async def send(self, data: bytes):
        await self._write(make_frame(0x2, data))

    async def close(self, code: int = 1000):
        if not self.closed:
            self.closed = True
            try:
                await self._write(make_frame(0x8, struct.pack(">H", code)))
            except Exception:
                pass

    async def recv(self):
        """Return next complete message (bytes), or None when closed."""
        buf = bytearray()
        while True:
            try:
                h = await self.r.readexactly(2)
            except (asyncio.IncompleteReadError, ConnectionError):
                return None
            fin = h[0] & 0x80
            op = h[0] & 0x0F
            masked = h[1] & 0x80
            ln = h[1] & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", await self.r.readexactly(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", await self.r.readexactly(8))[0]
            if ln > MAX_FRAME:
                return None
            mask = await self.r.readexactly(4) if masked else None
            data = await self.r.readexactly(ln) if ln else b""
            if mask:
                data = unmask(data, mask)
            if op == 0x8:
                return None
            if op == 0x9:
                await self._write(make_frame(0xA, data))
                continue
            if op == 0xA:
                continue
            buf += data
            if len(buf) > MAX_FRAME:
                return None
            if fin:
                return bytes(buf)


async def ws_keepalive(ws: WS):
    try:
        while True:
            await asyncio.sleep(25)
            await ws._write(make_frame(0x9, b""))
    except Exception:
        pass


# ---------------------------------------------------------------- vless
def parse_vless(b: bytes):
    if len(b) < 24:
        raise ValueError("short header")
    if b[1:17] != UUID_BYTES:
        raise ValueError("bad uuid")
    pos = 17
    pos += 1 + b[pos]
    cmd = b[pos]
    pos += 1
    port = int.from_bytes(b[pos:pos + 2], "big")
    pos += 2
    at = b[pos]
    pos += 1
    if at == 1:
        addr = socket.inet_ntoa(b[pos:pos + 4])
        pos += 4
    elif at == 2:
        ln = b[pos]
        pos += 1
        addr = b[pos:pos + ln].decode("utf-8", "ignore")
        pos += ln
    elif at == 3:
        addr = socket.inet_ntop(socket.AF_INET6, b[pos:pos + 16])
        pos += 16
    else:
        raise ValueError("bad address type")
    if pos > len(b):
        raise ValueError("truncated header")
    return b[0], cmd, addr, port, b[pos:]


def allowed_ip(ip: str) -> bool:
    if ALLOW_PRIVATE:
        return True
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    return a.is_global and not a.is_multicast


async def resolve(addr: str, port: int, kind: int):
    """Return allowed (family, ip) candidates, IPv4 first. Blocks private/internal targets."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(addr, port, type=kind)
    infos.sort(key=lambda i: 0 if i[0] == socket.AF_INET else 1)
    out = []
    for fam, _, _, _, sa in infos:
        if allowed_ip(sa[0]):
            out.append((fam, sa[0]))
    if not out:
        raise ValueError("target blocked or unresolved")
    return out


async def open_tcp(addr: str, port: int):
    last = None
    for _, ip in await resolve(addr, port, socket.SOCK_STREAM):
        try:
            return await asyncio.wait_for(asyncio.open_connection(ip, port), 10)
        except Exception as e:  # try next address
            last = e
    raise last or ValueError("connect failed")


async def tcp_tunnel(ws: WS, ver: int, addr: str, port: int, payload: bytes):
    r, w = await open_tcp(addr, port)
    sock = w.get_extra_info("socket")
    if sock is not None:
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
    if payload:
        w.write(payload)
        await w.drain()
    hdr = bytes([ver, 0])

    async def up():
        while True:
            m = await ws.recv()
            if m is None:
                break
            w.write(m)
            await w.drain()

    async def down():
        first = True
        while True:
            d = await r.read(READ_SIZE)
            if not d:
                break
            await ws.send(hdr + d if first else d)
            first = False

    tasks = [asyncio.create_task(up()), asyncio.create_task(down())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        try:
            w.close()
        except Exception:
            pass


class _UdpProto(asyncio.DatagramProtocol):
    def __init__(self, queue):
        self.q = queue

    def datagram_received(self, data, addr):
        self.q.put_nowait(data)


async def udp_tunnel(ws: WS, ver: int, addr: str, port: int, payload: bytes):
    fam, ip = (await resolve(addr, port, socket.SOCK_DGRAM))[0]
    q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _UdpProto(q), remote_addr=(ip, port)
    )
    hdr = bytes([ver, 0])
    buf = bytearray(payload)

    def flush():
        while len(buf) >= 2:
            ln = (buf[0] << 8) | buf[1]
            if len(buf) < 2 + ln:
                break
            transport.sendto(bytes(buf[2:2 + ln]))
            del buf[:2 + ln]

    async def up():
        flush()
        while True:
            m = await ws.recv()
            if m is None:
                break
            buf.extend(m)
            flush()

    async def down():
        first = True
        while True:
            d = await q.get()
            msg = struct.pack(">H", len(d)) + d
            await ws.send(hdr + msg if first else msg)
            first = False

    tasks = [asyncio.create_task(up()), asyncio.create_task(down())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        transport.close()


async def ws_tunnel(reader, writer, headers):
    key = headers.get("sec-websocket-key", "")
    if not key:
        await http_reply(writer, "400 Bad Request", b"bad request")
        return
    accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
    writer.write(
        (
            "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n"
        ).encode()
    )
    await writer.drain()
    ws = WS(reader, writer)
    ka = asyncio.create_task(ws_keepalive(ws))
    print(f"[ws] handshake ok proto={headers.get('x-forwarded-proto','-')} "
          f"host={headers.get('host','-')}", flush=True)
    try:
        first = await asyncio.wait_for(ws.recv(), 30)
        if not first:
            return
        ver, cmd, addr, port, payload = parse_vless(first)
        print(f"[ws] cmd={cmd} -> {addr}:{port}", flush=True)
        if cmd == 1:
            await tcp_tunnel(ws, ver, addr, port, payload)
        elif cmd == 2:
            await udp_tunnel(ws, ver, addr, port, payload)
    except Exception as e:
        print(f"[ws] closed: {type(e).__name__}: {e}", flush=True)
    finally:
        ka.cancel()
        await ws.close()


# ---------------------------------------------------------------- http entry
async def handle(reader, writer):
    try:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 15)
        except Exception:
            return
        lines = head.decode("latin-1").split("\r\n")
        parts = lines[0].split(" ")
        if len(parts) < 2:
            return
        target = parts[1]
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        path, _, query = target.partition("?")

        if headers.get("upgrade", "").lower() == "websocket" and path == WS_PATH:
            await ws_tunnel(reader, writer, headers)
        elif path == "/health":
            await http_reply(writer, "200 OK", b"ok")
        elif path == "/api/links":
            key = parse_qs(query).get("k", [""])[0]
            if ACCESS_KEY and not hmac.compare_digest(key.encode(), ACCESS_KEY.encode()):
                await http_reply(writer, "403 Forbidden", b'{"error":"denied"}', "application/json")
            else:
                host = headers.get("host", "").split(":")[0]
                await http_reply(writer, "200 OK", json_bytes(build_links(host)), "application/json")
        elif path in ("/", "/index.html"):
            await http_reply(writer, "200 OK", render_page(), "text/html; charset=utf-8")
        else:
            await http_reply(writer, "404 Not Found", b"not found")
    except Exception as e:
        print(f"[http] error: {type(e).__name__}: {e}", flush=True)
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def main():
    try:
        server = await asyncio.start_server(handle, None, PORT, limit=READ_SIZE, backlog=1024)
    except OSError:
        server = await asyncio.start_server(handle, "0.0.0.0", PORT, limit=READ_SIZE, backlog=1024)
    print(f"[vless-ws] listening on :{PORT}  uuid={UUID}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
