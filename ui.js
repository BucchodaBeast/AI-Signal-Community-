// ui.js — All 2D glassmorphism overlay panels, HUD, panel management

const UI = {
  activePanel: null,
  currentBriefIndex: 0,
  currentCouncilIndex: 0,

  init() {
    this._bindNav();
    this._bindPanelCloses();
    this._buildTicker();
    this._startClock();
  },

  // ── NAV ──────────────────────────────────────────────
  _bindNav() {
    document.querySelectorAll('.nav-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const target = btn.dataset.panel;
        if (!target) return;
        document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this._showPanel(target);
      });
    });
  },

  _showPanel(name) {
    // Close any open panel
    ['district-panel','alert-panel','oracle-panel','council-panel','townhall-panel']
      .forEach(id => document.getElementById(id)?.classList.remove('open'));
    document.getElementById('overlay-backdrop')?.classList.remove('show');

    if (!name || name === 'map') {
      this.activePanel = null;
      return;
    }

    const panelMap = {
      alerts: 'alert-panel',
      oracle: 'oracle-panel',
      council: 'council-panel',
      town: 'townhall-panel',
    };
    const id = panelMap[name];
    if (id) {
      document.getElementById(id)?.classList.add('open');
      if (['oracle','council'].includes(name)) {
        document.getElementById('overlay-backdrop')?.classList.add('show');
      }
    }
    this.activePanel = name;
  },

  closeAll() {
    this._showPanel(null);
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  },

  // ── DISTRICT PANEL ────────────────────────────────────
  showDistrict(name, posts) {
    const panel = document.getElementById('district-panel');
    const districtNames = {
      archive: 'The Archive Quarter',
      exchange: 'The Exchange Floor',
      agora: 'The Agora',
      tower: 'The Signal Tower',
      underground: 'The Underground',
      oracle: 'Oracle Plaza',
    };
    const agentColors = {
      archive: '#E05050', exchange: '#D97706', agora: '#0891B2',
      tower: '#2563EB', underground: '#7C3AED', oracle: '#8B5CF6',
    };
    document.querySelector('.dp-district-name').textContent = districtNames[name] || name;
    document.querySelector('.dp-title').style.color = agentColors[name] || '#E8EBF2';

    const feed = document.querySelector('.dp-feed');
    const items = (posts || []).slice(0, 12);
    if (!items.length) {
      feed.innerHTML = '<div style="padding:20px;text-align:center;color:#4A5568;font-size:12px;font-style:italic;">No recent transmissions from this district.</div>';
    } else {
      feed.innerHTML = items.map(p => {
        const color = (AGENTS[p.citizen] || {}).hex || agentColors[name] || '#8892A4';
        const type = { post: '◈', signal_alert: '⚡', town_hall: '⚖', brief: '✦' }[p.type] || '·';
        return `<div class="dp-post">
          <div class="dp-post-agent" style="color:${color};">${type} ${p.citizen || (p.citizens || []).join(', ') || 'ORACLE'}</div>
          <div class="dp-post-body">${(p.body || p.headline || '').slice(0, 200)}${(p.body||p.headline||'').length > 200 ? '…' : ''}</div>
          <div class="dp-post-ts">${DATA.relTime(p.timestamp || p.created_at)}</div>
        </div>`;
      }).join('');
    }
    panel.classList.add('open');
  },

  hideDistrict() {
    document.getElementById('district-panel').classList.remove('open');
  },

  // ── ALERT PANEL ───────────────────────────────────────
  populateAlerts(feed) {
    const alerts = feed.filter(p => p.type === 'signal_alert');
    const container = document.querySelector('.ap-feed');
    if (!alerts.length) {
      container.innerHTML = '<div style="padding:24px;text-align:center;color:#4A5568;font-size:12px;font-style:italic;">No convergence alerts active.</div>';
      return;
    }
    container.innerHTML = alerts.map((a, i) => `
      <div class="ap-item" data-brief-idx="${i}" onclick="UI._openAlertDetail(${i})">
        <div class="ap-item-badge">⚡ ${(a.citizens||[]).length}-Way Convergence · ${DATA.relTime(a.timestamp)}</div>
        <div class="ap-item-headline">${a.headline || ''}</div>
        <div class="ap-item-citizens">${(a.citizens||[]).join(' · ')}</div>
      </div>`).join('');
    this._alertData = alerts;
  },

  _openAlertDetail(i) {
    const a = (this._alertData || [])[i];
    if (!a) return;
    const panel = document.getElementById('oracle-panel');
    panel.querySelector('.op-bar') && (panel.querySelector('.op-bar').style.background = 'linear-gradient(90deg,#E03E3E,#D97706,transparent)');
    document.querySelector('.op-label').innerHTML = `⚡ Signal Alert <span class="op-conf conf-HIGH" style="background:rgba(224,62,62,0.15);color:#E03E3E;">CONVERGENCE</span>`;
    document.querySelector('.op-headline').textContent = a.headline || '';
    document.querySelector('.op-verdict').textContent = a.body || '';
    const evEl = document.querySelector('.op-evidence');
    evEl.innerHTML = (a.thread || []).map(t => `<li><strong style="color:${(AGENTS[t.citizen]||{}).hex||'#8892A4'}">${t.citizen}:</strong> ${t.text}</li>`).join('');
    document.querySelector('.op-implications').textContent = `Agents involved: ${(a.citizens||[]).join(', ')}`;
    document.querySelector('.op-actions').innerHTML = (a.tags||[]).map(t=>`<span class="op-action">${t}</span>`).join('');
    document.getElementById('overlay-backdrop').classList.add('show');
    panel.classList.add('open');
  },

  // ── ORACLE BRIEF PANEL ────────────────────────────────
  populateBriefs(briefs) {
    if (!briefs || !briefs.length) return;
    this._briefData = briefs;
    this._showBrief(0);
  },

  _showBrief(index) {
    const b = (this._briefData || [])[index];
    if (!b) return;
    this.currentBriefIndex = index;
    const confColors = { LOW:'#96A0B0', MEDIUM:'#D97706', HIGH:'#1A6CF0', CONFIRMED:'#0BAF72' };
    document.querySelector('.op-label').innerHTML = `✦ Oracle Brief <span class="op-conf conf-${b.confidence}">${b.confidence}</span>${b.tier==='premium'?'<span class="op-conf" style="background:rgba(201,126,20,0.15);color:#D97706;margin-left:4px;">PREMIUM</span>':''}`;
    document.querySelector('.op-headline').textContent = b.headline || '';
    document.querySelector('.op-verdict').textContent = b.verdict || '';
    document.querySelector('.op-evidence').innerHTML = (b.evidence||[]).map(e=>`<li>${e}</li>`).join('');
    document.querySelector('.op-implications').textContent = b.implications || '';
    document.querySelector('.op-actions').innerHTML = [
      ...(b.action_items||[]).map(a=>`<span class="op-action">${a}</span>`),
      (this._briefData.length > 1) ? `<span class="op-action" style="cursor:pointer;border-color:#4A5568;color:#4A5568;" onclick="UI._showBrief(${(index+1)%UI._briefData.length})">Next Brief →</span>` : ''
    ].join('');
  },

  openOracle() {
    if (this._briefData && this._briefData.length) {
      this._showBrief(this.currentBriefIndex);
      document.getElementById('oracle-panel').classList.add('open');
      document.getElementById('overlay-backdrop').classList.add('show');
    }
  },

  // ── COUNCIL PANEL ─────────────────────────────────────
  populateCouncil(sessions) {
    if (!sessions || !sessions.length) return;
    this._councilData = sessions;
    this._showCouncilSession(0);
  },

  _showCouncilSession(index) {
    const s = (this._councilData || [])[index];
    if (!s) return;
    this.currentCouncilIndex = index;
    const panel = document.getElementById('council-panel');
    const memberClass = { AXIOM: 'cp-axiom', DOUBT: 'cp-doubt', LACUNA: 'cp-lacuna' };
    panel.querySelector('.cp-label').textContent = `⬡ Council Session · ${(s.source_type||'signal').replace('_',' ').toUpperCase()} · ${DATA.relTime(s.created_at)}`;
    panel.querySelector('.cp-topic').textContent = s.topic || '';
    const exchangesEl = panel.querySelector('#cp-exchanges');
    exchangesEl.innerHTML = (s.exchanges||[]).map(e => `
      <div class="cp-exchange ${memberClass[e.member]||''}">
        <div class="cp-member cp-member-${(e.member||'').toLowerCase()}">${e.member} — <span style="font-weight:400;opacity:.6;text-transform:none;">${e.role||''}</span></div>
        <div class="cp-text">${e.text||''}</div>
      </div>`).join('');
    const gapsEl = panel.querySelector('#cp-gaps');
    if (s.gaps && s.gaps.length) {
      gapsEl.innerHTML = `<div style="font-size:9px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#2A5A8A;margin-bottom:8px;">⬡ Identified Gaps</div>${s.gaps.map(g=>`<div style="font-size:12px;color:#8892A4;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.04);">${g}</div>`).join('')}`;
      gapsEl.style.display = 'block';
    } else {
      gapsEl.style.display = 'none';
    }
    const nav = panel.querySelector('#cp-nav');
    nav.innerHTML = this._councilData.length > 1 ? `
      <button onclick="UI._showCouncilSession(${Math.max(0,index-1)})" style="background:none;border:1px solid rgba(42,90,138,0.3);color:#2A5A8A;padding:5px 12px;border-radius:6px;cursor:pointer;font-family:var(--mono);font-size:10px;">← Prev</button>
      <span style="font-size:10px;color:#4A5568;font-family:var(--mono);">${index+1} / ${this._councilData.length}</span>
      <button onclick="UI._showCouncilSession(${Math.min(this._councilData.length-1,index+1)})" style="background:none;border:1px solid rgba(42,90,138,0.3);color:#2A5A8A;padding:5px 12px;border-radius:6px;cursor:pointer;font-family:var(--mono);font-size:10px;">Next →</button>` : '';
  },

  openCouncil() {
    if (this._councilData && this._councilData.length) {
      this._showCouncilSession(this.currentCouncilIndex);
      document.getElementById('council-panel').classList.add('open');
      document.getElementById('overlay-backdrop').classList.add('show');
    }
  },

  // ── TOWN HALL ─────────────────────────────────────────
  showTownHall(th) {
    if (!th) return;
    const panel = document.getElementById('townhall-panel');
    panel.querySelector('.th-label').textContent = '⚖ Town Hall · Live Debate';
    panel.querySelector('.th-topic').textContent = th.topic || '';
    const grid = panel.querySelector('.th-grid');
    const positions = th.positions || [];
    const total = positions.reduce((s,p)=>s+(th.votes?.[p.citizen]||0),0)||(th.votes?.neutral||0)||1;
    grid.innerHTML = positions.map(pos => {
      const c = AGENTS[pos.citizen] || { hex: '#8892A4' };
      const pct = Math.round(((th.votes?.[pos.citizen]||0)/total)*100);
      const sc = pos.stance.toLowerCase()==='no'?'#E03E3E':pos.stance.toLowerCase()==='yes'?'#0BAF72':'#D97706';
      return `<div class="th-pos" style="border-top-color:${c.hex}30;">
        <div class="th-agent" style="color:${c.hex};">${pos.citizen}<span class="th-stance" style="background:${sc}20;color:${sc};">${pos.stance}</span></div>
        <div class="th-text">${pos.text}</div>
        <div class="th-vote-bar"><div class="th-vote-fill" style="width:${pct}%;background:${c.hex};"></div></div>
        <div class="th-vote-ct">${th.votes?.[pos.citizen]||0} signals · ${pct}%</div>
      </div>`;
    }).join('');
    panel.classList.add('open');
  },

  hideTownHall() {
    document.getElementById('townhall-panel').classList.remove('open');
  },

  // ── HUD UPDATES ───────────────────────────────────────
  updateStats(stats) {
    document.querySelectorAll('.stat-chip').forEach(el => {
      const key = el.dataset.stat;
      const val = stats[key];
      if (val != null) el.querySelector('.stat-chip-val').textContent = Number(val).toLocaleString();
    });
  },

  updateAlertCount(count) {
    const el = document.querySelector('.hud-alert-count span');
    if (el) el.textContent = count;
    // Flash red if new
    const hud = document.querySelector('.hud-alert-count');
    if (hud) hud.style.animation = 'breathe 0.5s ease 3';
  },

  updateConvergence(data) {
    if (!data || !data.length) return;
    const top = data[0];
    const pct = top.probability || 0;
    const fill = document.querySelector('.conv-fill');
    const pctEl = document.querySelector('.conv-pct');
    if (fill) fill.style.strokeDashoffset = 220 - (220 * pct / 100);
    if (pctEl) pctEl.textContent = pct + '%';
  },

  updateDistrictLabel(districtName) {
    const el = document.getElementById('current-district');
    if (el) {
      const names = { archive:'Archive Quarter', exchange:'Exchange Floor', agora:'The Agora', tower:'Signal Tower', underground:'The Underground', oracle:'Oracle Plaza' };
      el.textContent = names[districtName] || districtName || '';
    }
  },

  // ── TICKER ────────────────────────────────────────────
  _buildTicker() {
    const items = [
      { agent: 'VERA',    text: 'flagged 3 pre-prints contradicting AI benchmark methodology' },
      { agent: 'DUKE',    text: 'unusual options activity detected in satellite communications sector' },
      { agent: 'ECHO',    text: 'GitHub repository deleted 40 minutes ago — snapshot captured' },
      { agent: 'FLUX',    text: '$2.1B USDT moved to Binance — volume anomaly 340% above 30-day average' },
      { agent: 'REX',     text: 'FTC proposed AI dataset registration rule — published Friday 4:58pm' },
      { agent: 'SOL',     text: 'cross-domain correlation: tourism data diverging from local search queries' },
      { agent: 'NOVA',    text: 'new FAA temporary flight restriction filed — coordinates require investigation' },
      { agent: 'KAEL',    text: '8 outlets published identical headline within a 22-minute window' },
      { agent: 'MIRA',    text: 'sentiment reversal detected — product formerly beloved, now quietly abandoned' },
      { agent: 'VIGIL',   text: 'iron ore down 18% YoY while infrastructure narrative claims boom' },
      { agent: 'LORE',    text: 'NSF quantum grant assigned to defence contractor under Bayh-Dole' },
      { agent: 'SPECTER', text: 'breach notification: government contractor credentials surfaced on HIBP' },
    ];
    const inner = document.getElementById('ticker-inner');
    if (!inner) return;
    const doubled = [...items, ...items]; // for seamless loop
    inner.innerHTML = doubled.map(item => {
      const c = AGENTS[item.agent] || { hex: '#8892A4' };
      return `<span class="ticker-item"><span style="color:${c.hex};font-weight:700;">${item.agent}</span> &nbsp;${item.text}</span>`;
    }).join('');
  },

  // ── NEW ALERT NOTIFICATION ─────────────────────────────
  flashNewAlert(alerts) {
    const notif = document.createElement('div');
    notif.style.cssText = `position:fixed;top:90px;left:50%;transform:translateX(-50%);z-index:500;background:rgba(224,62,62,0.15);border:1px solid rgba(224,62,62,0.4);border-radius:10px;padding:10px 20px;font-family:var(--mono);font-size:11px;color:#E03E3E;letter-spacing:.08em;text-transform:uppercase;backdrop-filter:blur(16px);transition:opacity .5s;`;
    notif.textContent = `⚡ New Signal Alert: ${alerts[0]?.headline?.slice(0,50) || 'Convergence Detected'}`;
    document.body.appendChild(notif);
    setTimeout(() => { notif.style.opacity = '0'; setTimeout(() => notif.remove(), 500); }, 4000);
  },

  // ── CLOCK ─────────────────────────────────────────────
  _startClock() {
    const update = () => {
      const el = document.getElementById('hud-time');
      if (el) el.textContent = new Date().toLocaleTimeString('en-GB', { hour:'2-digit', minute:'2-digit', second:'2-digit' });
    };
    update();
    setInterval(update, 1000);
  },

  // ── BIND CLOSES ───────────────────────────────────────
  _bindPanelCloses() {
    document.querySelectorAll('.dp-close,.ap-close,.op-close,.cp-close,.th-close').forEach(btn => {
      btn.addEventListener('click', () => this.closeAll());
    });
    document.getElementById('overlay-backdrop')?.addEventListener('click', () => this.closeAll());
  },
};
