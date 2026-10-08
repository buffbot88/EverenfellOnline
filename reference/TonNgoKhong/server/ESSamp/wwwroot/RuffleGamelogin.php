<?php
// Ruffle wrapper for the SUPPLIED Flash client (/res/Main.swf).
// Same session gate and signed flashvars as Gamelogin.php; only the Flash
// Player embed is replaced with Ruffle (Flash is dead in modern browsers).
// Flow: login first at /UserCenter/Login.php, then open this page.
  include_once "configuration/config.inc.php";
  if(!$_SESSION['accountName']) exit("<script> alert('请登陆后使用！');location.href='UserCenter/Login.php';</script>");
    $userid = $_SESSION['accountName'];
    $time = time();
  $sid = md5($userid.'xianlingkey'.$time);
?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
<meta http-equiv="Cache-Control" content="no-cache" />
<title>大闹天宫</title>
<link rel="icon" href="data:," />
<base href="http://127.0.0.1/res/" />
<style type="text/css">
html,body{ margin:0; height:100%; padding:0; overflow:hidden; background-color:#000; }
#container{ position:relative; margin:auto; height:100%; }
#Main{ width:100%; height:100%; display:block; }
#Main ruffle-player{ width:100%; height:100%; display:block; }
#diagnostics-toggle{ position:absolute; right:12px; bottom:10px; z-index:20; border:1px solid #59627e; border-radius:6px; padding:6px 10px; background:rgba(5,7,15,.9); color:#d9def0; font-size:12px; cursor:pointer; }
#diagnostics-toggle.has-errors{ border-color:#ff6b6b; color:#ffb0b0; }
#diagnostics{ display:none; position:absolute; right:12px; bottom:48px; z-index:20; width:min(620px,calc(100vw - 24px)); max-height:min(55vh,420px); overflow:hidden; border:1px solid #59627e; border-radius:8px; background:rgba(8,10,20,.97); color:#d9def0; font-size:12px; }
#diagnostics.open{ display:flex; flex-direction:column; }
#diagnostics header{ display:flex; align-items:center; gap:8px; padding:8px 10px; border-bottom:1px solid #30374a; }
#diagnostics-title{ flex:1; font-weight:600; }
#diagnostics button{ border:1px solid #59627e; border-radius:4px; background:#171b2a; color:inherit; padding:3px 7px; cursor:pointer; }
#diagnostics-list{ margin:0; padding:8px 10px; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; font:11px/1.45 Consolas,monospace; }
.diag-error{ color:#ff8585; } .diag-warn{ color:#ffd76a; } .diag-info{ color:#9bb8ff; }
</style>
<script type="text/javascript" src="http://127.0.0.1/ruffle/ruffle.js"></script>
</head>
<body>
  <div id="container"><div id="Main"></div>
  <section id="diagnostics" aria-label="Client diagnostics" aria-live="polite">
    <header><span id="diagnostics-title">Client diagnostics</span>
    <button id="diagnostics-copy" type="button">Copy</button>
    <button id="diagnostics-clear" type="button">Clear</button>
    <button id="diagnostics-close" type="button" aria-label="Close diagnostics">×</button></header>
    <pre id="diagnostics-list"><span>No client warnings or errors captured.</span></pre>
  </section>
  <button id="diagnostics-toggle" type="button">Diagnostics</button>
  </div>
<script type="text/javascript">
(function(){
  var list=document.getElementById('diagnostics-list'),panel=document.getElementById('diagnostics'),toggle=document.getElementById('diagnostics-toggle'),items=[],MAX=400;
  function fmt(v){ if(v instanceof Error) return v.name+': '+v.message+(v.stack?'\n'+v.stack:''); if(typeof v==='string') return v; try{return JSON.stringify(v);}catch(e){return String(v);} }
  function render(){ var e=0,w=0,i; for(i=0;i<items.length;i++){ if(items[i].level==='error')e++; else if(items[i].level==='warn')w++; }
    toggle.textContent='Diagnostics · '+e+' errors · '+w+' warnings'; toggle.className=e?'has-errors':'';
    list.replaceChildren(); if(!items.length){ var s=document.createElement('span'); s.textContent='No client warnings or errors captured.'; list.append(s); return; }
    for(i=0;i<items.length;i++){ var l=document.createElement('span'); l.className='diag-'+items[i].level; l.textContent='['+items[i].time+'] '+items[i].level.toUpperCase()+' '+items[i].message+'\n'; list.append(l); }
    list.scrollTop=list.scrollHeight; }
  function clean(t){ var m=String(t).match(/%c(INFO|WARN|ERROR|DEBUG)%c\s*([^%]+?)%c\s*([\s\S]*)/); if(!m) return String(t);
    return (m[1]+' '+m[2].trim()+' '+m[3].replace(/\s+color:\s*[^;]+;.*$/,'').trim()).slice(0,3000); }
  window.__report=function(level){ var msg=Array.prototype.slice.call(arguments,1).map(fmt).join(' ');
    items.push({level:level,message:msg.slice(0,3000),time:new Date().toLocaleTimeString()}); if(items.length>MAX)items.shift(); render();
    if(level==='error'){panel.classList.add('open');} };
  var oc={log:console.log.bind(console),warn:console.warn.bind(console),error:console.error.bind(console),debug:console.debug.bind(console),info:console.info.bind(console)};
  ['log','warn','error','debug','info'].forEach(function(m){ if(!oc[m])return; console[m]=function(){ oc[m].apply(console,arguments);
    var text=Array.prototype.slice.call(arguments).map(fmt).join(' '); var rl=text.match(/%c(INFO|WARN|ERROR|DEBUG)%c/);
    if(m==='error'||m==='warn') window.__report(rl&&rl[1]==='ERROR'?'error':rl&&rl[1]==='WARN'?'warn':m,clean(text));
    else if(rl&&rl[1]!=='INFO'&&rl[1]!=='DEBUG') window.__report(rl[1]==='ERROR'?'error':'warn',clean(text));
    else window.__report('info',clean(text)); }; });
  window.addEventListener('error',function(e){ window.__report('error',e.error||e.message); });
  window.addEventListener('unhandledrejection',function(e){ window.__report('error','Unhandled promise rejection:',e.reason); });
  toggle.addEventListener('click',function(){ panel.classList.toggle('open'); });
  document.getElementById('diagnostics-close').addEventListener('click',function(){ panel.classList.remove('open'); });
  document.getElementById('diagnostics-clear').addEventListener('click',function(){ items.length=0; render(); });
  document.getElementById('diagnostics-copy').addEventListener('click',function(){
    var t=items.map(function(i){return '['+i.time+'] '+i.level.toUpperCase()+' '+i.message;}).join('\n');
    if(navigator.clipboard) navigator.clipboard.writeText(t); });
  if(window.PerformanceObserver){ try{ new PerformanceObserver(function(l){ l.getEntries().forEach(function(en){
    if(en.responseStatus>=400) window.__report('error','Resource '+en.responseStatus+': '+en.name); }); }).observe({type:'resource',buffered:true}); }catch(e){} }
  render(); window.__report('info','Diagnostics ready ('+navigator.userAgent+')');
})();
</script>
<script type="text/javascript">
(function(){
  // Browsers can't open raw TCP sockets, so the client's socket to
  // ip:sport forwards through the byte-transparent WS->TCP shim on :8181.
  // Override: ?bridge=ws://host:port  |  disable: ?nobridge=1
  var qs = new URLSearchParams(location.search);
  var bridgeUrl = qs.get('bridge') || 'ws://127.0.0.1:8181';
  var socketProxy = qs.has('nobridge') ? [] : [
    { host: '127.0.0.1', port: 8008, proxyUrl: bridgeUrl },
    { host: 'localhost', port: 8008, proxyUrl: bridgeUrl }
  ];
  if (!window.RufflePlayer || typeof window.RufflePlayer.newest !== 'function') {
    document.getElementById('Main').innerHTML =
      '<p style="color:#f66">Ruffle failed to load from /ruffle/ruffle.js. ' +
      'Reboot the stack (tools/orig-stack.sh down &amp;&amp; tools/orig-stack.sh up) ' +
      'so Apache picks up the /ruffle Alias, then check ' +
      'http://127.0.0.1/ruffle/ruffle.js loads as JavaScript.</p>';
    return;
  }
  // logLevel info: the loader core is compiled C (Alchemy) whose only
  // diagnostics are AS3 trace() calls (wrteBytes/packet id/...). At
  // 'warn' Ruffle hides them; we need them to see where the core stops.
  var lvl = qs.get('loglevel') || 'info';
  window.RufflePlayer.config = {
    autoplay: 'on',
    unmuteOverlay: 'hidden',
    logLevel: lvl,
    socketProxy: socketProxy
  };
  var flashvars = {
    lcid: (new Date()).valueOf().toString(16) + (Math.random() * 1000 >> 0).toString(16),
    pay: escape('http://tuan565.blogspot.com/'),
    cm: escape('http://tuan565.blogspot.com/'),
    uid: '<?php echo $userid;?>',
    pid: 'gmthai',
    t: '<?php echo $time;?>',
    seid: 'fu1304',
    sport: '8008',
    ip: '127.0.0.1',
    who: '',
    sign: '<?php echo $sid;?>',
    cminfo: 'null',
    bbsurl: escape('http://tuan565.blogspot.com/'),
    homeurl: escape('http://tuan565.blogspot.com/'),
    infourl: escape('http://tuan565.blogspot.com/'),
    shownav: escape('0'),
    bugurl: escape('http://www.gmthai.com/in_game/service?game_id=10&user_id=shidian001'),
    suggesturl: escape('http://www.gmthai.com/in_game/service?game_id=10 &user_id=shidian001'),
    saveUrl: escape('http://tuan565.blogspot.com/'),
    pl: 'null',
    client: 'null',
    microClientURL: escape('http://tuan565.blogspot.com/'),
    gmpanel: '0',
    server: 'null',
    gameid: 'null'
  };
  var ruffle = window.RufflePlayer.newest();
  var player = ruffle.createPlayer();
  document.getElementById('Main').appendChild(player);
  player.load({ url: 'Main.swf', backgroundColor: '#000000', parameters: flashvars });
})();
</script>
</body>
</html>
