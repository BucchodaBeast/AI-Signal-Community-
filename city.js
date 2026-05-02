// ═══════════════════════════════════════════════════════════════════════════════
// CITY.JS — Three.js r128 3D city engine
// Full WASD + touch joystick navigation, click-to-interact, particle systems
// ═══════════════════════════════════════════════════════════════════════════════

const CITY = (() => {

  // ─── Scene globals ───────────────────────────────────────────────────────────
  let renderer, scene, camera, clock;
  let animId, running = false;

  // ─── Navigation state ────────────────────────────────────────────────────────
  const nav = {
    moveF:false, moveB:false, moveL:false, moveR:false,
    yaw:0, pitch:0,
    speed:18,
    velocity:new THREE.Vector3(),
    joystick:{ active:false, dx:0, dz:0 },
    lookDelta:{ x:0, y:0 },
  };

  // ─── World objects ───────────────────────────────────────────────────────────
  const buildings  = [];
  const particles  = [];
  const agentMeshes = {};
  let   currentDistrict = 'oracle';

  // ─── Raycaster ───────────────────────────────────────────────────────────────
  const raycaster = new THREE.Raycaster();
  const mouse     = new THREE.Vector2();
  let   hoveredAgent = null;

  // ─── Colour helpers ──────────────────────────────────────────────────────────
  function hex(str){ return new THREE.Color(str); }
  function hexN(str, n=0.5){ return new THREE.Color(str).multiplyScalar(n); }

  // ─── Materials cache ─────────────────────────────────────────────────────────
  const MAT = {};
  function mat(color, opts={}){
    const k = color + JSON.stringify(opts);
    if(!MAT[k]) MAT[k] = new THREE.MeshStandardMaterial({ color:hex(color), ...opts });
    return MAT[k];
  }
  function matGlass(color){
    return new THREE.MeshPhysicalMaterial({
      color:hex(color), transparent:true, opacity:0.18,
      roughness:0.05, metalness:0.1, transmission:0.8,
      side:THREE.DoubleSide,
    });
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // INIT
  // ═══════════════════════════════════════════════════════════════════════════
  function init(canvas) {
    // Renderer
    renderer = new THREE.WebGLRenderer({ canvas, antialias:true, powerPreference:'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 0.9;
    renderer.outputEncoding = THREE.sRGBEncoding;
    renderer.setClearColor(0x040608);

    // Scene
    scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x060810, 0.012);

    // Camera — start above centre
    camera = new THREE.PerspectiveCamera(70, window.innerWidth/window.innerHeight, 0.1, 800);
    camera.position.set(0, 4, 20);
    camera.rotation.order = 'YXZ';

    clock = new THREE.Clock();

    buildLighting();
    buildGround();
    buildSky();
    buildAllDistricts();
    buildDataStreams();
    buildParticleSystem();

    window.addEventListener('resize', onResize);
    return { renderer, scene, camera };
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // LIGHTING
  // ═══════════════════════════════════════════════════════════════════════════
  function buildLighting() {
    // Ambient — deep blue night
    scene.add(new THREE.AmbientLight(0x080E1A, 1.0));

    // Moon-like directional
    const dir = new THREE.DirectionalLight(0x8899CC, 0.6);
    dir.position.set(50, 100, -30);
    dir.castShadow = true;
    dir.shadow.camera.near = 0.1;
    dir.shadow.camera.far  = 500;
    dir.shadow.camera.left = dir.shadow.camera.bottom = -200;
    dir.shadow.camera.right = dir.shadow.camera.top = 200;
    dir.shadow.mapSize.set(2048, 2048);
    dir.shadow.bias = -0.001;
    scene.add(dir);

    // Warm fill from below (city glow)
    const fill = new THREE.HemisphereLight(0x1a2040, 0x0D1020, 0.5);
    scene.add(fill);

    // District accent lights
    const districtLights = [
      { pos:[0,2,0],    color:0x6B21FF, intensity:3 },  // oracle
      { pos:[-80,2,70], color:0x1a3a8a, intensity:2 },  // archive
      { pos:[80,2,70],  color:0x8a5a00, intensity:2 },  // exchange
      { pos:[-60,2,-70],color:0x005a70, intensity:2 },  // agora
      { pos:[80,2,-70], color:0x002a8a, intensity:2 },  // tower
      { pos:[0,2,90],   color:0x4a007a, intensity:2 },  // underground
    ];
    districtLights.forEach(({ pos, color, intensity }) => {
      const pt = new THREE.PointLight(color, intensity, 60, 2);
      pt.position.set(...pos);
      scene.add(pt);
    });
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // GROUND
  // ═══════════════════════════════════════════════════════════════════════════
  function buildGround() {
    // Main ground plane
    const geo = new THREE.PlaneGeometry(600, 600, 80, 80);
    const groundMat = new THREE.MeshStandardMaterial({
      color:0x050810, roughness:0.95, metalness:0.05,
    });
    const ground = new THREE.Mesh(geo, groundMat);
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    scene.add(ground);

    // Grid overlay
    const gridHelper = new THREE.GridHelper(600, 80, 0x0D1525, 0x0A1020);
    gridHelper.position.y = 0.02;
    scene.add(gridHelper);

    // Roads between districts
    buildRoads();

    // Ground-level glow planes at each district
    Object.entries(DISTRICTS).forEach(([id, dist]) => {
      const glowGeo = new THREE.CircleGeometry(30, 32);
      const glowMat = new THREE.MeshBasicMaterial({
        color:hex(dist.color), transparent:true, opacity:0.04,
        depthWrite:false, side:THREE.DoubleSide,
      });
      const glow = new THREE.Mesh(glowGeo, glowMat);
      glow.rotation.x = -Math.PI/2;
      glow.position.set(dist.position.x, 0.05, dist.position.z);
      scene.add(glow);
    });
  }

  function buildRoads() {
    const roadMat = new THREE.MeshStandardMaterial({
      color:0x0A0F1A, roughness:0.9, metalness:0.05,
    });
    const lineMat = new THREE.MeshBasicMaterial({ color:0x1A2535 });

    // Main radial roads from centre
    const routes = [
      [[0,0],[0,100]],  [[0,0],[0,-100]],
      [[0,0],[100,0]],  [[0,0],[-100,0]],
      [[0,0],[-80,70]], [[0,0],[80,70]],
      [[0,0],[-60,-70]],[[0,0],[80,-70]],
    ];

    routes.forEach(([[x1,z1],[x2,z2]]) => {
      const len = Math.hypot(x2-x1, z2-z1);
      const angle = Math.atan2(z2-z1, x2-x1);
      const road = new THREE.Mesh(new THREE.PlaneGeometry(len, 8, 1, 1), roadMat);
      road.rotation.x = -Math.PI/2;
      road.rotation.z = -angle;
      road.position.set((x1+x2)/2, 0.03, (z1+z2)/2);
      scene.add(road);

      // Centre line
      const line = new THREE.Mesh(new THREE.PlaneGeometry(len, 0.3, 1, 1), lineMat);
      line.rotation.x = -Math.PI/2;
      line.rotation.z = -angle;
      line.position.set((x1+x2)/2, 0.04, (z1+z2)/2);
      scene.add(line);
    });
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // SKYBOX — procedural night sky with stars
  // ═══════════════════════════════════════════════════════════════════════════
  function buildSky() {
    // Star field
    const starCount = 2000;
    const starGeo = new THREE.BufferGeometry();
    const positions = new Float32Array(starCount * 3);
    const colors    = new Float32Array(starCount * 3);
    const sizes     = new Float32Array(starCount);
    const starCols  = [
      new THREE.Color(1,1,1), new THREE.Color(0.8,0.85,1),
      new THREE.Color(1,0.9,0.7), new THREE.Color(0.7,0.8,1),
    ];
    for(let i=0; i<starCount; i++){
      const theta = Math.random()*Math.PI*2;
      const phi   = Math.random()*Math.PI*0.5;
      const r     = 400 + Math.random()*50;
      positions[i*3]   = r*Math.sin(phi)*Math.cos(theta);
      positions[i*3+1] = r*Math.cos(phi)+10;
      positions[i*3+2] = r*Math.sin(phi)*Math.sin(theta);
      const c = starCols[Math.floor(Math.random()*starCols.length)];
      colors[i*3]=c.r; colors[i*3+1]=c.g; colors[i*3+2]=c.b;
      sizes[i] = Math.random()*2.5+0.5;
    }
    starGeo.setAttribute('position', new THREE.BufferAttribute(positions,3));
    starGeo.setAttribute('color',    new THREE.BufferAttribute(colors,3));
    starGeo.setAttribute('size',     new THREE.BufferAttribute(sizes,1));
    const starMat = new THREE.PointsMaterial({
      size:1.2, vertexColors:true, transparent:true, opacity:0.85,
      sizeAttenuation:true, depthWrite:false,
    });
    scene.add(new THREE.Points(starGeo, starMat));

    // Atmospheric glow dome
    const domeGeo = new THREE.SphereGeometry(380, 32, 16, 0, Math.PI*2, 0, Math.PI*0.5);
    const domeMat = new THREE.MeshBasicMaterial({
      color:0x050A18, side:THREE.BackSide, transparent:true, opacity:0.8,
    });
    scene.add(new THREE.Mesh(domeGeo, domeMat));

    // Aurora bands
    buildAurora();
  }

  function buildAurora() {
    const auroraColors = [[0x002244,0x004488],[0x220044,0x440088],[0x001133,0x002266]];
    auroraColors.forEach(([c1,c2],i) => {
      const geo = new THREE.PlaneGeometry(300, 40, 20, 8);
      const verts = geo.attributes.position;
      for(let j=0; j<verts.count; j++){
        verts.setY(j, verts.getY(j) + Math.sin(verts.getX(j)*0.05 + i*2)*8);
      }
      geo.attributes.position.needsUpdate=true;
      const mat2 = new THREE.MeshBasicMaterial({
        color:c1, transparent:true, opacity:0.04+i*0.01,
        side:THREE.DoubleSide, depthWrite:false,
      });
      const aurora = new THREE.Mesh(geo, mat2);
      aurora.position.set(Math.sin(i*1.5)*80, 80+i*20, Math.cos(i*1.5)*80);
      aurora.rotation.y = i*1.2;
      aurora.userData.aurora = true;
      aurora.userData.offset = i*2;
      scene.add(aurora);
    });
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // BUILD ALL DISTRICTS
  // ═══════════════════════════════════════════════════════════════════════════
  function buildAllDistricts() {
    buildOraclePlaza();
    buildArchiveQuarter();
    buildExchangeFloor();
    buildAgora();
    buildSignalTower();
    buildUnderground();
    buildCouncilChamber();
    buildStreetFurniture();
  }

  // ── Oracle Plaza ─────────────────────────────────────────────────────────────
  function buildOraclePlaza() {
    const pos = DISTRICTS.oracle.position;
    const col = '#8B5CF6';

    // Main oracle tower — tall hexagonal prism
    const hexGeo = new THREE.CylinderGeometry(8, 9, 60, 6);
    const hexMat = new THREE.MeshStandardMaterial({
      color:hex('#1A0A3A'), roughness:0.2, metalness:0.8,
      emissive:hex(col), emissiveIntensity:0.08,
    });
    const oracle = new THREE.Mesh(hexGeo, hexMat);
    oracle.position.set(pos.x, 30, pos.z);
    oracle.castShadow = true;
    scene.add(oracle);
    buildings.push(oracle);

    // Crown
    const crownGeo = new THREE.ConeGeometry(9, 14, 6);
    const crownMesh = new THREE.Mesh(crownGeo, new THREE.MeshStandardMaterial({
      color:hex(col), roughness:0.1, metalness:0.9,
      emissive:hex(col), emissiveIntensity:0.4,
    }));
    crownMesh.position.set(pos.x, 63, pos.z);
    scene.add(crownMesh);

    // Pulsing top light
    const topLight = new THREE.PointLight(hex(col), 6, 50, 2);
    topLight.position.set(pos.x, 72, pos.z);
    topLight.userData.pulse = { speed:1.8, min:4, max:10 };
    scene.add(topLight);

    // Orbiting rings
    for(let i=0; i<3; i++){
      const ringGeo = new THREE.TorusGeometry(12+i*3, 0.25, 8, 40);
      const ringMat = new THREE.MeshBasicMaterial({ color:hex(col), transparent:true, opacity:0.35-i*0.08 });
      const ring = new THREE.Mesh(ringGeo, ringMat);
      ring.position.set(pos.x, 25+i*8, pos.z);
      ring.rotation.x = Math.PI/2 + i*0.4;
      ring.userData.rotate = { speed:0.004-i*0.001, axis:'y' };
      scene.add(ring);
    }

    // Floating data cubes around oracle
    for(let i=0; i<8; i++){
      const angle = (i/8)*Math.PI*2;
      const r = 14;
      const cube = new THREE.Mesh(
        new THREE.BoxGeometry(1.2,1.2,1.2),
        new THREE.MeshStandardMaterial({ color:hex(col), emissive:hex(col), emissiveIntensity:0.6, roughness:0.2 })
      );
      cube.position.set(pos.x + Math.cos(angle)*r, 18+Math.sin(i*1.3)*3, pos.z + Math.sin(angle)*r);
      cube.userData.float = { baseY:cube.position.y, speed:0.6+i*0.15, angle:angle };
      cube.userData.rotate = { speed:0.02, axis:'all' };
      scene.add(cube);
    }

    // Plinth
    const plinthGeo = new THREE.CylinderGeometry(14, 16, 2, 6);
    const plinth = new THREE.Mesh(plinthGeo, mat('#0D0820'));
    plinth.position.set(pos.x, 1, pos.z);
    plinth.receiveShadow = true;
    scene.add(plinth);

    // Concentric plaza rings on ground
    for(let i=1; i<=4; i++){
      const ringFloor = new THREE.Mesh(
        new THREE.RingGeometry(i*16, i*16+0.4, 48),
        new THREE.MeshBasicMaterial({ color:hex(col), transparent:true, opacity:0.08+i*0.01, side:THREE.DoubleSide })
      );
      ringFloor.rotation.x = -Math.PI/2;
      ringFloor.position.set(pos.x, 0.06, pos.z);
      scene.add(ringFloor);
    }

    // Agent marker — ORACLE
    buildAgentMarker('ORACLE', pos.x, pos.z, col, '#FFFACD');
  }

  // ── Archive Quarter ───────────────────────────────────────────────────────────
  function buildArchiveQuarter() {
    const pos = DISTRICTS.archive.position;
    const agents = ['VERA','LORE'];

    // Main library block — wide brutalist
    const lib = buildBlock(pos.x, pos.z, 22, 24, 14, '#141a2e', '#2C3E7A', 0.06);
    lib.forEach(m => scene.add(m));

    // Stacked archive tiers
    [0,4,8].forEach((y, i) => {
      const tier = new THREE.Mesh(
        new THREE.BoxGeometry(20-i*2, 3.5, 12-i*1.5),
        new THREE.MeshStandardMaterial({ color:hex('#0E1428'), roughness:0.85, metalness:0.1 })
      );
      tier.position.set(pos.x+2, y+15.75+i*4, pos.z+2);
      tier.castShadow = true;
      scene.add(tier);
      buildings.push(tier);
    });

    // Glass reading room on top
    const glass = new THREE.Mesh(
      new THREE.BoxGeometry(14, 5, 8),
      matGlass('#4466CC')
    );
    glass.position.set(pos.x, 30, pos.z);
    scene.add(glass);

    // Lore tower — cylindrical archive
    const loreTower = new THREE.Mesh(
      new THREE.CylinderGeometry(4, 5, 34, 12),
      new THREE.MeshStandardMaterial({ color:hex('#0A1230'), roughness:0.7, metalness:0.3, emissive:hex('#90B8FF'), emissiveIntensity:0.04 })
    );
    loreTower.position.set(pos.x-18, 17, pos.z-8);
    loreTower.castShadow = true;
    scene.add(loreTower);
    buildings.push(loreTower);

    // Searchable windows (glowing grids)
    addWindowGrid(pos.x, 12, pos.z, 22, 14, '#2C3E7A', 6, 4);

    // District point light
    scene.add(Object.assign(new THREE.PointLight(0x2233AA, 2.5, 70), { position:new THREE.Vector3(pos.x, 5, pos.z) }));

    buildAgentMarker('VERA', pos.x+5, pos.z+5,  AGENTS.VERA.color,  '#FF5E6C');
    buildAgentMarker('LORE', pos.x-18, pos.z-8, AGENTS.LORE.color,  '#90B8FF');
  }

  // ── Exchange Floor ────────────────────────────────────────────────────────────
  function buildExchangeFloor() {
    const pos = DISTRICTS.exchange.position;

    // Trading floor — wide glass & steel
    const floor = buildBlock(pos.x, pos.z, 28, 18, 12, '#1A1200', '#D97706', 0.07);
    floor.forEach(m => scene.add(m));

    // Two trading towers
    [[-10,0],[10,0]].forEach(([dx,dz], i) => {
      const tower = new THREE.Mesh(
        new THREE.BoxGeometry(10, 38+i*6, 10),
        new THREE.MeshStandardMaterial({
          color:hex('#0D0A00'), roughness:0.25, metalness:0.85,
          emissive:hex('#FFA940'), emissiveIntensity:0.05+i*0.02,
        })
      );
      tower.position.set(pos.x+dx*2, 19+i*3, pos.z+dz);
      tower.castShadow = true;
      scene.add(tower);
      buildings.push(tower);

      // Glass skin
      const skin = new THREE.Mesh(
        new THREE.BoxGeometry(10.2, 38+i*6, 10.2),
        matGlass('#FFA940')
      );
      skin.position.copy(tower.position);
      scene.add(skin);

      // Gold antenna
      const ant = new THREE.Mesh(new THREE.CylinderGeometry(0.15,0.25,12,6), mat('#FFD700',{roughness:0.1,metalness:1}));
      ant.position.set(pos.x+dx*2, 42+i*3+6, pos.z+dz);
      scene.add(ant);
      const antBeacon = new THREE.Mesh(new THREE.SphereGeometry(0.6,8,8), new THREE.MeshBasicMaterial({color:hex('#FFD700')}));
      antBeacon.position.set(pos.x+dx*2, 48+i*3+6, pos.z+dz);
      antBeacon.userData.pulse = { speed:2+i, min:1, max:3 };
      scene.add(antBeacon);
    });

    // Ticker tape — spiral around exchange
    const tickerPoints = [];
    for(let i=0; i<200; i++){
      const t = i/200;
      const angle = t*Math.PI*4;
      const r = 18+Math.sin(t*Math.PI)*4;
      tickerPoints.push(new THREE.Vector3(pos.x+Math.cos(angle)*r, t*16+1, pos.z+Math.sin(angle)*r));
    }
    const tickerCurve = new THREE.CatmullRomCurve3(tickerPoints);
    const tickerGeo   = new THREE.TubeGeometry(tickerCurve,100,0.06,6,false);
    const tickerMesh  = new THREE.Mesh(tickerGeo, new THREE.MeshBasicMaterial({ color:hex('#FFA940'), transparent:true, opacity:0.4 }));
    scene.add(tickerMesh);

    addWindowGrid(pos.x, 10, pos.z, 28, 12, '#D97706', 8, 3);
    scene.add(Object.assign(new THREE.PointLight(0xAA7700, 2.5, 70), { position:new THREE.Vector3(pos.x, 5, pos.z) }));

    buildAgentMarker('DUKE', pos.x-6, pos.z-6, AGENTS.DUKE.color, '#FFA940');
    buildAgentMarker('FLUX', pos.x+8, pos.z+4, AGENTS.FLUX.color, '#FFE040');
    buildAgentMarker('VIGIL',pos.x+2, pos.z-8, AGENTS.VIGIL.color,'#FF8A60');
  }

  // ── The Agora ─────────────────────────────────────────────────────────────────
  function buildAgora() {
    const pos = DISTRICTS.agora.position;

    // Amphitheatre rings
    for(let i=0; i<5; i++){
      const ring = new THREE.Mesh(
        new THREE.TorusGeometry(10+i*4, 1.5, 6, 32),
        new THREE.MeshStandardMaterial({ color:hex('#0A1520'), roughness:0.9 })
      );
      ring.rotation.x = -Math.PI/2;
      ring.position.set(pos.x, i*1.8, pos.z);
      scene.add(ring);
    }

    // Central broadcast pillar
    const pillar = new THREE.Mesh(
      new THREE.CylinderGeometry(1.5, 2, 22, 12),
      new THREE.MeshStandardMaterial({ color:hex('#081830'), roughness:0.3, metalness:0.7, emissive:hex('#0891B2'), emissiveIntensity:0.15 })
    );
    pillar.position.set(pos.x, 11, pos.z);
    scene.add(pillar);

    // News scroll — vertical plane that rotates
    const scrollMat = new THREE.MeshBasicMaterial({ color:hex('#3DD8FF'), transparent:true, opacity:0.6, side:THREE.DoubleSide });
    const scroll = new THREE.Mesh(new THREE.PlaneGeometry(0.1, 14), scrollMat);
    scroll.position.set(pos.x, 14, pos.z);
    scroll.userData.rotate = { speed:0.008, axis:'y' };
    scene.add(scroll);

    // MIRA building — crystalline angular
    const mira = new THREE.Mesh(
      new THREE.OctahedronGeometry(7),
      new THREE.MeshPhysicalMaterial({ color:hex('#061820'), roughness:0.05, metalness:0.2, transmission:0.5, emissive:hex('#3DD8FF'), emissiveIntensity:0.08 })
    );
    mira.position.set(pos.x-12, 7, pos.z-4);
    scene.add(mira);

    // KAEL — flat press office
    const kael = buildBlock(pos.x+10, pos.z+5, 14, 10, 8, '#150818', '#FF70AA', 0.06);
    kael.forEach(m => scene.add(m));
    addWindowGrid(pos.x+10, 8, pos.z+5, 14, 8, '#FF70AA', 4, 3);

    scene.add(Object.assign(new THREE.PointLight(0x006688, 2, 60), { position:new THREE.Vector3(pos.x, 5, pos.z) }));

    buildAgentMarker('MIRA', pos.x-12, pos.z-4, AGENTS.MIRA.color, '#3DD8FF');
    buildAgentMarker('KAEL', pos.x+10, pos.z+5, AGENTS.KAEL.color, '#FF70AA');
  }

  // ── Signal Tower District ─────────────────────────────────────────────────────
  function buildSignalTower() {
    const pos = DISTRICTS.tower.position;

    // SOL — tall broadcast tower lattice
    for(let i=0; i<12; i++){
      const h = 5;
      const y = i*h+h/2;
      const w = 6-i*0.3;
      const geo = new THREE.BoxGeometry(w, 0.4, w);
      const mesh = new THREE.Mesh(geo, mat('#0A1A0A', { roughness:0.8 }));
      mesh.position.set(pos.x, y, pos.z);
      scene.add(mesh);
      // Corner posts
      [[-1,-1],[1,-1],[1,1],[-1,1]].forEach(([sx,sz]) => {
        const post = new THREE.Mesh(new THREE.CylinderGeometry(0.1,0.1,h,4), mat('#0D240D'));
        post.position.set(pos.x+sx*(w/2), y, pos.z+sz*(w/2));
        scene.add(post);
      });
    }
    // Top emitter
    const emitter = new THREE.Mesh(new THREE.SphereGeometry(1.5,8,8), new THREE.MeshBasicMaterial({color:hex('#00E5A0')}));
    emitter.position.set(pos.x, 63, pos.z);
    emitter.userData.pulse = { speed:3, min:0.5, max:3 };
    scene.add(emitter);
    scene.add(Object.assign(new THREE.PointLight(hex('#00E5A0'), 8, 80, 1.5), { position:new THREE.Vector3(pos.x, 64, pos.z) }));

    // NOVA — infrastructure hub (wide low building + cooling towers)
    const nova = buildBlock(pos.x+20, pos.z-8, 18, 14, 10, '#080C18', '#4D9FFF', 0.07);
    nova.forEach(m => scene.add(m));
    [-6,0,6].forEach(dx => {
      const cool = new THREE.Mesh(new THREE.CylinderGeometry(2.5,3,12,10), mat('#060D18'));
      cool.position.set(pos.x+20+dx, 12, pos.z-8);
      scene.add(cool);
      // Steam particle emitter
      cool.userData.steam = { x:pos.x+20+dx, z:pos.z-8, color:'#4D9FFF' };
    });

    // REX — courthouse columns
    const courthouse = buildBlock(pos.x+8, pos.z+14, 16, 12, 10, '#050A10', '#4DDFB0', 0.05);
    courthouse.forEach(m => scene.add(m));
    for(let i=0; i<6; i++){
      const col2 = new THREE.Mesh(new THREE.CylinderGeometry(0.7,0.8,10,8), mat('#070E18'));
      col2.position.set(pos.x+8-6+i*2.4, 10, pos.z+14-8);
      scene.add(col2);
    }

    scene.add(Object.assign(new THREE.PointLight(0x001A4A, 2, 70), { position:new THREE.Vector3(pos.x, 5, pos.z) }));

    buildAgentMarker('SOL',  pos.x,    pos.z,    AGENTS.SOL.color,  '#00E5A0');
    buildAgentMarker('NOVA', pos.x+20, pos.z-8,  AGENTS.NOVA.color, '#4D9FFF');
    buildAgentMarker('REX',  pos.x+8,  pos.z+14, AGENTS.REX.color,  '#4DDFB0');
  }

  // ── Underground ───────────────────────────────────────────────────────────────
  function buildUnderground() {
    const pos = DISTRICTS.underground.position;

    // Entry structure — brutalist sunken block
    const entry = new THREE.Mesh(
      new THREE.BoxGeometry(28, 4, 20),
      new THREE.MeshStandardMaterial({ color:hex('#08040E'), roughness:0.95, metalness:0.05 })
    );
    entry.position.set(pos.x, 2, pos.z);
    scene.add(entry);

    // Neon-trimmed facade
    const neonMat = new THREE.MeshBasicMaterial({ color:hex('#9B6FFF'), transparent:true, opacity:0.7 });
    [[pos.x-14,pos.z-10],[pos.x+14,pos.z-10],[pos.x-14,pos.z+10],[pos.x+14,pos.z+10]].forEach(([x,z]) => {
      const neon = new THREE.Mesh(new THREE.CylinderGeometry(0.12,0.12,4,4), neonMat);
      neon.position.set(x, 4, z);
      scene.add(neon);
    });

    // ECHO — glass pyramid (partially buried)
    const echoPyramid = new THREE.Mesh(
      new THREE.ConeGeometry(9, 12, 4),
      new THREE.MeshPhysicalMaterial({ color:hex('#0D0318'), transmission:0.6, roughness:0.05, emissive:hex('#9B6FFF'), emissiveIntensity:0.15 })
    );
    echoPyramid.rotation.y = Math.PI/4;
    echoPyramid.position.set(pos.x-10, 4, pos.z+6);
    scene.add(echoPyramid);
    buildings.push(echoPyramid);

    // SPECTER — jagged dark tower
    const specGeo = new THREE.CylinderGeometry(3.5, 5, 28, 7);
    const spec = new THREE.Mesh(specGeo, new THREE.MeshStandardMaterial({
      color:hex('#080010'), roughness:0.15, metalness:0.9,
      emissive:hex('#C880FF'), emissiveIntensity:0.12,
    }));
    spec.position.set(pos.x+12, 14, pos.z-4);
    spec.castShadow = true;
    scene.add(spec);
    buildings.push(spec);

    // Purple glow on ground
    scene.add(Object.assign(new THREE.PointLight(0x440066, 3, 60), { position:new THREE.Vector3(pos.x, 3, pos.z) }));

    // Eye-like lens floating above
    const lens = new THREE.Mesh(
      new THREE.SphereGeometry(3, 16, 16),
      new THREE.MeshPhysicalMaterial({ color:hex('#0A0018'), transmission:0.85, roughness:0.02, emissive:hex('#C880FF'), emissiveIntensity:0.3 })
    );
    lens.position.set(pos.x, 14, pos.z);
    lens.userData.float = { baseY:14, speed:0.5, angle:0 };
    lens.userData.rotate = { speed:0.005, axis:'y' };
    scene.add(lens);

    buildAgentMarker('ECHO',    pos.x-10, pos.z+6, AGENTS.ECHO.color,    '#9B6FFF');
    buildAgentMarker('SPECTER', pos.x+12, pos.z-4, AGENTS.SPECTER.color, '#C880FF');
  }

  // ── Council Chamber ───────────────────────────────────────────────────────────
  function buildCouncilChamber() {
    const pos = DISTRICTS.council.position;

    // Round table building — cylinder with dome
    const chamber = new THREE.Mesh(
      new THREE.CylinderGeometry(11, 12, 10, 16),
      new THREE.MeshStandardMaterial({ color:hex('#0E0820'), roughness:0.6, metalness:0.3, emissive:hex('#C4B0FF'), emissiveIntensity:0.05 })
    );
    chamber.position.set(pos.x, 5, pos.z);
    scene.add(chamber);

    const dome = new THREE.Mesh(
      new THREE.SphereGeometry(11, 20, 10, 0, Math.PI*2, 0, Math.PI*0.5),
      new THREE.MeshPhysicalMaterial({ color:hex('#120A2A'), transmission:0.3, roughness:0.1, emissive:hex('#C4B0FF'), emissiveIntensity:0.08 })
    );
    dome.position.set(pos.x, 10, pos.z);
    scene.add(dome);

    // 3 council member beams (AXIOM / DOUBT / LACUNA)
    const councilColors = ['#00E5A0','#FF5E6C','#4D9FFF'];
    councilColors.forEach((c, i) => {
      const angle = (i/3)*Math.PI*2 + Math.PI/6;
      const beam = new THREE.Mesh(
        new THREE.CylinderGeometry(0.2, 0.3, 14, 6),
        new THREE.MeshBasicMaterial({ color:hex(c), transparent:true, opacity:0.6 })
      );
      beam.position.set(pos.x+Math.cos(angle)*7, 9, pos.z+Math.sin(angle)*7);
      beam.userData.pulse = { speed:0.8+i*0.4, min:0.3, max:0.9 };
      scene.add(beam);
    });

    // Columns
    for(let i=0; i<8; i++){
      const angle = (i/8)*Math.PI*2;
      const col2 = new THREE.Mesh(new THREE.CylinderGeometry(0.5,0.6,12,8), mat('#080514'));
      col2.position.set(pos.x+Math.cos(angle)*11, 6, pos.z+Math.sin(angle)*11);
      scene.add(col2);
    }

    scene.add(Object.assign(new THREE.PointLight(0x4A2A88, 2.5, 50), { position:new THREE.Vector3(pos.x, 8, pos.z) }));
  }

  // ─── Generic block builder ────────────────────────────────────────────────────
  function buildBlock(x, z, w, h, d, bodyColor, accentColor, emissiveInt=0.05) {
    const meshes = [];
    const body = new THREE.Mesh(
      new THREE.BoxGeometry(w, h, d),
      new THREE.MeshStandardMaterial({ color:hex(bodyColor), roughness:0.8, metalness:0.15, emissive:hex(accentColor), emissiveIntensity:emissiveInt })
    );
    body.position.set(x, h/2, z);
    body.castShadow = body.receiveShadow = true;
    meshes.push(body);
    buildings.push(body);

    // Accent top band
    const top = new THREE.Mesh(
      new THREE.BoxGeometry(w+0.2, 0.4, d+0.2),
      new THREE.MeshStandardMaterial({ color:hex(accentColor), roughness:0.2, metalness:0.8, emissive:hex(accentColor), emissiveIntensity:0.5 })
    );
    top.position.set(x, h+0.2, z);
    meshes.push(top);
    return meshes;
  }

  // ─── Window grid helper ────────────────────────────────────────────────────────
  function addWindowGrid(x, baseY, z, bw, bh, color, cols=5, rows=4) {
    const winGeo = new THREE.PlaneGeometry(0.7, 0.9);
    const onMat  = new THREE.MeshBasicMaterial({ color:hex(color), transparent:true, opacity:0.7 });
    const offMat = new THREE.MeshBasicMaterial({ color:hex(color), transparent:true, opacity:0.08 });

    for(let row=0; row<rows; row++){
      for(let col=0; col<cols; col++){
        const lit = Math.random() > 0.3;
        const win = new THREE.Mesh(winGeo, lit ? onMat.clone() : offMat.clone());
        win.position.set(
          x - bw/2 + 1.5 + col*(bw-2)/(cols-1||1),
          baseY - bh/2 + 1.5 + row*(bh-2)/(rows-1||1),
          z + bw/2 + 0.05
        );
        if(lit) {
          win.userData.winFlicker = { speed:2+Math.random()*2, phase:Math.random()*Math.PI*2 };
        }
        scene.add(win);
      }
    }
  }

  // ─── Agent marker (glowing beacon on ground) ──────────────────────────────────
  function buildAgentMarker(name, x, z, color, glowColor) {
    const group = new THREE.Group();

    // Pedestal
    const pedGeo = new THREE.CylinderGeometry(1.2, 1.5, 0.4, 12);
    const ped = new THREE.Mesh(pedGeo, mat('#0A1020', { roughness:0.8 }));
    ped.position.set(0, 0.2, 0);
    group.add(ped);

    // Holographic ring
    const ringGeo = new THREE.TorusGeometry(1.8, 0.08, 8, 32);
    const ring = new THREE.Mesh(ringGeo, new THREE.MeshBasicMaterial({ color:hex(color), transparent:true, opacity:0.7 }));
    ring.rotation.x = -Math.PI/2;
    ring.position.y = 0.5;
    ring.userData.rotate = { speed:0.02, axis:'y' };
    group.add(ring);

    // Upward beam
    const beamGeo = new THREE.CylinderGeometry(0.05, 0.4, 8, 6, 1, true);
    const beamMat = new THREE.MeshBasicMaterial({ color:hex(color), transparent:true, opacity:0.18, side:THREE.BackSide });
    const beam = new THREE.Mesh(beamGeo, beamMat);
    beam.position.y = 4.4;
    beam.userData.pulse = { speed:1.5, min:0.1, max:0.3, targetProp:'material.opacity' };
    group.add(beam);

    // Name plate (floating)
    const nameGeo = new THREE.PlaneGeometry(2.8, 0.8);
    const nameMat = new THREE.MeshBasicMaterial({ color:hex(glowColor), transparent:true, opacity:0.9, side:THREE.DoubleSide });
    const namePlate = new THREE.Mesh(nameGeo, nameMat);
    namePlate.position.y = 3;
    namePlate.userData.billboard = true;
    namePlate.userData.float = { baseY:3, speed:0.8, angle:Math.random()*Math.PI*2 };
    group.add(namePlate);

    // Core glow sphere
    const core = new THREE.Mesh(
      new THREE.SphereGeometry(0.5, 16, 16),
      new THREE.MeshBasicMaterial({ color:hex(glowColor) })
    );
    core.position.y = 0.7;
    core.userData.pulse = { speed:2, min:0.8, max:1.2, targetProp:'scale' };
    group.add(core);

    // Point light
    const light = new THREE.PointLight(hex(color), 2.5, 20, 2);
    light.position.y = 1.5;
    light.userData.pulse = { speed:1.5, min:1.5, max:3 };
    group.add(light);

    group.position.set(x, 0, z);
    group.userData.agentName = name;
    group.userData.clickable = true;
    scene.add(group);
    agentMeshes[name] = group;
  }

  // ─── Street furniture ─────────────────────────────────────────────────────────
  function buildStreetFurniture() {
    // Street lights along roads
    const lightPositions = [
      [0,20],[0,-20],[20,0],[-20,0],[30,40],[-30,40],[40,-30],[-40,-30],
      [50,50],[-50,50],[60,-50],[-60,-50],
    ];
    lightPositions.forEach(([x,z]) => {
      const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.12,0.15,7,6), mat('#0A1018'));
      pole.position.set(x, 3.5, z);
      scene.add(pole);

      const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.5,8,8), new THREE.MeshBasicMaterial({ color:0xFFEEAA }));
      lamp.position.set(x, 7.2, z);
      scene.add(lamp);

      const ptLight = new THREE.PointLight(0xFFEEAA, 1.2, 18, 2);
      ptLight.position.set(x, 7, z);
      scene.add(ptLight);
    });

    // Benches / low geometry near oracle
    for(let i=0; i<6; i++){
      const angle = (i/6)*Math.PI*2;
      const r = 22;
      const bench = new THREE.Mesh(new THREE.BoxGeometry(3, 0.4, 0.8), mat('#060C18'));
      bench.position.set(Math.cos(angle)*r, 0.2, Math.sin(angle)*r);
      bench.rotation.y = angle+Math.PI/2;
      scene.add(bench);
    }

    // Holographic billboards
    buildBillboard(30, -20, '#00E5A0', 0.2);
    buildBillboard(-45, 30, '#FF5E6C', 0.15);
    buildBillboard(60, 10, '#4D9FFF', 0.18);
  }

  function buildBillboard(x, z, color, opacity) {
    const stand = new THREE.Mesh(new THREE.CylinderGeometry(0.2,0.2,5,6), mat('#080E1A'));
    stand.position.set(x, 2.5, z);
    scene.add(stand);

    const board = new THREE.Mesh(
      new THREE.PlaneGeometry(5, 2.5),
      new THREE.MeshBasicMaterial({ color:hex(color), transparent:true, opacity, side:THREE.DoubleSide })
    );
    board.position.set(x, 6, z);
    board.userData.rotate = { speed:0.003, axis:'y' };
    board.userData.pulse = { speed:0.7, min:opacity*0.5, max:opacity*1.5, targetProp:'material.opacity' };
    scene.add(board);
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // DATA STREAMS — connecting lines between districts
  // ═══════════════════════════════════════════════════════════════════════════
  function buildDataStreams() {
    const connections = [
      ['oracle','archive',  '#8B5CF6'],
      ['oracle','exchange', '#8B5CF6'],
      ['oracle','agora',    '#8B5CF6'],
      ['oracle','tower',    '#8B5CF6'],
      ['oracle','council',  '#C4B0FF'],
      ['archive','agora',   '#2C3E7A'],
      ['exchange','tower',  '#D97706'],
    ];
    connections.forEach(([a, b, color]) => {
      const pa = DISTRICTS[a].position;
      const pb = DISTRICTS[b].position;
      buildDataStream(pa.x, pa.z, pb.x, pb.z, color);
    });
  }

  function buildDataStream(x1, z1, x2, z2, color) {
    const pts = [];
    const steps = 20;
    for(let i=0; i<=steps; i++){
      const t = i/steps;
      const x = x1+(x2-x1)*t;
      const z = z1+(z2-z1)*t;
      const y = Math.sin(t*Math.PI)*4+0.5;
      pts.push(new THREE.Vector3(x, y, z));
    }
    const curve  = new THREE.CatmullRomCurve3(pts);
    const tubeGeo = new THREE.TubeGeometry(curve, 40, 0.08, 4, false);
    const mesh    = new THREE.Mesh(tubeGeo, new THREE.MeshBasicMaterial({ color:hex(color), transparent:true, opacity:0.35 }));
    mesh.userData.stream = { phase:Math.random()*Math.PI*2, speed:0.6+Math.random()*0.4 };
    scene.add(mesh);

    // Animated data packets along stream
    for(let i=0; i<3; i++){
      const packet = new THREE.Mesh(
        new THREE.SphereGeometry(0.3, 6, 6),
        new THREE.MeshBasicMaterial({ color:hex(color) })
      );
      packet.userData.packet = { curve, t:i/3, speed:0.003+Math.random()*0.002 };
      scene.add(packet);
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // PARTICLE SYSTEM
  // ═══════════════════════════════════════════════════════════════════════════
  function buildParticleSystem() {
    // Ambient floating particles
    const count = 600;
    const geo   = new THREE.BufferGeometry();
    const pos   = new Float32Array(count*3);
    const vel   = new Float32Array(count*3);
    const cols  = new Float32Array(count*3);
    const particleColors = [
      new THREE.Color('#8B5CF6'), new THREE.Color('#00E5A0'),
      new THREE.Color('#4D9FFF'), new THREE.Color('#FF5E6C'),
      new THREE.Color('#FFA940'), new THREE.Color('#C880FF'),
    ];
    for(let i=0; i<count; i++){
      pos[i*3]   = (Math.random()-0.5)*200;
      pos[i*3+1] = Math.random()*30+2;
      pos[i*3+2] = (Math.random()-0.5)*200;
      vel[i*3]   = (Math.random()-0.5)*0.02;
      vel[i*3+1] = Math.random()*0.015+0.005;
      vel[i*3+2] = (Math.random()-0.5)*0.02;
      const c = particleColors[Math.floor(Math.random()*particleColors.length)];
      cols[i*3]=c.r; cols[i*3+1]=c.g; cols[i*3+2]=c.b;
    }
    geo.setAttribute('position', new THREE.BufferAttribute(pos,3));
    geo.setAttribute('color',    new THREE.BufferAttribute(cols,3));
    const pMat = new THREE.PointsMaterial({ size:0.35, vertexColors:true, transparent:true, opacity:0.65, depthWrite:false, sizeAttenuation:true });
    const pts  = new THREE.Points(geo, pMat);
    pts.userData.particles = { vel };
    scene.add(pts);
    particles.push(pts);
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // ANIMATION LOOP
  // ═══════════════════════════════════════════════════════════════════════════
  function start() {
    running = true;
    animate();
  }
  function stop() {
    running = false;
    cancelAnimationFrame(animId);
  }

  function animate() {
    if(!running) return;
    animId = requestAnimationFrame(animate);
    const dt   = clock.getDelta();
    const time = clock.getElapsedTime();

    updateNav(dt);
    updateObjects(time, dt);
    updateParticles(dt);
    updateDistrictLabel();
    updateMinimap();

    renderer.render(scene, camera);
  }

  // ─── Nav update ──────────────────────────────────────────────────────────────
  function updateNav(dt) {
    const speed = nav.speed;
    const fwd   = new THREE.Vector3();
    const right = new THREE.Vector3();
    camera.getWorldDirection(fwd); fwd.y = 0; fwd.normalize();
    right.crossVectors(fwd, camera.up).normalize();

    const move = new THREE.Vector3();
    if(nav.moveF) move.add(fwd);
    if(nav.moveB) move.sub(fwd);
    if(nav.moveL) move.sub(right);
    if(nav.moveR) move.add(right);

    // Touch joystick
    if(nav.joystick.active){
      move.add(fwd.clone().multiplyScalar(-nav.joystick.dz));
      move.add(right.clone().multiplyScalar(nav.joystick.dx));
    }

    if(move.lengthSq() > 0){
      move.normalize().multiplyScalar(speed * dt);
      camera.position.add(move);
    }

    // Clamp y
    camera.position.y = Math.max(1.8, Math.min(40, camera.position.y));
    // World boundary
    camera.position.x = Math.max(-250, Math.min(250, camera.position.x));
    camera.position.z = Math.max(-250, Math.min(250, camera.position.z));

    // Touch look delta
    if(nav.lookDelta.x !== 0 || nav.lookDelta.y !== 0){
      nav.yaw   -= nav.lookDelta.x * 0.002;
      nav.pitch -= nav.lookDelta.y * 0.002;
      nav.pitch = Math.max(-Math.PI/2.5, Math.min(Math.PI/2.5, nav.pitch));
      nav.lookDelta.x = nav.lookDelta.y = 0;
    }

    camera.rotation.y = nav.yaw;
    camera.rotation.x = nav.pitch;
  }

  // ─── Object animations ────────────────────────────────────────────────────────
  function updateObjects(time, dt) {
    scene.traverse(obj => {
      // Rotation
      if(obj.userData.rotate){
        const r = obj.userData.rotate;
        if(r.axis==='y') obj.rotation.y += r.speed;
        else if(r.axis==='x') obj.rotation.x += r.speed;
        else { obj.rotation.x+=r.speed*0.7; obj.rotation.y+=r.speed; obj.rotation.z+=r.speed*0.5; }
      }

      // Float
      if(obj.userData.float){
        const f = obj.userData.float;
        f.angle += 0.01*f.speed;
        obj.position.y = f.baseY + Math.sin(f.angle)*0.8;
      }

      // Pulse (lights & meshes)
      if(obj.userData.pulse){
        const p = obj.userData.pulse;
        const v = p.min+(p.max-p.min)*(0.5+0.5*Math.sin(time*p.speed));
        if(obj.isLight) obj.intensity = v;
        else if(p.targetProp==='material.opacity' && obj.material) obj.material.opacity = v;
        else if(p.targetProp==='scale') obj.scale.setScalar(v);
        else obj.scale.setScalar(v);
      }

      // Aurora wave
      if(obj.userData.aurora){
        // gentle undulate already baked into geometry; just shift opacity
        if(obj.material) obj.material.opacity = 0.04+0.02*Math.sin(time*0.3+obj.userData.offset);
      }

      // Window flicker
      if(obj.userData.winFlicker){
        const wf = obj.userData.winFlicker;
        if(obj.material) obj.material.opacity = 0.5+0.3*Math.sin(time*wf.speed+wf.phase);
      }

      // Data packets
      if(obj.userData.packet){
        const pk = obj.userData.packet;
        pk.t = (pk.t + pk.speed) % 1;
        const pt = pk.curve.getPoint(pk.t);
        obj.position.copy(pt);
      }

      // Billboard — face camera
      if(obj.userData.billboard){
        obj.lookAt(camera.position);
      }
    });
  }

  // ─── Particle update ─────────────────────────────────────────────────────────
  function updateParticles(dt) {
    particles.forEach(pts => {
      const pos = pts.geometry.attributes.position.array;
      const vel = pts.userData.particles.vel;
      for(let i=0; i<pos.length/3; i++){
        pos[i*3]   += vel[i*3];
        pos[i*3+1] += vel[i*3+1];
        pos[i*3+2] += vel[i*3+2];
        // Reset if too high
        if(pos[i*3+1] > 35){ pos[i*3+1] = 1; pos[i*3]=(Math.random()-0.5)*200; pos[i*3+2]=(Math.random()-0.5)*200; }
        if(Math.abs(pos[i*3]) > 100 || Math.abs(pos[i*3+2]) > 100){
          pos[i*3]=(Math.random()-0.5)*200; pos[i*3+2]=(Math.random()-0.5)*200;
        }
      }
      pts.geometry.attributes.position.needsUpdate = true;
    });
  }

  // ─── District label update ────────────────────────────────────────────────────
  function updateDistrictLabel() {
    let nearest = null;
    let nearestDist = Infinity;
    Object.entries(DISTRICTS).forEach(([id, dist]) => {
      const dx = camera.position.x - dist.position.x;
      const dz = camera.position.z - dist.position.z;
      const d  = Math.sqrt(dx*dx+dz*dz);
      if(d < nearestDist){ nearestDist=d; nearest=id; }
    });
    if(nearest !== currentDistrict){
      currentDistrict = nearest;
      const el = document.getElementById('tb-district');
      if(el) el.textContent = DISTRICTS[nearest].name;
      CITY_UI && CITY_UI.onDistrictChange && CITY_UI.onDistrictChange(nearest);
    }

    // Interact prompt — near any agent marker
    let nearAgent = null;
    Object.entries(agentMeshes).forEach(([name, mesh]) => {
      const dx = camera.position.x - mesh.position.x;
      const dz = camera.position.z - mesh.position.z;
      if(Math.sqrt(dx*dx+dz*dz) < 10) nearAgent = name;
    });
    const prompt = document.getElementById('interact-prompt');
    if(prompt){
      if(nearAgent){ prompt.textContent = `[E] or tap to open ${nearAgent}'s district`; prompt.classList.add('visible'); }
      else          { prompt.classList.remove('visible'); }
    }
    hoveredAgent = nearAgent;
  }

  // ─── Minimap ──────────────────────────────────────────────────────────────────
  function updateMinimap() {
    const cv = document.getElementById('minimap-canvas');
    if(!cv) return;
    const ctx = cv.getContext('2d');
    const W = cv.width, H = cv.height;
    const scale = W/200;

    ctx.fillStyle = '#040810';
    ctx.fillRect(0,0,W,H);

    // Grid
    ctx.strokeStyle = 'rgba(255,255,255,0.05)';
    ctx.lineWidth = 0.5;
    for(let i=0;i<W;i+=W/10){ ctx.beginPath();ctx.moveTo(i,0);ctx.lineTo(i,H);ctx.stroke(); }
    for(let i=0;i<H;i+=H/10){ ctx.beginPath();ctx.moveTo(0,i);ctx.lineTo(W,i);ctx.stroke(); }

    // Districts
    Object.entries(DISTRICTS).forEach(([id, d]) => {
      const x = W/2 + d.position.x*scale;
      const z = H/2 + d.position.z*scale;
      ctx.beginPath(); ctx.arc(x,z,5,0,Math.PI*2);
      ctx.fillStyle = d.color+'99'; ctx.fill();
      ctx.strokeStyle = d.color; ctx.lineWidth=1; ctx.stroke();
      ctx.fillStyle = d.color; ctx.font='6px monospace'; ctx.textAlign='center';
      ctx.fillText(id.substring(0,3).toUpperCase(),x,z-7);
    });

    // Player
    const px = W/2+camera.position.x*scale;
    const pz = H/2+camera.position.z*scale;
    ctx.beginPath(); ctx.arc(px,pz,3,0,Math.PI*2);
    ctx.fillStyle='#00E5A0'; ctx.fill();
    // Direction arrow
    const dir = new THREE.Vector3();
    camera.getWorldDirection(dir);
    ctx.strokeStyle='#00E5A0'; ctx.lineWidth=1.5;
    ctx.beginPath(); ctx.moveTo(px,pz);
    ctx.lineTo(px+dir.x*8,pz+dir.z*8);
    ctx.stroke();

    const coords = document.getElementById('mm-coords');
    if(coords) coords.textContent = `${Math.round(camera.position.x)}, ${Math.round(camera.position.z)}`;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // INPUT — KEYBOARD
  // ═══════════════════════════════════════════════════════════════════════════
  function setupKeyboard() {
    const map = { KeyW:'moveF',KeyS:'moveB',KeyA:'moveL',KeyD:'moveR',ArrowUp:'moveF',ArrowDown:'moveB',ArrowLeft:'moveL',ArrowRight:'moveR' };
    document.addEventListener('keydown', e => {
      if(map[e.code]) nav[map[e.code]]=true;
      if(e.code==='KeyE' && hoveredAgent) CITY_UI?.openAgent(hoveredAgent);
      if(e.code==='KeyF') CITY_UI?.toggleFeed();
      if(e.code==='KeyM') CITY_UI?.toggleMap();
      if(e.code==='Escape') CITY_UI?.closeAll();
    });
    document.addEventListener('keyup', e => {
      if(map[e.code]) nav[map[e.code]]=false;
    });
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // INPUT — MOUSE LOOK (pointer lock)
  // ═══════════════════════════════════════════════════════════════════════════
  function setupMouseLook() {
    const canvas = renderer.domElement;
    canvas.addEventListener('click', () => {
      if(!document.pointerLockElement) canvas.requestPointerLock();
    });
    document.addEventListener('pointerlockchange', () => {
      const locked = document.pointerLockElement === canvas;
      document.getElementById('crosshair')?.classList.toggle('locked', locked);
    });
    document.addEventListener('mousemove', e => {
      if(document.pointerLockElement === canvas){
        nav.yaw   -= e.movementX * 0.0018;
        nav.pitch -= e.movementY * 0.0018;
        nav.pitch = Math.max(-Math.PI/2.5, Math.min(Math.PI/2.5, nav.pitch));
      }
    });
    // Raycaster click (outside pointer lock)
    canvas.addEventListener('mousedown', e => {
      if(document.pointerLockElement) return;
      mouse.x = (e.clientX/window.innerWidth)*2-1;
      mouse.y = -(e.clientY/window.innerHeight)*2+1;
      raycaster.setFromCamera(mouse, camera);
      const hits = raycaster.intersectObjects(scene.children, true);
      for(const h of hits){
        let o = h.object;
        while(o){ if(o.userData.agentName){ CITY_UI?.openAgent(o.userData.agentName); break; } o=o.parent; }
        break;
      }
    });
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // INPUT — TOUCH JOYSTICK (left) + LOOK (right)
  // ═══════════════════════════════════════════════════════════════════════════
  function setupTouch() {
    const zone  = document.querySelector('.joystick-zone');
    const knob  = document.querySelector('.joystick-knob');
    const look  = document.getElementById('look-zone');
    if(!zone || !knob || !look) return;

    let joyId=null, lookId=null, joyOrig={x:0,y:0}, lookLast={x:0,y:0};
    const R = 33; // max knob radius

    zone.addEventListener('touchstart', e=>{
      e.preventDefault();
      const t=e.changedTouches[0];
      const rect=zone.getBoundingClientRect();
      joyOrig={x:rect.left+rect.width/2, y:rect.top+rect.height/2};
      joyId=t.identifier;
      nav.joystick.active=true;
    },{passive:false});

    zone.addEventListener('touchmove', e=>{
      e.preventDefault();
      for(const t of e.changedTouches){
        if(t.identifier!==joyId) continue;
        const dx=t.clientX-joyOrig.x, dy=t.clientY-joyOrig.y;
        const dist=Math.min(Math.sqrt(dx*dx+dy*dy),R);
        const angle=Math.atan2(dy,dx);
        const kx=Math.cos(angle)*dist, ky=Math.sin(angle)*dist;
        knob.style.transform=`translate(calc(-50% + ${kx}px), calc(-50% + ${ky}px))`;
        nav.joystick.dx = kx/R;
        nav.joystick.dz = ky/R;
      }
    },{passive:false});

    const joyEnd=e=>{
      for(const t of e.changedTouches){
        if(t.identifier===joyId){ nav.joystick.active=false; nav.joystick.dx=0; nav.joystick.dz=0; knob.style.transform='translate(-50%,-50%)'; joyId=null; }
      }
    };
    zone.addEventListener('touchend',joyEnd); zone.addEventListener('touchcancel',joyEnd);

    // Right side — look
    look.addEventListener('touchstart',e=>{
      e.preventDefault();
      const t=e.changedTouches[0];
      lookId=t.identifier;
      lookLast={x:t.clientX, y:t.clientY};
    },{passive:false});
    look.addEventListener('touchmove',e=>{
      e.preventDefault();
      for(const t of e.changedTouches){
        if(t.identifier!==lookId) continue;
        nav.lookDelta.x += t.clientX-lookLast.x;
        nav.lookDelta.y += t.clientY-lookLast.y;
        lookLast={x:t.clientX, y:t.clientY};
      }
    },{passive:false});
    const lookEnd=e=>{ for(const t of e.changedTouches){ if(t.identifier===lookId) lookId=null; } };
    look.addEventListener('touchend',lookEnd); look.addEventListener('touchcancel',lookEnd);
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // TELEPORT to district
  // ═══════════════════════════════════════════════════════════════════════════
  function teleport(districtId) {
    const d = DISTRICTS[districtId];
    if(!d) return;
    // Smooth tween via step animation
    const start = camera.position.clone();
    const end   = new THREE.Vector3(d.position.x, 4, d.position.z + 20);
    let t = 0;
    const dur = 60;
    const step = () => {
      t++;
      const f = t/dur;
      const ease = f<0.5 ? 2*f*f : -1+(4-2*f)*f; // ease in-out
      camera.position.lerpVectors(start, end, ease);
      if(t<dur) requestAnimationFrame(step);
    };
    step();
  }

  // ─── Resize ───────────────────────────────────────────────────────────────────
  function onResize() {
    camera.aspect = window.innerWidth/window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // BOOT
  // ═══════════════════════════════════════════════════════════════════════════
  function boot(canvas) {
    init(canvas);
    setupKeyboard();
    setupMouseLook();
    setupTouch();
    start();
  }

  let CITY_UI = null;
  function linkUI(ui) { CITY_UI = ui; }

  return { boot, teleport, linkUI, scene, get camera(){ return camera; } };
})();

window.CITY = CITY;
