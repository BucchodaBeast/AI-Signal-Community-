// agents.js — Agent definitions, avatar logic, district assignments

const AGENTS = {
  VERA:    { color: 0xE05050, hex: '#E05050', district: 'archive',   title: 'Contrarian Archivist',      icon: '📄', tagline: "Everything important happened before you noticed it." },
  DUKE:    { color: 0xD97706, hex: '#D97706', district: 'exchange',  title: 'Market Anthropologist',     icon: '📊', tagline: "Price is the only honest signal. Everything else is theater." },
  MIRA:    { color: 0x0891B2, hex: '#0891B2', district: 'agora',     title: 'Sentiment Archaeologist',   icon: '💬', tagline: "What people don't say tells you more than what they do." },
  SOL:     { color: 0x059669, hex: '#059669', district: 'tower',     title: 'The Pattern Priest',        icon: '🔗', tagline: "Coincidence is just a pattern you haven't named yet." },
  NOVA:    { color: 0x2563EB, hex: '#2563EB', district: 'tower',     title: 'Infrastructure Whisperer',  icon: '📡', tagline: "The future announces itself in boring permit filings." },
  ECHO:    { color: 0x7C3AED, hex: '#7C3AED', district: 'underground', title: 'Disappeared Content',    icon: '👁', tagline: "The most important thing on the internet is what's been deleted." },
  KAEL:    { color: 0xDB2777, hex: '#DB2777', district: 'agora',     title: 'Narrative Auditor',         icon: '📰', tagline: "Every story has a story." },
  FLUX:    { color: 0xC0392B, hex: '#C0392B', district: 'exchange',  title: 'Capital Flow Tracker',      icon: '💹', tagline: "Capital moves before news does. Always." },
  REX:     { color: 0x7D3C98, hex: '#7D3C98', district: 'tower',     title: 'Regulatory Scanner',        icon: '⚖', tagline: "Power announces itself in paperwork. I read the paperwork." },
  VIGIL:   { color: 0x5D6D1E, hex: '#5D6D1E', district: 'exchange',  title: 'Physical World Tracker',   icon: '🚢', tagline: "Ships don't lie. Follow the atoms." },
  LORE:    { color: 0x8B6914, hex: '#8B6914', district: 'archive',   title: 'Patent & IP Intelligence',  icon: '🔍', tagline: "Ownership precedes announcements. Always." },
  SPECTER: { color: 0x2C3E7A, hex: '#2C3E7A', district: 'archive',   title: 'The Dark Mirror',           icon: '🪞', tagline: "History doesn't repeat. But it plagiarises shamelessly." },
};

const DISTRICT_POSITIONS = {
  archive:     { x: -120, z: -80 },
  exchange:    { x:  120, z: -80 },
  agora:       { x:    0, z:  80 },
  tower:       { x:    0, z:    0 },
  underground: { x: -120, z:  80 },
  oracle:      { x:    0, z: -20 },
};

class AgentAvatar {
  constructor(name, scene, THREE) {
    this.name = name;
    this.agent = AGENTS[name];
    this.scene = scene;
    this.THREE = THREE;
    this.mesh = null;
    this.target = new THREE.Vector3();
    this.speed = 0.015 + Math.random() * 0.01;
    this.waitTimer = 0;
    this.waiting = false;
    this.trail = [];
    this.glowLight = null;
    this._build();
    this._assignHome();
  }

  _build() {
    const THREE = this.THREE;
    const col = this.agent.color;
    const group = new THREE.Group();

    // Body
    const bodyGeo = new THREE.CylinderGeometry(0.4, 0.5, 1.6, 8);
    const bodyMat = new THREE.MeshPhongMaterial({ color: col, emissive: col, emissiveIntensity: 0.3 });
    const body = new THREE.Mesh(bodyGeo, bodyMat);
    body.position.y = 0.8;
    group.add(body);

    // Head
    const headGeo = new THREE.SphereGeometry(0.38, 8, 8);
    const headMat = new THREE.MeshPhongMaterial({ color: col, emissive: col, emissiveIntensity: 0.5 });
    const head = new THREE.Mesh(headGeo, headMat);
    head.position.y = 1.9;
    group.add(head);

    // Glow point light
    const light = new THREE.PointLight(col, 0.6, 8);
    light.position.y = 1.5;
    group.add(light);
    this.glowLight = light;

    // Name sprite (canvas texture)
    const canvas = document.createElement('canvas');
    canvas.width = 128; canvas.height = 32;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = this.agent.hex;
    ctx.font = 'bold 18px DM Mono, monospace';
    ctx.textAlign = 'center';
    ctx.fillText(this.name, 64, 22);
    const tex = new THREE.CanvasTexture(canvas);
    const spriteMat = new THREE.SpriteMaterial({ map: tex, transparent: true });
    const sprite = new THREE.Sprite(spriteMat);
    sprite.scale.set(4, 1, 1);
    sprite.position.y = 3.2;
    group.add(sprite);

    this.mesh = group;
    this.scene.add(group);
  }

  _assignHome() {
    const dp = DISTRICT_POSITIONS[this.agent.district];
    const spread = 40;
    this.home = new this.THREE.Vector3(
      dp.x + (Math.random() - 0.5) * spread,
      0,
      dp.z + (Math.random() - 0.5) * spread
    );
    this.mesh.position.copy(this.home);
    this._pickNewTarget();
  }

  _pickNewTarget() {
    const dp = DISTRICT_POSITIONS[this.agent.district];
    const spread = 35;
    // Occasionally walk to oracle plaza
    if (Math.random() < 0.08) {
      const op = DISTRICT_POSITIONS.oracle;
      this.target.set(
        op.x + (Math.random() - 0.5) * 20,
        0,
        op.z + (Math.random() - 0.5) * 20
      );
    } else {
      this.target.set(
        dp.x + (Math.random() - 0.5) * spread,
        0,
        dp.z + (Math.random() - 0.5) * spread
      );
    }
    this.waitTimer = 2 + Math.random() * 4;
    this.waiting = false;
  }

  update(delta) {
    if (this.waiting) {
      this.waitTimer -= delta;
      if (this.waitTimer <= 0) this._pickNewTarget();
      // Bob in place
      this.mesh.position.y = Math.sin(Date.now() * 0.003) * 0.1;
      return;
    }

    const dir = new this.THREE.Vector3().subVectors(this.target, this.mesh.position);
    const dist = dir.length();

    if (dist < 1.5) {
      this.waiting = true;
      this.waitTimer = 3 + Math.random() * 5;
      return;
    }

    dir.normalize();
    this.mesh.position.addScaledVector(dir, this.speed * delta * 60);
    this.mesh.position.y = 0;

    // Face direction of travel
    const angle = Math.atan2(dir.x, dir.z);
    this.mesh.rotation.y = angle;

    // Walking bob
    this.mesh.position.y = Math.abs(Math.sin(Date.now() * 0.008)) * 0.15;

    // Pulse glow
    this.glowLight.intensity = 0.4 + Math.sin(Date.now() * 0.004) * 0.2;
  }

  alertMode(on) {
    this.glowLight.intensity = on ? 2.5 : 0.6;
    this.speed = on ? 0.04 : 0.015 + Math.random() * 0.01;
    if (on) {
      const op = DISTRICT_POSITIONS.oracle;
      this.target.set(op.x + (Math.random()-0.5)*15, 0, op.z + (Math.random()-0.5)*15);
      this.waiting = false;
    }
  }
}

// Export
if (typeof module !== 'undefined') module.exports = { AGENTS, DISTRICT_POSITIONS, AgentAvatar };
