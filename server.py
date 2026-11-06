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
from urllib.parse import parse_qs, quote, unquote

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
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#08090a">
<title>__NAME__</title>
<style>
:root{--y:#ffe600;--red:#ff3b3b;--ink:#08090a;--fg:#f1f1ee;--mut:#8a8d90;--line:rgba(255,255,255,.18);
  --sans:"Helvetica Neue",Arial,"Segoe UI",Roboto,"Noto Sans JP","Hiragino Sans",sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{height:100%}
body{margin:0;background:var(--ink);color:var(--fg);overflow:hidden;font:14px/1.5 var(--sans);
  padding:env(safe-area-inset-top,0) 0 env(safe-area-inset-bottom,0)}

/* ---------- stage (slideshow) ---------- */
#stage{position:fixed;inset:0;z-index:0;background:radial-gradient(80% 50% at 50% 30%,#1c1f22,#08090a)}
.sl{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:50% 30%;opacity:0;
  transform:scale(1.02);transition:opacity 1s ease}
.sl.on{opacity:1;animation:kb 9s ease-out forwards}
@keyframes kb{to{transform:scale(1.1)}}
#stage .fb{position:absolute;inset:0;display:flex;align-items:flex-end;justify-content:center;padding-bottom:150px}
#stage .fb svg{height:min(54vh,430px);width:auto;filter:drop-shadow(0 0 24px rgba(255,60,60,.3))}
.shade{position:fixed;inset:0;z-index:1;pointer-events:none;
  background:
   linear-gradient(180deg,rgba(8,9,10,.78) 0,rgba(8,9,10,0) 22%,rgba(8,9,10,0) 40%,rgba(8,9,10,.92) 78%,#08090a 100%)}
.scan{position:fixed;inset:0;z-index:2;pointer-events:none;opacity:.35;
  background:repeating-linear-gradient(0deg,rgba(255,255,255,.035) 0 1px,transparent 1px 3px)}
.grid{position:fixed;inset:0;z-index:2;pointer-events:none;opacity:.5;
  background-image:linear-gradient(var(--line) 1px,transparent 1px),linear-gradient(90deg,var(--line) 1px,transparent 1px);
  background-size:72px 72px;background-position:-1px -1px;
  -webkit-mask-image:linear-gradient(180deg,transparent 0,#000 15%,transparent 45%);mask-image:linear-gradient(180deg,transparent 0,#000 15%,transparent 45%)}

/* ---------- HUD ---------- */
.bk{position:fixed;z-index:6;width:18px;height:18px;pointer-events:none;border:2px solid var(--y)}
.bk.a{left:10px;top:calc(10px + env(safe-area-inset-top,0));border-right:0;border-bottom:0}
.bk.b{right:10px;top:calc(10px + env(safe-area-inset-top,0));border-left:0;border-bottom:0}
.bk.c{left:10px;bottom:calc(10px + env(safe-area-inset-bottom,0));border-right:0;border-top:0}
.bk.d{right:10px;bottom:calc(10px + env(safe-area-inset-bottom,0));border-left:0;border-top:0}

.top{position:fixed;z-index:20;left:0;right:0;top:env(safe-area-inset-top,0);height:62px;display:flex;align-items:center;
  justify-content:space-between;padding:0 18px 0 22px}
.brand{display:flex;flex-direction:column;line-height:1.1}
.brand b{font:800 15px var(--sans);letter-spacing:.2em}
.brand small{font:10px var(--mono);letter-spacing:.2em;color:var(--y);margin-top:3px}
#tab{position:relative;display:flex;align-items:center;gap:9px;height:38px;padding:0 18px 0 14px;border:0;cursor:pointer;
  background:var(--y);color:#0a0a0a;font:800 12px var(--sans);letter-spacing:.24em;text-indent:.1em;
  clip-path:polygon(0 0,calc(100% - 12px) 0,100% 12px,100% 100%,12px 100%,0 calc(100% - 12px))}
#tab i{display:block;width:16px;height:12px;background:
  linear-gradient(#0a0a0a,#0a0a0a) 0 0/100% 2px no-repeat,linear-gradient(#0a0a0a,#0a0a0a) 0 5px/70% 2px no-repeat,
  linear-gradient(#0a0a0a,#0a0a0a) 0 10px/100% 2px no-repeat;transition:.3s}
#tab.open i{background:linear-gradient(45deg,transparent 45%,#0a0a0a 45% 55%,transparent 55%),linear-gradient(-45deg,transparent 45%,#0a0a0a 45% 55%,transparent 55%)}
#tab:active{filter:brightness(.88)}

.rec{position:fixed;z-index:6;left:22px;top:calc(78px + env(safe-area-inset-top,0));font:11px var(--mono);letter-spacing:.14em;
  display:flex;align-items:center;gap:8px;color:var(--fg)}
.rec i{width:8px;height:8px;border-radius:50%;background:var(--red);box-shadow:0 0 10px var(--red);animation:blink 1.2s steps(1) infinite}
@keyframes blink{50%{opacity:0}}
.rec span{color:var(--mut)}
.vtag{position:fixed;z-index:6;right:20px;top:calc(82px + env(safe-area-inset-top,0));writing-mode:vertical-rl;
  font:10px var(--mono);letter-spacing:.35em;color:rgba(255,255,255,.55)}

main{position:fixed;z-index:7;left:0;right:0;bottom:calc(18px + env(safe-area-inset-bottom,0));padding:0 24px}
.cap{display:flex;align-items:flex-end;justify-content:space-between;gap:10px;margin-bottom:12px}
.cap .n{font:800 44px/1 var(--sans);letter-spacing:-.02em;color:var(--y)}
.cap .n small{font:11px var(--mono);color:var(--mut);letter-spacing:.14em;margin-left:6px}
.cap .t{flex:1;text-align:right;font:11px/1.35 var(--mono);letter-spacing:.1em;color:var(--fg);opacity:.85;min-height:30px;
  display:flex;align-items:flex-end;justify-content:flex-end}
.arrows{display:flex;gap:6px;margin-left:8px}
.arrows button{width:34px;height:34px;border:1px solid var(--line);background:rgba(8,9,10,.55);color:var(--fg);font:14px var(--mono);cursor:pointer;
  clip-path:polygon(0 0,calc(100% - 8px) 0,100% 8px,100% 100%,8px 100%,0 calc(100% - 8px))}
.arrows button:active{background:var(--y);color:#000}
.seg{display:flex;gap:4px;margin-bottom:16px}
.seg span{position:relative;flex:1;height:3px;background:rgba(255,255,255,.2);overflow:hidden}
.seg span.done{background:var(--y)}
.seg span.act::after{content:"";position:absolute;inset:0;background:var(--y);transform-origin:left;transform:scaleX(0);animation:fill var(--dur,5.5s) linear forwards}
@keyframes fill{to{transform:scaleX(1)}}
h1{margin:0;font:800 clamp(30px,10.4vw,50px)/1 var(--sans);letter-spacing:.04em;text-transform:uppercase;white-space:nowrap}
h1 i{font-style:italic;text-transform:lowercase;color:var(--y);padding-left:.08em}
.jp{margin:8px 0 14px;font:10px var(--mono);letter-spacing:.2em;color:var(--mut);white-space:nowrap}
.jp b{color:var(--y);font-weight:400}
.chips{display:flex;gap:6px;flex-wrap:nowrap}
.chip{flex:1;padding:8px 10px;border:1px solid var(--line);background:rgba(8,9,10,.6);font:10px var(--mono);letter-spacing:.14em;color:var(--mut);
  clip-path:polygon(0 0,calc(100% - 8px) 0,100% 8px,100% 100%,0 100%);white-space:nowrap}
.chip b{display:block;margin-top:2px;font:700 13px var(--sans);letter-spacing:.06em;color:var(--fg)}
.chip .dot{display:inline-block;width:6px;height:6px;margin-right:6px;background:#3dff9a;box-shadow:0 0 8px #3dff9a;vertical-align:1px;animation:blink 1.6s steps(1) infinite}

/* ---------- boot ---------- */
#boot{position:fixed;inset:0;z-index:50;background:#08090a;display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:16px;transition:opacity .6s,visibility .6s}
#boot.off{opacity:0;visibility:hidden}
#boot b{font:800 20px var(--sans);letter-spacing:.34em;text-indent:.34em}
#boot b i{font-style:italic;color:var(--y)}
#boot small{font:10px var(--mono);letter-spacing:.3em;color:var(--mut)}
#boot .bar{width:min(60vw,240px);height:3px;background:rgba(255,255,255,.18)}
#boot .bar span{display:block;height:100%;width:0;background:var(--y)}
#boot em{font:700 12px var(--mono);font-style:normal;color:var(--y);letter-spacing:.2em}

/* ---------- drawer (from top) ---------- */
#scrim{position:fixed;inset:0;z-index:15;background:rgba(0,0,0,.78);opacity:0;pointer-events:none;transition:opacity .3s}
#scrim.on{opacity:1;pointer-events:auto}
#drawer{position:fixed;top:0;left:50%;z-index:16;width:min(100%,460px);max-height:95vh;overflow-y:auto;
  transform:translate(-50%,-106%);transition:transform .45s cubic-bezier(.2,.9,.2,1);
  padding:calc(74px + env(safe-area-inset-top,0)) 20px 22px;background:#0b0c0d;border-bottom:3px solid var(--y);
  box-shadow:0 24px 70px rgba(0,0,0,.7)}
#drawer.open{transform:translate(-50%,0)}
.dh{display:flex;align-items:center;justify-content:space-between;margin-bottom:4px}
.dh h2{margin:0;font:800 13px var(--sans);letter-spacing:.4em}
.dh h2 em{font:11px var(--mono);font-style:normal;color:var(--y);margin-right:10px;letter-spacing:.1em}
#x{width:32px;height:32px;border:1px solid var(--line);background:transparent;color:var(--fg);font-size:18px;line-height:1}
.dp{color:var(--mut);font:11px var(--mono);margin:0 0 18px;letter-spacing:.08em}
.btn{width:100%;padding:15px;border:0;background:var(--y);color:#0a0a0a;font:800 13px var(--sans);letter-spacing:.3em;text-indent:.3em;
  text-transform:uppercase;cursor:pointer;
  clip-path:polygon(0 0,calc(100% - 12px) 0,100% 12px,100% 100%,12px 100%,0 calc(100% - 12px))}
.btn:active{filter:brightness(.88)}.btn:disabled{opacity:.6}
.btn.sm{padding:11px;font-size:12px;margin-top:10px}
#key{width:100%;margin-bottom:12px;padding:13px;border:1px solid var(--line);background:#050606;color:var(--fg);
  font:15px var(--mono);text-align:center;letter-spacing:.3em;border-radius:0}
#err{min-height:18px;margin:12px 0 0;color:var(--red);font:11px var(--mono);text-align:center;letter-spacing:.24em}
#links{display:none}
#links.show{display:block;animation:rise .45s ease}
@keyframes rise{from{opacity:0;transform:translateY(-12px)}}
.card{position:relative;margin-top:14px;padding:16px 16px 16px 20px;border:1px solid var(--line);background:#0e1011}
.card::before{content:"";position:absolute;left:-1px;top:-1px;bottom:-1px;width:4px;background:var(--y)}
.card.alt::before{background:#6fd3ff}
.card h3{margin:0 0 2px;font:800 12px var(--sans);letter-spacing:.2em}
.card h3 s{text-decoration:none;font:10px var(--mono);color:var(--y);margin-left:8px;letter-spacing:.14em}
.card.alt h3 s{color:#6fd3ff}
.card p{margin:0 0 10px;font:10px var(--mono);color:var(--mut);letter-spacing:.2em}
textarea{width:100%;height:96px;resize:none;border:1px solid var(--line);border-radius:0;background:#000;color:#d7d9d6;padding:10px;
  font:11px/1.4 var(--mono);word-break:break-all}
.note{margin-top:12px;font:11px var(--mono);color:var(--y);text-align:center}
.hide{margin-top:18px;width:100%;padding:12px;background:transparent;border:1px solid var(--line);color:var(--mut);
  font:11px var(--mono);letter-spacing:.3em;cursor:pointer;border-radius:0}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head>
<body>
<div id="stage"></div>
<div class="shade"></div><div class="scan"></div><div class="grid"></div>
<i class="bk a"></i><i class="bk b"></i><i class="bk c"></i><i class="bk d"></i>

<div class="top">
  <div class="brand"><b id="brand">__NAME__</b><small>// FOG NODE &middot; サイレントヒル</small></div>
  <button id="tab" aria-label="Open links"><i></i><span id="tabt">LINKS</span></button>
</div>
<div class="rec"><i></i>REC <span id="tc">00:00:00</span></div>
<div class="vtag">BEYOND THE FOG</div>

<main>
  <div class="cap">
    <div class="n"><span id="cn">01</span><small>/ <span id="ct">--</span></small></div>
    <div class="t" id="cc"></div>
    <div class="arrows"><button id="pv" aria-label="Previous">&lsaquo;</button><button id="nx" aria-label="Next">&rsaquo;</button></div>
  </div>
  <div class="seg" id="seg"></div>
  <h1 id="ttl">__NAME__</h1>
  <div class="jp"><b>&#9656;</b> サイレントヒル エフ &middot; INTO THE SILENCE</div>
  <div class="chips">
    <div class="chip"><i class="dot"></i>STATUS<b>ONLINE</b></div>
    <div class="chip">PING<b id="ping">--</b></div>
    <div class="chip">WS<b>READY</b></div>
  </div>
</main>

<div id="boot"><b>__NAME__</b><div class="bar"><span id="bb"></span></div><em id="bp">0%</em><small>OVER THE FRONTIER / INTO THE FRONT</small></div>

<div id="scrim"></div>
<aside id="drawer" aria-hidden="true">
  <div class="dh"><h2><em>//</em>ACCESS</h2><button id="x" aria-label="Close">&times;</button></div>
  <p class="dp">Links chhupay hain. Neeche button dabao.</p>
  <div id="gate">
    <input id="key" type="password" placeholder="ACCESS KEY" autocomplete="off" style="display:none">
    <button id="open" class="btn"><span>Open Link</span></button>
    <div id="err"></div>
  </div>
  <div id="links">
    <div class="card"><h3>VLESS WS &middot; TLS<s>ENCRYPTED</s></h3><p id="tlsp"></p>
      <textarea id="tls" readonly></textarea>
      <button class="btn sm" data-copy="tls">Copy</button></div>
    <div class="note" id="gnote"></div>
    <div class="card alt" id="plaincard"><h3>VLESS WS &middot; NON-TLS<s>PLAIN</s></h3><p id="plainp"></p>
      <textarea id="plain" readonly></textarea>
      <button class="btn sm" data-copy="plain">Copy</button>
      <div class="note" id="note"></div></div>
    <button class="hide" id="hide">HIDE LINKS</button>
  </div>
</aside>

<template id="fb"><svg viewBox="0 0 300 390" aria-hidden="true">
    <defs>
      <linearGradient id="skin" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fbe9de"/><stop offset="1" stop-color="#efcfc0"/></linearGradient>
      <linearGradient id="hair" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1b1d28"/><stop offset=".5" stop-color="#07070b"/><stop offset="1" stop-color="#14151d"/></linearGradient>
      <radialGradient id="iris" cx=".5" cy=".35" r=".75"><stop offset="0" stop-color="#ff5a64"/><stop offset=".55" stop-color="#b3121f"/><stop offset="1" stop-color="#3d0309"/></radialGradient>
      <g id="eye">
        <path d="M-17 -2 Q-16 -19 0 -21 Q16 -19 17 -2 Q16 17 0 20 Q-16 17 -17 -2 Z" fill="#fff"/>
        <g class="blink">
          <ellipse cx="0" cy="0" rx="12.5" ry="18" fill="url(#iris)"/>
          <ellipse cx="0" cy="1" rx="5.5" ry="10" fill="#1a0206"/>
          <circle cx="-4.5" cy="-8" r="4.6" fill="#fff"/>
          <circle cx="5" cy="8" r="2.2" fill="#fff" opacity=".9"/>
        </g>
        <path d="M-19 -1 Q-17 -22 0 -23 Q17 -22 19 -4" fill="none" stroke="#08070a" stroke-width="4.2" stroke-linecap="round"/>
        <path d="M-19 -1 L-24 4 M-17 -10 L-23 -9" stroke="#08070a" stroke-width="2.4" stroke-linecap="round"/>
        <path d="M-12 20 Q0 24 12 20" fill="none" stroke="#c99a8e" stroke-width="1.2" opacity=".7"/>
      </g>
    </defs>

    <circle class="sun" cx="150" cy="140" r="118"/>

    <!-- back hair -->
    <path d="M150 14 C66 14 34 92 40 176 C44 240 28 316 14 390 L286 390 C272 316 256 240 260 176 C266 92 234 14 150 14 Z" fill="url(#hair)"/>

    <!-- body: sailor uniform -->
    <path d="M44 390 C48 326 84 292 130 274 L150 300 L170 274 C216 292 252 326 256 390 Z" fill="#ece8de"/>
    <path d="M56 390 C60 340 90 306 128 288 M244 390 C240 340 210 306 172 288" stroke="#cfc9ba" stroke-width="1.5" fill="none"/>
    <!-- neck -->
    <path d="M129 226 L129 276 Q150 302 171 276 L171 226 Z" fill="#efcdbd"/>
    <path d="M129 238 Q150 262 171 238 L171 226 L129 226 Z" fill="#dfb5a4" opacity=".55"/>
    <!-- sailor collar -->
    <path d="M92 296 L128 268 L150 318 L172 268 L208 296 L196 340 L150 322 L104 340 Z" fill="#171924"/>
    <path d="M98 303 L130 276 M104 312 L134 286 M202 303 L170 276 M196 312 L166 286" stroke="#ece8de" stroke-width="2" stroke-linecap="round"/>
    <!-- ribbon -->
    <path d="M150 316 L118 302 Q108 316 118 332 Z" fill="#c1121f"/>
    <path d="M150 316 L182 302 Q192 316 182 332 Z" fill="#a50f1a"/>
    <path d="M146 324 L136 356 L150 348 L164 356 L154 324 Z" fill="#8c0b15"/>
    <rect x="143" y="310" width="14" height="16" rx="4" fill="#e02a38"/>

    <!-- face -->
    <path d="M97 128 C97 84 122 66 150 66 C178 66 203 84 203 128 C203 196 180 238 150 244 C120 238 97 196 97 128 Z" fill="url(#skin)"/>
    <path d="M97 150 C100 206 122 238 150 244 C128 232 112 204 108 160 Z" fill="#e9c3b3" opacity=".6"/>
    <ellipse cx="116" cy="196" rx="14" ry="7" fill="#ff6f7d" opacity=".32"/>
    <ellipse cx="184" cy="196" rx="14" ry="7" fill="#ff6f7d" opacity=".32"/>

    <!-- eyes -->
    <path d="M104 144 Q121 134 138 142 M162 142 Q179 134 196 144" stroke="#150d10" stroke-width="2" fill="none" stroke-linecap="round"/>
    <use href="#eye" transform="translate(121 168)"/>
    <use href="#eye" transform="translate(300 0) scale(-1 1) translate(121 168)"/>
    <!-- tear streak -->
    <path d="M111 189 Q109 205 112 218" stroke="#ff8a94" stroke-width="1.8" fill="none" stroke-linecap="round" opacity=".65"/>
    <path d="M150 192 l-2.5 6 l4 .4" stroke="#c99485" stroke-width="1.6" fill="none" stroke-linecap="round"/>
    <path d="M141 216 Q150 221 159 216" stroke="#a8444f" stroke-width="2.2" fill="none" stroke-linecap="round"/>

    <!-- bangs (hime cut) -->
    <path d="M88 138 C80 58 116 30 150 30 C184 30 220 58 212 138 L206 118 L196 140 L186 104 L174 134 L162 100 L150 132 L138 100 L126 134 L114 104 L104 140 L94 118 Z" fill="url(#hair)"/>
    <path d="M116 46 Q150 30 186 48" stroke="#4a4e63" stroke-width="3" fill="none" stroke-linecap="round" opacity=".7"/>
    <path d="M108 70 Q124 54 142 52" stroke="#3a3d50" stroke-width="2" fill="none" stroke-linecap="round" opacity=".6"/>
    <!-- side locks -->
    <path d="M92 124 C80 176 84 240 70 350 L92 350 C102 270 104 200 108 134 Z" fill="url(#hair)"/>
    <path d="M208 124 C220 176 216 240 230 350 L208 350 C198 270 196 200 192 134 Z" fill="url(#hair)"/>

    <!-- hair ribbon -->
    <g transform="translate(98 64) rotate(-18)">
      <path d="M0 0 L-22 -12 Q-28 0 -22 12 Z" fill="#c1121f"/>
      <path d="M0 0 L22 -12 Q28 0 22 12 Z" fill="#a50f1a"/>
      <rect x="-5" y="-6" width="10" height="12" rx="3" fill="#e02a38"/>
    </g>

    <!-- fox mask on the side of the head -->
    <g transform="translate(222 98) rotate(16)">
      <path d="M-26 -16 L-18 -42 L-4 -22 Q12 -26 26 -20 L40 -40 L42 -10 Q46 16 18 36 Q4 46 -12 36 Q-40 16 -26 -16 Z" fill="#efe8d8" stroke="#171417" stroke-width="1.6"/>
      <path d="M-17 -30 L-7 -18 L-18 -14 Z M33 -30 L28 -16 L38 -12 Z" fill="#c1121f"/>
      <path d="M-18 -2 Q-8 8 0 0 M20 -2 Q12 8 4 0" stroke="#171417" stroke-width="2.4" fill="none" stroke-linecap="round"/>
      <path d="M-26 8 Q-14 10 -8 22 M30 8 Q18 10 12 22" stroke="#c1121f" stroke-width="2.6" fill="none" stroke-linecap="round"/>
      <path d="M-4 18 Q6 24 16 18 Q6 30 -4 18 Z" fill="#171417"/>
      <path d="M-4 -22 Q6 -14 12 -22" stroke="#c1121f" stroke-width="2" fill="none"/>
    </g>
  </svg></template>

<script>
var LOCK=__LOCK__;
var SLIDES=__SLIDES__;
var SLIDE_MS=5500;
var $=function(s){return document.querySelector(s)};
var drawer=$('#drawer'),scrim=$('#scrim'),tab=$('#tab'),tabt=$('#tabt');

/* title: trailing lone "f" -> yellow italic */
(function(){var t=$('#ttl'),s=t.textContent,m=s.match(/^(.*\S)\s+f$/i);
  if(m){t.textContent=m[1]+' ';var i=document.createElement('i');i.textContent='f';t.appendChild(i)}})();

/* boot loader */
(function(){var p=0,bp=$('#bp'),bb=$('#bb'),boot=$('#boot');
  var iv=setInterval(function(){p+=Math.ceil(Math.random()*9)+3;if(p>=100){p=100;clearInterval(iv);setTimeout(function(){boot.classList.add('off')},250)}
    bp.textContent=p+'%';bb.style.width=p+'%'},70)})();

/* timecode */
(function(){var t0=Date.now(),el=$('#tc');
  function z(n){return(n<10?'0':'')+n}
  setInterval(function(){var s=Math.floor((Date.now()-t0)/1000);el.textContent=z(Math.floor(s/3600))+':'+z(Math.floor(s/60)%60)+':'+z(s%60)},1000)})();

/* ---------- slideshow ---------- */
(function(){
  var stage=$('#stage'),seg=$('#seg'),n=SLIDES.length,cur=-1,timer=null,bad=0,startX=null;
  var ok=[];
  function pad(v){return(v<10?'0':'')+v}
  function fallback(){
    var t=document.getElementById('fb'),d=document.createElement('div');d.className='fb';
    d.appendChild(t.content.cloneNode(true));stage.appendChild(d);
    $('#cn').textContent='01';$('#ct').textContent='01';$('#cc').textContent='SILENT HILL // FOG NODE';seg.innerHTML='';
  }
  if(!n){fallback();return}
  $('#ct').textContent=pad(n);
  for(var i=0;i<n;i++){var s=document.createElement('span');seg.appendChild(s)}
  function mark(i){
    var ss=seg.children;
    for(var k=0;k<ss.length;k++){ss[k].className=k<i?'done':'';}
    var a=ss[i];a.style.setProperty('--dur',SLIDE_MS+'ms');
    void a.offsetWidth;a.className='act';
  }
  function load(i,cb){
    if(ok[i]===true)return cb(true);if(ok[i]===false)return cb(false);
    var im=new Image();im.referrerPolicy='no-referrer';
    im.onload=function(){ok[i]=true;cb(true)};im.onerror=function(){ok[i]=false;cb(false)};im.src=SLIDES[i].src;
  }
  function go(i,dir){
    i=((i%n)+n)%n;
    load(i,function(good){
      if(!good){bad++;if(bad>=n){fallback();return}return go(i+(dir||1),dir)}
      bad=0;
      var el=document.createElement('img');el.className='sl';el.referrerPolicy='no-referrer';el.alt='';el.src=SLIDES[i].src;
      stage.appendChild(el);
      var old=stage.querySelectorAll('.sl.on');
      requestAnimationFrame(function(){requestAnimationFrame(function(){
        el.classList.add('on');for(var k=0;k<old.length;k++)old[k].classList.remove('on');
        setTimeout(function(){for(var k=0;k<old.length;k++)if(old[k].parentNode)old[k].parentNode.removeChild(old[k])},1100);
      })});
      cur=i;$('#cn').textContent=pad(i+1);$('#cc').textContent=SLIDES[i].cap||'';mark(i);
      clearTimeout(timer);timer=setTimeout(function(){go(cur+1,1)},SLIDE_MS);
      load((i+1)%n,function(){});
    });
  }
  $('#nx').onclick=function(){go(cur+1,1)};
  $('#pv').onclick=function(){go(cur-1,-1)};
  stage.addEventListener('touchstart',function(e){startX=e.touches[0].clientX},{passive:true});
  stage.addEventListener('touchend',function(e){if(startX===null)return;var dx=e.changedTouches[0].clientX-startX;startX=null;
    if(Math.abs(dx)>40)go(cur+(dx<0?1:-1),dx<0?1:-1)},{passive:true});
  document.addEventListener('visibilitychange',function(){if(!document.hidden&&cur>=0){go(cur,1)}});
  go(0,1);
})();

/* ---------- drawer ---------- */
function openD(){drawer.classList.add('open');scrim.classList.add('on');tab.classList.add('open');drawer.setAttribute('aria-hidden','false');tabt.textContent='CLOSE'}
function closeD(){drawer.classList.remove('open');scrim.classList.remove('on');tab.classList.remove('open');drawer.setAttribute('aria-hidden','true');tabt.textContent='LINKS'}
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
</script></body></html>
"""


IMG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")
IMG_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}

# Default slideshow (official Arknights: Endfield media, loaded straight from their CDN).
# If you put your own pictures in the "images" folder next to server.py, those are used instead.
_CDN = "https://web-static.hg-cdn.com/upload/image/"
DEFAULT_SLIDES = [
    (_CDN + "20261104/eb21a5045952fd94ce94642fb7c4c274.jpg", "Argent Flow // The Returning Traveler"),
    (_CDN + "20261014/3d48ba31690d7ca4f599c082cca09156.png", "Si // All Cleaned Up"),
    (_CDN + "20261006/c942be70201cd7b5e96b11bbe5227cea.png", "Special Trailer // Hongshan"),
    (_CDN + "20261006/7fd952a677f430df10417ac5e2199bed.jpg", "Sanctuary of Ink"),
    (_CDN + "20260902/b86326791c158172551177fd46018a53.png", "Typhoeus // Child of Samivegr"),
    (_CDN + "20260821/15f5e9bd0679cbe1fe3f51b440470493.jpg", "Dreamscape of Wind and Snow"),
    (_CDN + "20260807/6e16ea162578fae87fe80a6eb12483e0.png", "Liino // Focus of Heart and Star"),
    (_CDN + "20260715/b15b6f01601d449faf342d0ca4b7d8de.png", "Arcane // Dust of Forgotten Steps"),
    (_CDN + "20260710/3e7ef5f35a199a9327a55d5a97c5bd1e.jpg", "Homecoming"),
]


def local_images():
    try:
        names = sorted(n for n in os.listdir(IMG_DIR) if os.path.splitext(n)[1].lower() in IMG_TYPES)
    except OSError:
        return []
    return names


def slides_json() -> str:
    names = local_images()
    if names:
        items = [{"src": "/img/" + quote(n), "cap": os.path.splitext(n)[0].replace("_", " ").replace("-", " ").upper()} for n in names]
    else:
        items = [{"src": u, "cap": c.upper()} for u, c in DEFAULT_SLIDES]
    return json.dumps(items).replace("</", "<\\/")


def render_page() -> bytes:
    out = (
        PAGE.replace("__NAME__", NAME.replace("<", "").replace(">", "").replace("&", ""))
        .replace("__LOCK__", "true" if ACCESS_KEY else "false")
        .replace("__SLIDES__", slides_json())
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
        elif path.startswith("/img/"):
            name = unquote(path[5:])
            ext = os.path.splitext(name)[1].lower()
            full = os.path.join(IMG_DIR, name)
            if os.path.basename(name) == name and ext in IMG_TYPES and os.path.isfile(full):
                with open(full, "rb") as fh:
                    await http_reply(writer, "200 OK", fh.read(), IMG_TYPES[ext])
            else:
                await http_reply(writer, "404 Not Found", b"not found")
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
