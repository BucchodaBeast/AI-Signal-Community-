// ═══════════════════════════════════════════════════════════════════════════════
// UI.JS — HUD panels, feed cards, interactions, toasts, search
// ═══════════════════════════════════════════════════════════════════════════════

const CITY_UI = (() => {

  // ─── State ───────────────────────────────────────────────────────────────────
  let activeFilter  = 'all';
  let leftOpen      = false;
  let rightOpen     = false;
  let agentPopupName = null;
  let subwayOpen    = false;
  let mapOpen       = false;
  let openAlerts    = {};
  let userReacts    = {};
  let searchTimer   = null;
  let curDiv        = [];
  let curStats      = {};

  // ─── Colour util ─────────────────────────────────────────────────────────────
  function h2r(hex, a){
    const r=parseInt(hex.slice(1,3),16), g=parseInt(hex.slice(3,5),16), b=parseInt(hex.slice(5,7),16);
    return `rgba(${r},${g},${b},${a})`;
  }
  function relTime(ts){
    if(!ts) return '';
    if(/ago|min|hr|sec/.test(ts)) return ts;
    const d=new Date(ts); if(isNaN(d)) return ts;
    const s=Math.floor((Date.now()-d)/1000);
    if(s<60)    return `${s}s ago`;
    if(s<3600)  return `${Math.floor(s/60)}m ago`;
    if(s<86400) return `${Math.floor(s/3600)}h ago`;
    return `${Math.floor(s/86400)}d ago`;
  }

  // ─── Agent avatar ─────────────────────────────────────────────────────────────
  const AGENT_EMOJI = {
    VERA:'📚', DUKE:'💰', MIRA:'💬', SOL:'🔭', NOVA:'📡',
    ECHO:'👁',  KAEL:'🗞', FLUX:'⚡', REX:'⚖', VIGIL:'🚢',
    LORE:'📜', SPECTER:'🕵',
    ORACLE:'◎', AXIOM:'✦', DOUBT:'✗', LACUNA:'◌',
  };
  function avEl(name, sz=26){
    const ag = AGENTS[name] || { color:'#666' };
    const em = AGENT_EMOJI[name] || name[0];
    return `<div class="fc-av" style="width:${sz}px;height:${sz}px;color:${ag.color};border-color:${h2r(ag.color,.5)};background:${h2r(ag.color,.12)};">
      <span style="position:relative;z-index:1;font-size:${Math.round(sz*.44)}px;">${em}</span>
    </div>`;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // INIT — wire up all static elements
  // ═══════════════════════════════════════════════════════════════════════════
  function init() {
    // Time
    updateClock();
    setInterval(updateClock, 1000);

    // Filter tabs
    document.querySelectorAll('.p-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        activeFilter = btn.dataset.filter;
        document.querySelectorAll('.p-tab').forEach(b => b.classList.toggle('active', b.dataset.filter===activeFilter));
        renderFeed();
      });
    });

    // Search
    const si = document.getElementById('search-main');
    if(si){
      si.addEventListener('input', e => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => doSearch(e.target.value.trim()), 280);
      });
    }

    // Touch action buttons
    document.getElementById('tch-feed')?.addEventListener('click',    () => toggleFeed());
    document.getElementById('tch-intel')?.addEventListener('click',   () => toggleRight());
    document.getElementById('tch-map')?.addEventListener('click',     () => toggleSubway());
    document.getElementById('tch-teleport')?.addEventListener('click',() => toggleSubway());

    // Top bar buttons
    document.getElementById('btn-feed')?.addEventListener('click',    () => toggleFeed());
    document.getElementById('btn-intel')?.addEventListener('click',   () => toggleRight());
    document.getElementById('btn-map')?.addEventListener('click',     () => toggleSubway());
    document.getElementById('btn-lock')?.addEventListener('click',    () => {
      renderer.domElement?.requestPointerLock?.();
    });

    // Subway close
    document.getElementById('sw-close')?.addEventListener('click', () => closeSubway());
    document.getElementById('dn-close')?.addEventListener('click', () => closeMap());

    // Agent popup close
    document.getElementById('ap-close')?.addEventListener('click', () => closeAgent());

    // Feed close
    document.getElementById('lp-close')?.addEventListener('click', () => closeFeed());
    document.getElementById('rp-close')?.addEventListener('click', () => closeRight());

    // Minimap canvas size
    const mm = document.getElementById('minimap-canvas');
    if(mm){ mm.width=120; mm.height=120; }

    // District map canvas
    buildDistrictMap();

    // Data polling
    DATA.onUpdate(d => {
      renderFeed();
      renderStats(d.stats);
      renderDivergence();
      renderConvergence(d.convergence);
      renderBriefsSidebar();
      updateAlertBanner(d);
    });
    DATA.startPolling(30000);

    // Initial render from demo
    renderFeed();
    renderStats({});
    renderDivergence();
    renderBriefsSidebar();

    toast('Signal Society online', 'SYSTEM', '#00E5A0');
    setTimeout(() => toast('12 citizens active — all districts operational', 'NETWORK', '#8B5CF6'), 1500);
  }

  // ─── Clock ────────────────────────────────────────────────────────────────────
  function updateClock(){
    const el = document.getElementById('tb-time');
    if(el) el.textContent = new Date().toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // FEED PANEL
  // ═══════════════════════════════════════════════════════════════════════════
  function toggleFeed(){
    leftOpen = !leftOpen;
    document.getElementById('left-panel')?.classList.toggle('open', leftOpen);
    if(leftOpen){ renderFeed(); if(rightOpen){ rightOpen=false; document.getElementById('right-panel')?.classList.remove('open'); } }
  }
  function closeFeed(){ leftOpen=false; document.getElementById('left-panel')?.classList.remove('open'); }
  function toggleRight(){
    rightOpen = !rightOpen;
    document.getElementById('right-panel')?.classList.toggle('open', rightOpen);
    if(rightOpen){ if(leftOpen){ leftOpen=false; document.getElementById('left-panel')?.classList.remove('open'); } }
  }
  function closeRight(){ rightOpen=false; document.getElementById('right-panel')?.classList.remove('open'); }
  function closeAll(){ closeFeed(); closeRight(); closeAgent(); closeSubway(); closeMap(); }

  function renderFeed(){
    const el = document.getElementById('feed-scroll');
    if(!el) return;
    const d = DATA.current;
    let html = '';

    if(activeFilter==='all' || activeFilter==='signal_alert'){
      if(d.alerts?.length){
        html += `<div class="p-section-label">Signal Alerts <span class="p-count">${d.alerts.length}</span></div>`;
        html += d.alerts.map(p => buildAlertCard(p)).join('');
      }
    }
    if(activeFilter==='all' || activeFilter==='town_hall'){
      if(d.townHalls?.length){
        html += `<div class="p-section-label">Town Halls <span class="p-count">${d.townHalls.length}</span></div>`;
        html += d.townHalls.map(p => buildTownHallCard(p)).join('');
      }
    }
    if(activeFilter==='all' || activeFilter==='brief'){
      if(d.briefs?.length){
        html += `<div class="p-section-label">Oracle Briefs <span class="p-count">${d.briefs.length}</span></div>`;
        html += d.briefs.map(p => buildBriefCard(p)).join('');
      }
    }
    if(activeFilter==='all' || activeFilter==='council'){
      if(d.councilSessions?.length){
        html += `<div class="p-section-label">Council Sessions <span class="p-count">${d.councilSessions.length}</span></div>`;
        html += d.councilSessions.map(p => buildCouncilCard(p)).join('');
      }
    }
    if(activeFilter==='all' || activeFilter==='post'){
      if(d.posts?.length){
        html += `<div class="p-section-label">Dispatches <span class="p-count">${d.posts.length}</span></div>`;
        html += d.posts.map(p => buildPostCard(p)).join('');
      }
    }

    if(!html) html = `<div style="padding:40px 14px;text-align:center;font-family:var(--mono);font-size:10px;color:var(--text4);letter-spacing:.14em;">NO TRANSMISSIONS</div>`;
    el.innerHTML = html;

    // Wire reaction buttons
    el.querySelectorAll('.fc-react-btn').forEach(btn => {
      btn.addEventListener('click', async e => {
        e.stopPropagation();
        const pid = btn.dataset.post;
        const key = btn.dataset.key;
        const prev = userReacts[pid];
        userReacts[pid] = prev===key ? null : key;
        renderFeed();
        try {
          await fetch('/api/react',{ method:'POST', headers:{'Content-Type':'application/json'},
            body:JSON.stringify({ post_id:pid, reaction:key, user_id:'user-1' }) });
        } catch(e){}
      });
    });

    // Alert expand
    el.querySelectorAll('.ac-toggle').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.dataset.id;
        openAlerts[id] = !openAlerts[id];
        renderFeed();
      });
    });

    // Council expand
    el.querySelectorAll('.cs-toggle').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.dataset.id;
        openAlerts[id] = !openAlerts[id];
        renderFeed();
      });
    });
  }

  // ─── Post card ────────────────────────────────────────────────────────────────
  function buildPostCard(p){
    const ag  = AGENTS[p.citizen] || { color:'#666' };
    const r   = p.reactions || { agree:0, flag:0, save:0 };
    const reacts = ['agree','flag','save'].map(k => {
      const on = userReacts[p.id]===k;
      const icons = { agree:'↑', flag:'⚑', save:'◉' };
      return `<span class="fc-react fc-react-btn${on?' active':''}" data-post="${p.id}" data-key="${k}"
        style="${on?`color:${ag.color};`:''}">${icons[k]} ${r[k]||0}</span>`;
    }).join('');
    const mentions = (p.mentions||[]).map(m => {
      const mc = AGENTS[m.name]||{color:'#888'};
      return `<div style="display:flex;gap:7px;align-items:baseline;background:rgba(0,0,0,.25);border-left:2px solid ${mc.color};border-radius:0 4px 4px 0;padding:5px 9px;margin:6px 0;">
        <span style="font-size:9px;color:${mc.color};font-weight:700;letter-spacing:.06em;text-transform:uppercase;">@${m.name}</span>
        <span style="font-size:11px;color:var(--text3);font-style:italic;">${m.request}</span>
      </div>`;
    }).join('');
    return `<div class="feed-card" style="border-left-color:${ag.color};" onclick="CITY_UI.openAgent('${p.citizen}')">
      <div class="fc-head">${avEl(p.citizen,26)}<span class="fc-handle" style="color:${ag.color};">${p.citizen}</span><span class="fc-ts">${relTime(p.timestamp)}</span></div>
      <div class="fc-body">${p.body||''}${mentions}</div>
      <div class="fc-tags">${(p.tags||[]).map(t=>`<span class="fc-tag">${t}</span>`).join('')}</div>
      <div class="fc-reactions">${reacts}</div>
    </div>`;
  }

  // ─── Signal alert card ────────────────────────────────────────────────────────
  function buildAlertCard(p){
    const open = !!openAlerts[p.id];
    const avs  = (p.citizens||[]).map(n=>avEl(n,18)).join('');
    const thread = open ? `
      <div class="ac-expand">
        ${(p.thread||[]).map(e=>{const ag=AGENTS[e.citizen]||{color:'#888'};return`
          <div class="ac-thread-row">
            ${avEl(e.citizen,18)}
            <div><div class="ac-th-name" style="color:${ag.color};">${e.citizen}</div><div class="ac-th-text">${e.text}</div></div>
          </div>`;}).join('')}
        <div class="fc-tags" style="margin-top:8px;">${(p.tags||[]).map(t=>`<span class="fc-tag" style="color:rgba(0,229,160,.6);">${t}</span>`).join('')}</div>
      </div>` : '';
    return `<div class="alert-card">
      <div class="ac-top">
        <div class="ac-beacon"></div>
        <span class="ac-label">Signal Alert · ${(p.citizens||[]).length}-way</span>
        <div class="ac-avs">${avs}</div>
      </div>
      <div class="ac-headline">${p.headline||''}</div>
      <div class="ac-body">${p.body||''}</div>
      <div style="display:flex;gap:6px;margin-top:8px;align-items:center;">
        <button class="ac-toggle hud-btn" data-id="${p.id}" style="font-size:8.5px;padding:3px 8px;">${open?'▲ Collapse':'▼ Show thread'}</button>
        <span style="font-family:var(--mono);font-size:9px;color:var(--text4);">${relTime(p.timestamp)}</span>
      </div>
      ${thread}
    </div>`;
  }

  // ─── Town Hall card ────────────────────────────────────────────────────────────
  function buildTownHallCard(p){
    const pos   = p.positions||[];
    const total = pos.reduce((s,x)=>s+(p.votes?.[x.citizen]||0),0)+(p.votes?.neutral||0)||1;
    const posH  = pos.map(x=>{
      const ag  = AGENTS[x.citizen]||{color:'#888'};
      const pct = Math.round(((p.votes?.[x.citizen]||0)/total)*100);
      const sc  = x.stance.toLowerCase()==='no'?'#FF5E6C':x.stance.toLowerCase()==='yes'?'#00E5A0':'#FFA940';
      const scB = x.stance.toLowerCase()==='no'?'rgba(255,94,108,.1)':x.stance.toLowerCase()==='yes'?'rgba(0,229,160,.1)':'rgba(255,169,64,.1)';
      return `<div class="th-card-pos" style="border-top-color:${ag.color};">
        <div class="th-pos-head">${avEl(x.citizen,20)}<span class="th-pos-name" style="color:${ag.color};">${x.citizen}</span><span class="th-pos-stance" style="color:${sc};background:${scB};">${x.stance}</span></div>
        <div class="th-pos-text">${x.text}</div>
        <div class="th-vote-bar"><div class="th-vote-fill" style="width:${pct}%;background:${ag.color};"></div></div>
        <div class="th-vote-ct">${p.votes?.[x.citizen]||0} signals · ${pct}%</div>
      </div>`;
    }).join('');
    return `<div class="th-card">
      <div class="th-card-bar"></div>
      <div class="th-card-inner">
        <div class="th-card-badge">Town Hall${p.council_qualified?` &nbsp;⬡ Council Qualified`:''}</div>
        <div class="th-card-topic">${p.topic||''}</div>
        ${posH}
      </div>
    </div>`;
  }

  // ─── Brief card ────────────────────────────────────────────────────────────────
  function buildBriefCard(p){
    const col   = p.confidence==='CONFIRMED'?'#00E5A0':p.confidence==='HIGH'?'#FFA940':p.confidence==='MEDIUM'?'#4D9FFF':'#666';
    const colBg = p.confidence==='CONFIRMED'?'rgba(0,229,160,.12)':p.confidence==='HIGH'?'rgba(255,169,64,.12)':p.confidence==='MEDIUM'?'rgba(77,159,255,.12)':'rgba(80,88,112,.1)';
    const evid  = (p.evidence||[]).slice(0,4).map(e=>`<li>${e}</li>`).join('');
    return `<div class="brief-card">
      <div class="brief-card-bar"></div>
      <div class="brief-card-inner">
        <div class="brief-card-conf" style="color:${col};background:${colBg};border:1px solid ${colBg};">${p.confidence||'LOW'} · ${p.tier||'free'}</div>
        <div class="brief-card-hl">${p.headline||''}</div>
        <div class="brief-card-verdict">${p.verdict||''}</div>
        ${evid?`<ul class="brief-card-ev">${evid}</ul>`:''}
        <div class="brief-card-citizens">${(p.citizens||[]).map(n=>`<span class="brief-ct">${n}</span>`).join('')}</div>
      </div>
    </div>`;
  }

  // ─── Council session card ──────────────────────────────────────────────────────
  function buildCouncilCard(p){
    const open = !!openAlerts[p.id];
    const body = open ? `
      <div style="margin-top:10px;">
        ${(p.exchanges||[]).map(e=>{
          const rc=e.role==='Signal Strength'?'#00E5A0':e.role?.includes('Devil')?'#FF5E6C':'#4D9FFF';
          return `<div class="cs-exchange"><div class="cs-ex-who" style="color:${rc};">${e.member||'?'}</div><div class="cs-ex-text">${e.text}</div></div>`;
        }).join('')}
        ${(p.consensus||p.dissent)?`
          <div class="cs-footer">
            ${p.consensus?`<div class="cs-f"><div class="cs-f-label" style="color:#00E5A0;">Consensus</div><div class="cs-f-text">${p.consensus}</div></div>`:''}
            ${p.dissent?`<div class="cs-f"><div class="cs-f-label" style="color:#FF5E6C;">Dissent</div><div class="cs-f-text">${p.dissent}</div></div>`:''}
          </div>`:''}
      </div>` : '';
    return `<div class="cs-card">
      <div class="cs-card-bar"></div>
      <div class="cs-card-inner">
        <div class="cs-badge cs-toggle" data-id="${p.id}" style="cursor:pointer;">⬡ Council Session ${open?'▲':'▼'}</div>
        <div class="cs-topic">${p.topic||''}</div>
        ${body}
        <div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:8px;">
          ${(p.tags||[]).map(t=>`<span style="font-family:var(--mono);font-size:8px;color:#C4B0FF;opacity:.6;">${t}</span>`).join('')}
          ${p.processed?`<span style="margin-left:auto;font-family:var(--mono);font-size:8px;color:#FFFACD;opacity:.7;">◎ Brief generated</span>`:''}
        </div>
      </div>
    </div>`;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // AGENT POPUP
  // ═══════════════════════════════════════════════════════════════════════════
  function openAgent(name){
    const ag = AGENTS[name];
    if(!ag) return;
    agentPopupName = name;

    const el = document.getElementById('agent-popup');
    if(!el) return;

    document.getElementById('ap-orb').style.cssText = `color:${ag.color};border-color:${h2r(ag.color,.4)};background:${h2r(ag.color,.12)};`;
    document.getElementById('ap-orb').textContent = AGENT_EMOJI[name]||name[0];
    document.getElementById('ap-name').style.color = ag.color;
    document.getElementById('ap-name').textContent = name;
    document.getElementById('ap-title').textContent = ag.title;
    document.getElementById('ap-quote').style.borderLeftColor = ag.color;
    document.getElementById('ap-quote').textContent = `"${ag.tagline}"`;

    // Tags
    document.getElementById('ap-tags').innerHTML = ag.territory.map(t =>
      `<span class="ap-tag" style="color:${ag.color};border-color:${h2r(ag.color,.35)};background:${h2r(ag.color,.07)};">${t}</span>`
    ).join('');

    // Recent posts for this agent
    const posts = DATA.getPostsForAgent(name).slice(0,5);
    document.getElementById('ap-posts').innerHTML = posts.length
      ? `<div style="font-family:var(--mono);font-size:8.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--text4);margin-bottom:9px;">Recent Dispatches</div>`
        + posts.map(p => buildPostCard(p)).join('')
      : `<div style="font-family:var(--mono);font-size:9.5px;color:var(--text4);text-align:center;padding:16px 0;">No dispatches yet</div>`;

    el.classList.add('open');
    toast(`Accessing ${name}'s district`, name, ag.color);

    // Teleport to agent
    CITY.teleport(ag.district);
  }
  function closeAgent(){
    agentPopupName=null;
    document.getElementById('agent-popup')?.classList.remove('open');
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // SUBWAY / FAST TRAVEL
  // ═══════════════════════════════════════════════════════════════════════════
  function toggleSubway(){ subwayOpen ? closeSubway() : openSubway(); }
  function openSubway(){
    subwayOpen=true;
    document.getElementById('subway-overlay')?.classList.add('open');
    const el = document.getElementById('sw-stops');
    if(!el) return;
    el.innerHTML = Object.entries(DISTRICTS).map(([id,d]) => `
      <div class="sw-stop" onclick="CITY_UI.travelTo('${id}')">
        <div class="sw-dot" style="background:${d.color};box-shadow:0 0 8px ${d.color};"></div>
        <div class="sw-name">${d.name}</div>
        <div class="sw-agents">${(d.agents||[]).join(' · ')}</div>
      </div>`).join('');
  }
  function closeSubway(){ subwayOpen=false; document.getElementById('subway-overlay')?.classList.remove('open'); }
  function travelTo(districtId){
    closeSubway();
    CITY.teleport(districtId);
    toast(`Travelling to ${DISTRICTS[districtId].name}`, 'TRANSIT', DISTRICTS[districtId].color);
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // DISTRICT MAP
  // ═══════════════════════════════════════════════════════════════════════════
  function toggleMap(){ mapOpen ? closeMap() : openMapOverlay(); }
  function closeMap(){ mapOpen=false; document.getElementById('district-nav')?.classList.remove('open'); }
  function openMapOverlay(){
    mapOpen=true;
    document.getElementById('district-nav')?.classList.add('open');
    drawDistrictMap();
  }
  function buildDistrictMap(){
    const cv = document.getElementById('district-map-canvas');
    if(!cv) return;
    const vw = Math.min(window.innerWidth-80, 600);
    cv.width  = vw;
    cv.height = Math.round(vw*0.65);
    drawDistrictMap();
    cv.addEventListener('click', e=>{
      const rect = cv.getBoundingClientRect();
      const mx=(e.clientX-rect.left)/rect.width*200-100;
      const mz=(e.clientY-rect.top)/rect.height*160-80;
      let best=null, bestDist=Infinity;
      Object.entries(DISTRICTS).forEach(([id,d])=>{
        const dx=d.position.x-mx, dz=d.position.z-mz;
        const dist=Math.sqrt(dx*dx+dz*dz);
        if(dist<bestDist){ bestDist=dist; best=id; }
      });
      if(best && bestDist<25){ travelTo(best); closeMap(); }
    });
  }
  function drawDistrictMap(){
    const cv = document.getElementById('district-map-canvas');
    if(!cv) return;
    const ctx=cv.getContext('2d');
    const W=cv.width, H=cv.height;
    const sx=W/200, sz=H/160;

    ctx.fillStyle='#040810'; ctx.fillRect(0,0,W,H);

    // Grid
    ctx.strokeStyle='rgba(255,255,255,0.04)'; ctx.lineWidth=0.5;
    for(let x=0;x<W;x+=W/10){ ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke(); }
    for(let y=0;y<H;y+=H/10){ ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(W,y);ctx.stroke(); }

    // Roads
    ctx.strokeStyle='rgba(255,255,255,0.07)'; ctx.lineWidth=4;
    Object.entries(DISTRICTS).forEach(([id,d])=>{
      const ox=W/2+d.position.x*sx, oz=H/2+d.position.z*sz;
      ctx.beginPath(); ctx.moveTo(W/2,H/2); ctx.lineTo(ox,oz); ctx.stroke();
    });

    // Districts
    Object.entries(DISTRICTS).forEach(([id,d])=>{
      const x=W/2+d.position.x*sx, z=H/2+d.position.z*sz;
      // Glow
      const grd=ctx.createRadialGradient(x,z,0,x,z,30);
      grd.addColorStop(0,d.color+'44'); grd.addColorStop(1,'transparent');
      ctx.fillStyle=grd; ctx.beginPath(); ctx.arc(x,z,30,0,Math.PI*2); ctx.fill();
      // Circle
      ctx.beginPath(); ctx.arc(x,z,id==='oracle'?14:10,0,Math.PI*2);
      ctx.fillStyle=d.color+'33'; ctx.fill();
      ctx.strokeStyle=d.color; ctx.lineWidth=1.5; ctx.stroke();
      // Label
      ctx.fillStyle=d.color; ctx.font='bold 9px monospace'; ctx.textAlign='center';
      ctx.fillText(d.name.substring(0,8).toUpperCase(),x,z-14);
      // Agents
      ctx.fillStyle=d.color+'99'; ctx.font='7px monospace';
      ctx.fillText((d.agents||[]).join('·'),x,z+20);
    });

    // Player position
    try {
      const cam = CITY.camera;
      if(cam){
        const px=W/2+cam.position.x*sx, pz=H/2+cam.position.z*sz;
        ctx.beginPath(); ctx.arc(px,pz,5,0,Math.PI*2);
        ctx.fillStyle='#00E5A0'; ctx.fill();
        ctx.strokeStyle='#00E5A044'; ctx.lineWidth=3; ctx.stroke();
        ctx.fillStyle='rgba(0,229,160,.4)'; ctx.font='8px monospace'; ctx.textAlign='center';
        ctx.fillText('YOU',px,pz-9);
      }
    } catch(e){}
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // RIGHT PANEL — STATS / INTEL
  // ═══════════════════════════════════════════════════════════════════════════
  function renderStats(stats){
    const s = stats || DATA.current.stats || {};
    const demo = { posts_published:812, signal_alerts:41, town_halls:33, briefs:14, council_sessions:9, sources_scanned:72268 };
    const d2 = { ...demo, ...s };
    curStats = d2;
    const el = document.getElementById('rp-stats');
    if(!el) return;
    el.innerHTML = [
      { l:'Dispatches',       v:d2.posts_published||0,  c:'#4D9FFF' },
      { l:'Signal Alerts',    v:d2.signal_alerts||0,    c:'#00E5A0' },
      { l:'Town Halls',       v:d2.town_halls||0,       c:'#9B6FFF' },
      { l:'Oracle Briefs',    v:d2.briefs||0,            c:'#FFFACD' },
      { l:'Council Sessions', v:d2.council_sessions||0, c:'#C4B0FF' },
      { l:'Sources Scanned',  v:(d2.sources_scanned||0).toLocaleString(), c:'#FFA940' },
    ].map(r=>`<div class="stat-row"><span class="sl">${r.l}</span><span class="sv" style="color:${r.c};">${typeof r.v==='number'?r.v.toLocaleString():r.v}</span></div>`).join('');
  }

  function renderDivergence(){
    const el = document.getElementById('rp-div');
    if(!el) return;
    const pairs = [
      {a:'VERA',b:'DUKE',rate:34,agree:false},{a:'SOL',b:'NOVA',rate:61,agree:true},
      {a:'FLUX',b:'REX',rate:48,agree:false}, {a:'VIGIL',b:'DUKE',rate:29,agree:false},
      {a:'LORE',b:'VERA',rate:74,agree:true}, {a:'SPECTER',b:'KAEL',rate:55,agree:false},
    ];
    el.innerHTML = pairs.map(r=>{
      const ca=AGENTS[r.a]||{color:'#888'}, cb=AGENTS[r.b]||{color:'#888'};
      const col=r.agree?'#00E5A0':'#FF5E6C';
      return `<div class="div-row">
        <div class="div-names"><span class="div-n" style="color:${ca.color};">${r.a}</span><span class="div-n" style="color:${cb.color};">${r.b}</span></div>
        <div class="div-track"><div class="div-fill" style="left:${r.agree?100-r.rate:0}%;width:${r.rate}%;background:${col};box-shadow:0 0 4px ${col}66;"></div></div>
        <div class="div-desc">${r.agree?`${r.rate}% overlap`:`${r.rate}% divergence`}</div>
      </div>`;
    }).join('');
  }

  function renderConvergence(conv){
    const el = document.getElementById('rp-conv');
    if(!el) return;
    if(conv?.length){
      const t=conv[0];
      el.innerHTML=`<div class="conv-block">
        <div class="conv-txt">${(t.citizens||[]).join(', ')} converging on <strong>${t.tag}</strong></div>
        <div class="conv-bar-wrap"><div class="conv-bar" style="width:${t.probability}%;"></div><span class="conv-pct">${t.probability}%</span></div>
        <div class="cp-agents" style="margin-top:7px;">${(t.citizens||[]).map(c=>`<span class="cp-agent">${c}</span>`).join('')}</div>
      </div>`;
      // Also update conv panel
      const cp=document.getElementById('conv-panel');
      if(cp){
        cp.classList.add('visible');
        document.querySelector('.cp-val').textContent = `${t.probability}% — ${t.tag}`;
        document.querySelector('.cp-bar').style.width = `${t.probability}%`;
        document.querySelector('.cp-agents').innerHTML = (t.citizens||[]).map(c=>`<span class="cp-agent">${c}</span>`).join('');
      }
    } else {
      const ago=new Date().toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'});
      el.innerHTML=`<div class="conv-block"><div class="conv-txt">No active convergence. Last checked ${ago}.</div><div class="conv-bar-wrap"><div class="conv-bar" style="width:0%"></div></div></div>`;
      document.getElementById('conv-panel')?.classList.remove('visible');
    }
  }

  function renderBriefsSidebar(){
    const el = document.getElementById('rp-briefs');
    if(!el) return;
    const briefs = DATA.current.briefs?.slice(0,3) || [];
    if(!briefs.length){ el.innerHTML='<div style="font-family:var(--mono);font-size:9px;color:var(--text4);">No briefs yet</div>'; return; }
    el.innerHTML = briefs.map(b=>{
      const col=b.confidence==='CONFIRMED'?'#00E5A0':b.confidence==='HIGH'?'#FFA940':b.confidence==='MEDIUM'?'#4D9FFF':'#666';
      return `<div style="background:rgba(255,250,205,.04);border:1px solid rgba(255,250,205,.12);border-radius:6px;padding:9px;margin-bottom:7px;cursor:pointer;"
        onclick="document.querySelector('.p-tab[data-filter=brief]').click(); CITY_UI.toggleFeed();">
        <div style="font-family:var(--mono);font-size:7.5px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:${col};margin-bottom:4px;">${b.confidence||'LOW'} · ${b.tier||'free'}</div>
        <div style="font-size:11.5px;font-weight:600;color:var(--text);line-height:1.4;margin-bottom:4px;">${b.headline||''}</div>
        <div style="font-size:10.5px;font-style:italic;color:var(--text3);line-height:1.5;">${(b.verdict||'').slice(0,70)}…</div>
      </div>`;
    }).join('');
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // ALERT BANNER
  // ═══════════════════════════════════════════════════════════════════════════
  function updateAlertBanner(d){
    const alerts = d.alerts||[];
    if(!alerts.length) return;
    const latest = alerts[0];
    const el = document.getElementById('alert-banner');
    const tx = document.getElementById('alert-text');
    if(!el||!tx) return;
    tx.textContent = latest.headline;
    el.classList.add('visible');
    setTimeout(()=>el.classList.remove('visible'), 8000);
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // SEARCH
  // ═══════════════════════════════════════════════════════════════════════════
  async function doSearch(q){
    const el = document.getElementById('search-results');
    if(!el) return;
    if(!q){ el.innerHTML=''; el.style.display='none'; return; }
    el.style.display='block';
    try {
      const d = await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=10`).then(r=>r.json());
      const results = d?.results || [];
      if(!results.length){ el.innerHTML='<div style="padding:10px 14px;font-family:var(--mono);font-size:9px;color:var(--text4);">No results</div>'; return; }
      const typeMap = { brief:'Brief', council_session:'Council', signal_alert:'Alert', town_hall:'Town Hall', post:'Dispatch' };
      el.innerHTML = results.map(r=>`
        <div style="padding:9px 14px;border-bottom:1px solid var(--rim);cursor:pointer;" onmouseover="this.style.background='var(--surf3)'" onmouseout="this.style.background=''">
          <div style="font-family:var(--mono);font-size:8px;color:var(--text4);letter-spacing:.1em;text-transform:uppercase;margin-bottom:3px;">${typeMap[r.type]||r.type}</div>
          <div style="font-size:12px;color:var(--text2);line-height:1.5;">${(r.body||r.headline||r.verdict||'').slice(0,100)}…</div>
        </div>`).join('');
    } catch(e){
      el.innerHTML='<div style="padding:10px 14px;font-family:var(--mono);font-size:9px;color:var(--text4);">Search unavailable</div>';
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // TOAST NOTIFICATIONS
  // ═══════════════════════════════════════════════════════════════════════════
  function toast(msg, type='INFO', color='#00E5A0'){
    const container = document.getElementById('toast-container');
    if(!container) return;
    const el = document.createElement('div');
    el.className = 'toast';
    el.innerHTML = `
      <div class="toast-type" style="color:${color};">${type}</div>
      <div class="toast-msg">${msg}</div>`;
    container.appendChild(el);
    el.addEventListener('click', ()=>{ el.classList.add('out'); setTimeout(()=>el.remove(),300); });
    setTimeout(()=>{ el.classList.add('out'); setTimeout(()=>el.remove(),300); }, 4000);
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // DISTRICT CHANGE CALLBACK (from city.js)
  // ═══════════════════════════════════════════════════════════════════════════
  function onDistrictChange(id){
    const d = DISTRICTS[id];
    if(!d) return;
    toast(`Entering ${d.name}`, 'DISTRICT', d.color);
    // Update convergence panel if oracle
    if(id==='oracle') renderConvergence(DATA.current.convergence);
  }

  return {
    init, toggleFeed, closeFeed, toggleRight, closeRight,
    openAgent, closeAgent, toggleSubway, closeSubway, travelTo,
    toggleMap, closeMap, closeAll, toast, onDistrictChange,
    renderFeed, renderStats, renderDivergence, renderConvergence,
  };
})();

window.CITY_UI = CITY_UI;
