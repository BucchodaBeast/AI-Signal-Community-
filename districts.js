// districts.js — City geometry, buildings, districts, interiors, particle systems

const CITY = {
  districts: {},
  buildings: [],
  particles: [],
  streetLights: [],
  neonSigns: [],
  roads: [],
  
  build(scene, THREE) {
    this.scene = scene;
    this.THREE = THREE;
    this._buildGround();
    this._buildRoads();
    this._buildArchiveQuarter();
    this._buildExchangeFloor();
    this._buildAgora();
    this._buildSignalTower();
    this._buildUnderground();
    this._buildOraclePlaza();
    this._buildStreetLights();
    this._buildParticles();
    this._buildAmbientCrowd();
    this._buildMetroSystem();
    this._buildSkyline();
    this._buildBridges();
  },

  _buildGround() {
    const T = this.THREE;
    // Main ground plane
    const geo = new T.PlaneGeometry(800, 800, 60, 60);
    const mat = new T.MeshPhongMaterial({ color: 0x06090f, shininess: 15 });
    const ground = new T.Mesh(geo, mat);
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    this.scene.add(ground);

    // Grid overlay
    const gridHelper = new T.GridHelper(600, 80, 0x0d1530, 0x0a1020);
    gridHelper.position.y = 0.05;
    this.scene.add(gridHelper);

    // Reflective puddles
    for (let i = 0; i < 40; i++) {
      const puddleGeo = new T.PlaneGeometry(
        3 + Math.random() * 8, 2 + Math.random() * 5
      );
      const puddleMat = new T.MeshPhongMaterial({
        color: 0x0a1530, shininess: 180,
        transparent: true, opacity: 0.6
      });
      const puddle = new T.Mesh(puddleGeo, puddleMat);
      puddle.rotation.x = -Math.PI / 2;
      puddle.position.set(
        (Math.random() - 0.5) * 280,
        0.06,
        (Math.random() - 0.5) * 280
      );
      this.scene.add(puddle);
    }
  },

  _buildRoads() {
    const T = this.THREE;
    const roadMat = new T.MeshPhongMaterial({ color: 0x080b12, shininess: 8 });
    
    const roads = [
      // Main N-S boulevard
      { w: 18, d: 400, x: 0, z: 0 },
      // Main E-W boulevard
      { w: 400, d: 18, x: 0, z: 0 },
      // District connectors
      { w: 12, d: 200, x: -80, z: -40 },
      { w: 12, d: 200, x: 80, z: -40 },
      { w: 200, d: 12, x: 0, z: -80 },
      { w: 200, d: 12, x: 0, z: 80 },
      // Ring road
      { w: 8, d: 320, x: -140, z: 0 },
      { w: 8, d: 320, x: 140, z: 0 },
      { w: 320, d: 8, x: 0, z: -140 },
      { w: 320, d: 8, x: 0, z: 140 },
    ];

    roads.forEach(r => {
      const geo = new T.PlaneGeometry(r.w, r.d);
      const mesh = new T.Mesh(geo, roadMat);
      mesh.rotation.x = -Math.PI / 2;
      mesh.position.set(r.x, 0.08, r.z);
      this.scene.add(mesh);
      this.roads.push(mesh);

      // Road markings
      const lineGeo = new T.PlaneGeometry(r.w > r.d ? r.d * 0.9 : 0.5, r.w > r.d ? 0.5 : r.d * 0.9);
      const lineMat = new T.MeshBasicMaterial({ color: 0x1a2540, transparent: true, opacity: 0.5 });
      const line = new T.Mesh(lineGeo, lineMat);
      line.rotation.x = -Math.PI / 2;
      line.position.set(r.x, 0.1, r.z);
      this.scene.add(line);
    });
  },

  _buildArchiveQuarter() {
    const T = this.THREE;
    const cx = -120, cz = -80;
    const agents = ['VERA', 'LORE', 'SPECTER'];
    this.districts.archive = { center: new T.Vector3(cx, 0, cz), buildings: [], posts: [] };

    // Brutalist library towers
    const configs = [
      { x: cx-28, z: cz-20, w: 18, h: 55, d: 14, color: 0x1a0808 },
      { x: cx,    z: cz-28, w: 14, h: 72, d: 18, color: 0x120810 },
      { x: cx+28, z: cz-18, w: 16, h: 48, d: 12, color: 0x0d0810 },
      { x: cx-20, z: cz+10, w: 22, h: 35, d: 16, color: 0x150a08 },
      { x: cx+18, z: cz+14, w: 12, h: 60, d: 14, color: 0x100812 },
      { x: cx-8,  z: cz+22, w: 18, h: 28, d: 20, color: 0x120a0a },
      { x: cx+10, z: cz-5,  w: 10, h: 80, d: 10, color: 0x0e0812 },
      { x: cx-32, z: cz+18, w: 14, h: 42, d: 12, color: 0x150810 },
    ];

    configs.forEach((c, i) => {
      const geo = new T.BoxGeometry(c.w, c.h, c.d);
      const mat = new T.MeshPhongMaterial({
        color: c.color, shininess: 5,
        emissive: 0xE05050, emissiveIntensity: 0.02
      });
      const mesh = new T.Mesh(geo, mat);
      mesh.position.set(c.x, c.h / 2, c.z);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.userData = { district: 'archive', buildingIndex: i, agent: agents[i % 3] };
      this.scene.add(mesh);
      this.buildings.push(mesh);
      this.districts.archive.buildings.push(mesh);

      // Windows — emissive grid
      this._addWindows(mesh, c.w, c.h, c.d, 0xE05050, 0.6);
      // Neon signs
      if (i % 2 === 0) this._addNeonSign(c.x, c.h + 1, c.z, agents[i % 3], 0xE05050);
    });

    // Ground-level details: filing cabinet rows (small boxes)
    for (let i = 0; i < 20; i++) {
      const cabGeo = new T.BoxGeometry(2, 3, 1);
      const cabMat = new T.MeshPhongMaterial({ color: 0x1c0f0f });
      const cab = new T.Mesh(cabGeo, cabMat);
      cab.position.set(
        cx + (Math.random() - 0.5) * 55,
        1.5,
        cz + (Math.random() - 0.5) * 55
      );
      this.scene.add(cab);
    }

    // District label light
    const ambLight = new T.PointLight(0xE05050, 1.5, 80);
    ambLight.position.set(cx, 25, cz);
    this.scene.add(ambLight);
    this.districts.archive.light = ambLight;
  },

  _buildExchangeFloor() {
    const T = this.THREE;
    const cx = 120, cz = -80;
    const agents = ['DUKE', 'FLUX', 'VIGIL'];
    this.districts.exchange = { center: new T.Vector3(cx, 0, cz), buildings: [], posts: [] };

    // Glass-and-chrome towers
    const configs = [
      { x: cx+22, z: cz-22, w: 20, h: 90, d: 16, color: 0x060d18 },
      { x: cx-22, z: cz-18, w: 16, h: 70, d: 20, color: 0x080d1a },
      { x: cx+5,  z: cz-30, w: 14, h: 110, d: 14, color: 0x060c16 },
      { x: cx-30, z: cz+5,  w: 18, h: 55, d: 12, color: 0x07101c },
      { x: cx+28, z: cz+10, w: 12, h: 75, d: 16, color: 0x060b14 },
      { x: cx-10, z: cz+20, w: 24, h: 40, d: 18, color: 0x080e1c },
      { x: cx+10, z: cz+28, w: 14, h: 65, d: 12, color: 0x060c18 },
      { x: cx-28, z: cz-28, w: 10, h: 85, d: 10, color: 0x06101e },
    ];

    configs.forEach((c, i) => {
      // Glass facade
      const geo = new T.BoxGeometry(c.w, c.h, c.d);
      const mat = new T.MeshPhongMaterial({
        color: c.color, shininess: 120,
        transparent: true, opacity: 0.88,
        emissive: 0xD97706, emissiveIntensity: 0.025
      });
      const mesh = new T.Mesh(geo, mat);
      mesh.position.set(c.x, c.h / 2, c.z);
      mesh.castShadow = true;
      mesh.userData = { district: 'exchange', buildingIndex: i, agent: agents[i % 3] };
      this.scene.add(mesh);
      this.buildings.push(mesh);
      this.districts.exchange.buildings.push(mesh);
      this._addWindows(mesh, c.w, c.h, c.d, 0xD97706, 0.7);

      // Ticker display on tall buildings
      if (c.h > 70) this._addTickerScreen(c.x, c.h * 0.6, c.z, c.w, 0xD97706);
      if (i % 2 === 0) this._addNeonSign(c.x, c.h + 1, c.z, agents[i % 3], 0xD97706);
    });

    // Helipad on tallest building
    const padGeo = new T.CylinderGeometry(5, 5, 0.3, 16);
    const padMat = new T.MeshPhongMaterial({ color: 0x0a1428, emissive: 0xD97706, emissiveIntensity: 0.3 });
    const pad = new T.Mesh(padGeo, padMat);
    pad.position.set(cx + 5, 111, cz - 30);
    this.scene.add(pad);

    const ambLight = new T.PointLight(0xD97706, 1.8, 90);
    ambLight.position.set(cx, 30, cz);
    this.scene.add(ambLight);
    this.districts.exchange.light = ambLight;
  },

  _buildAgora() {
    const T = this.THREE;
    const cx = 0, cz = 80;
    this.districts.agora = { center: new T.Vector3(cx, 0, cz), buildings: [], posts: [] };

    // Central open square — large plaza surface
    const plazaGeo = new T.PlaneGeometry(80, 80);
    const plazaMat = new T.MeshPhongMaterial({ color: 0x0a0e18, shininess: 40 });
    const plaza = new T.Mesh(plazaGeo, plazaMat);
    plaza.rotation.x = -Math.PI / 2;
    plaza.position.set(cx, 0.15, cz);
    this.scene.add(plaza);

    // Debate stage in centre
    const stageGeo = new T.CylinderGeometry(12, 12, 1.5, 32);
    const stageMat = new T.MeshPhongMaterial({ color: 0x0d1525, shininess: 60, emissive: 0x8B5CF6, emissiveIntensity: 0.08 });
    const stage = new T.Mesh(stageGeo, stageMat);
    stage.position.set(cx, 0.75, cz);
    this.scene.add(stage);
    this.districts.agora.stage = stage;

    // Giant screens around plaza
    const screenPositions = [
      { x: cx-35, z: cz, ry: Math.PI/2 },
      { x: cx+35, z: cz, ry: -Math.PI/2 },
      { x: cx, z: cz-35, ry: 0 },
      { x: cx, z: cz+35, ry: Math.PI },
    ];
    screenPositions.forEach((sp, i) => {
      const screenGeo = new T.PlaneGeometry(20, 14);
      const screenMat = new T.MeshBasicMaterial({ color: 0x050d20 });
      const screen = new T.Mesh(screenGeo, screenMat);
      screen.position.set(sp.x, 10, sp.z);
      screen.rotation.y = sp.ry;
      this.scene.add(screen);

      // Screen glow
      const glowGeo = new T.PlaneGeometry(22, 16);
      const glowMat = new T.MeshBasicMaterial({ color: 0x0891B2, transparent: true, opacity: 0.06 });
      const glow = new T.Mesh(glowGeo, glowMat);
      glow.position.set(sp.x, 10, sp.z + (sp.ry === 0 ? 0.1 : 0));
      glow.rotation.y = sp.ry;
      this.scene.add(glow);
    });

    // Surrounding buildings (mixed height, open feel)
    const configs = [
      { x: cx-50, z: cz-30, w: 14, h: 30, d: 12 },
      { x: cx+50, z: cz-30, w: 12, h: 38, d: 14 },
      { x: cx-48, z: cz+30, w: 16, h: 25, d: 12 },
      { x: cx+48, z: cz+30, w: 14, h: 32, d: 10 },
      { x: cx-30, z: cz-48, w: 10, h: 20, d: 16 },
      { x: cx+30, z: cz-48, w: 12, h: 28, d: 12 },
    ];
    configs.forEach((c, i) => {
      const geo = new T.BoxGeometry(c.w, c.h, c.d);
      const mat = new T.MeshPhongMaterial({ color: 0x080c18, emissive: 0x0891B2, emissiveIntensity: 0.02 });
      const mesh = new T.Mesh(geo, mat);
      mesh.position.set(c.x, c.h/2, c.z);
      mesh.userData = { district: 'agora', buildingIndex: i };
      this.scene.add(mesh);
      this.buildings.push(mesh);
      this.districts.agora.buildings.push(mesh);
      this._addWindows(mesh, c.w, c.h, c.d, 0x0891B2, 0.5);
    });

    // Crowd of small cylinders (pixel people)
    for (let i = 0; i < 60; i++) {
      const pGeo = new T.CylinderGeometry(0.25, 0.25, 1.4, 6);
      const pMat = new T.MeshPhongMaterial({ color: 0x1a2540 });
      const person = new T.Mesh(pGeo, pMat);
      const angle = Math.random() * Math.PI * 2;
      const radius = 5 + Math.random() * 25;
      person.position.set(cx + Math.cos(angle)*radius, 1.45, cz + Math.sin(angle)*radius);
      person.userData = { isPerson: true, angle, radius, cx, cz, speed: 0.001 + Math.random()*0.003 };
      this.scene.add(person);
      this.particles.push({ mesh: person, type: 'person' });
    }

    const ambLight = new T.PointLight(0x0891B2, 1.2, 100);
    ambLight.position.set(cx, 20, cz);
    this.scene.add(ambLight);
    this.districts.agora.light = ambLight;
  },

  _buildSignalTower() {
    const T = this.THREE;
    const cx = 0, cz = 0;
    this.districts.tower = { center: new T.Vector3(cx, 0, cz), buildings: [] };

    // Main brutalist government tower
    const baseGeo = new T.BoxGeometry(28, 4, 28);
    const baseMat = new T.MeshPhongMaterial({ color: 0x080c18 });
    const base = new T.Mesh(baseGeo, baseMat);
    base.position.set(cx, 2, cz);
    this.scene.add(base);

    // Tower body — stepped brutalist form
    const tiers = [
      { w: 24, h: 30, d: 24, y: 17 },
      { w: 20, h: 25, d: 20, y: 44 },
      { w: 16, h: 30, d: 16, y: 71 },
      { w: 10, h: 40, d: 10, y: 106 },
      { w: 4,  h: 20, d: 4,  y: 136 },
    ];
    tiers.forEach((t, i) => {
      const geo = new T.BoxGeometry(t.w, t.h, t.d);
      const mat = new T.MeshPhongMaterial({
        color: 0x060a14, shininess: 10,
        emissive: 0x2563EB, emissiveIntensity: 0.04 + i * 0.01
      });
      const mesh = new T.Mesh(geo, mat);
      mesh.position.set(cx, t.y, cz);
      mesh.castShadow = true;
      mesh.userData = { district: 'tower', isTower: true };
      this.scene.add(mesh);
      this.buildings.push(mesh);
      this.districts.tower.buildings.push(mesh);
      if (t.h > 25) this._addWindows(mesh, t.w, t.h, t.d, 0x2563EB, 0.8);
    });

    // Antenna array on roof
    for (let i = 0; i < 8; i++) {
      const aGeo = new T.CylinderGeometry(0.15, 0.2, 15 + Math.random()*10, 6);
      const aMat = new T.MeshPhongMaterial({ color: 0x0d1530, emissive: 0x2563EB, emissiveIntensity: 0.4 });
      const ant = new T.Mesh(aGeo, aMat);
      const a = (i / 8) * Math.PI * 2;
      ant.position.set(cx + Math.cos(a)*4, 154, cz + Math.sin(a)*4);
      this.scene.add(ant);
      this.districts.tower.buildings.push(ant);

      // Blinking light on top
      const blinkGeo = new T.SphereGeometry(0.3, 6, 6);
      const blinkMat = new T.MeshBasicMaterial({ color: 0xFF0000 });
      const blink = new T.Mesh(blinkGeo, blinkMat);
      blink.position.set(cx + Math.cos(a)*4, 162 + Math.random()*8, cz + Math.sin(a)*4);
      blink.userData = { blink: true, phase: Math.random() * Math.PI * 2 };
      this.scene.add(blink);
      this.particles.push({ mesh: blink, type: 'blink' });
    }

    // Alert beacon ring
    const beaconGeo = new T.TorusGeometry(14, 0.5, 8, 32);
    const beaconMat = new T.MeshBasicMaterial({ color: 0x2563EB, transparent: true, opacity: 0.4 });
    const beacon = new T.Mesh(beaconGeo, beaconMat);
    beacon.position.set(cx, 6, cz);
    beacon.rotation.x = Math.PI / 2;
    this.scene.add(beacon);
    this.districts.tower.beacon = beacon;

    // Permit text projected on tower face (plane with texture)
    this._addPermitProjection(cx, 50, cz - 9);

    // Spot lights up the tower
    const spot = new T.SpotLight(0x2563EB, 3, 180, 0.3, 0.5);
    spot.position.set(cx - 40, 0, cz);
    spot.target.position.set(cx, 80, cz);
    this.scene.add(spot);
    this.scene.add(spot.target);
    this.districts.tower.spot = spot;

    const ambLight = new T.PointLight(0x2563EB, 2, 100);
    ambLight.position.set(cx, 40, cz);
    this.scene.add(ambLight);
    this.districts.tower.light = ambLight;
  },

  _buildUnderground() {
    const T = this.THREE;
    const cx = -120, cz = 80;
    this.districts.underground = { center: new T.Vector3(cx, 0, cz), buildings: [] };

    // Surface: derelict building with subway entrance
    const surfaceGeo = new T.BoxGeometry(30, 12, 25);
    const surfaceMat = new T.MeshPhongMaterial({ color: 0x060810, emissive: 0x7C3AED, emissiveIntensity: 0.03 });
    const surface = new T.Mesh(surfaceGeo, surfaceMat);
    surface.position.set(cx, 6, cz);
    surface.userData = { district: 'underground', isEntrance: true };
    this.scene.add(surface);
    this.buildings.push(surface);
    this.districts.underground.buildings.push(surface);
    this._addWindows(surface, 30, 12, 25, 0x7C3AED, 0.3);

    // Subway entrance arch
    const archGeo = new T.TorusGeometry(4, 0.6, 8, 16, Math.PI);
    const archMat = new T.MeshPhongMaterial({ color: 0x1a0830, emissive: 0x7C3AED, emissiveIntensity: 0.5 });
    const arch = new T.Mesh(archGeo, archMat);
    arch.position.set(cx, 4.6, cz + 13);
    this.scene.add(arch);

    // "ECHO" neon above entrance
    this._addNeonSign(cx, 10, cz + 12.5, 'ECHO', 0x7C3AED);

    // Underground cavern walls (negative space effect)
    const caveGeo = new T.BoxGeometry(60, 20, 60);
    const caveMat = new T.MeshPhongMaterial({ color: 0x04060e, side: T.BackSide });
    const cave = new T.Mesh(caveGeo, caveMat);
    cave.position.set(cx, -10, cz);
    this.scene.add(cave);

    // Purple fog light underground
    const fogLight = new T.PointLight(0x7C3AED, 2, 50);
    fogLight.position.set(cx, -5, cz);
    this.scene.add(fogLight);
    this.districts.underground.light = fogLight;

    // Deleted content "evidence" boards
    for (let i = 0; i < 8; i++) {
      const boardGeo = new T.PlaneGeometry(6, 4);
      const boardMat = new T.MeshPhongMaterial({ color: 0x0a0616, emissive: 0x7C3AED, emissiveIntensity: 0.15 });
      const board = new T.Mesh(boardGeo, boardMat);
      const angle = (i / 8) * Math.PI * 2;
      board.position.set(cx + Math.cos(angle)*18, 6, cz + Math.sin(angle)*18);
      board.rotation.y = -angle;
      this.scene.add(board);
    }
  },

  _buildOraclePlaza() {
    const T = this.THREE;
    const cx = 0, cz = -50;
    this.districts.oracle = { center: new T.Vector3(cx, 0, cz), buildings: [], monoliths: [] };

    // Moat ring
    const moatGeo = new T.TorusGeometry(28, 4, 8, 48);
    const moatMat = new T.MeshPhongMaterial({ color: 0x04080e, shininess: 200, transparent: true, opacity: 0.9 });
    const moat = new T.Mesh(moatGeo, moatMat);
    moat.rotation.x = Math.PI / 2;
    moat.position.set(cx, 0.4, cz);
    this.scene.add(moat);

    // Water glow in moat
    const waterGeo = new T.TorusGeometry(28, 3.5, 8, 48);
    const waterMat = new T.MeshBasicMaterial({ color: 0x8B5CF6, transparent: true, opacity: 0.12 });
    const water = new T.Mesh(waterGeo, waterMat);
    water.rotation.x = Math.PI / 2;
    water.position.set(cx, 0.3, cz);
    this.scene.add(water);

    // Central glass pyramid
    const pyrGeo = new T.ConeGeometry(18, 32, 4);
    const pyrMat = new T.MeshPhongMaterial({
      color: 0x060a18, shininess: 200,
      transparent: true, opacity: 0.75,
      emissive: 0x8B5CF6, emissiveIntensity: 0.08
    });
    const pyramid = new T.Mesh(pyrGeo, pyrMat);
    pyramid.position.set(cx, 16, cz);
    pyramid.rotation.y = Math.PI / 4;
    this.scene.add(pyramid);
    this.districts.oracle.pyramid = pyramid;
    this.buildings.push(pyramid);

    // Pyramid base
    const pyBaseGeo = new T.CylinderGeometry(18, 20, 2, 4);
    const pyBaseMat = new T.MeshPhongMaterial({ color: 0x080c1a, shininess: 60 });
    const pyBase = new T.Mesh(pyBaseGeo, pyBaseMat);
    pyBase.position.set(cx, 1, cz);
    pyBase.rotation.y = Math.PI / 4;
    this.scene.add(pyBase);

    // Spiral staircase down to Council chamber
    for (let i = 0; i < 20; i++) {
      const stepGeo = new T.BoxGeometry(4, 0.3, 1.5);
      const stepMat = new T.MeshPhongMaterial({ color: 0x0a0e20 });
      const step = new T.Mesh(stepGeo, stepMat);
      const angle = (i / 20) * Math.PI * 2 * 2;
      step.position.set(cx + Math.cos(angle)*6, -i*1.2, cz + Math.sin(angle)*6);
      step.rotation.y = angle;
      this.scene.add(step);
    }

    // Oracle brief monoliths — 3 standing slabs
    for (let i = 0; i < 3; i++) {
      const angle = (i / 3) * Math.PI * 2;
      const mGeo = new T.BoxGeometry(5, 14, 1);
      const mMat = new T.MeshPhongMaterial({
        color: 0x060a18, shininess: 80,
        emissive: 0x8B5CF6, emissiveIntensity: 0.18
      });
      const mono = new T.Mesh(mGeo, mMat);
      mono.position.set(cx + Math.cos(angle)*12, 7, cz + Math.sin(angle)*12);
      mono.rotation.y = -angle;
      mono.userData = { isMonolith: true, briefIndex: i };
      this.scene.add(mono);
      this.districts.oracle.monoliths.push(mono);
      this.buildings.push(mono);

      // Monolith glow
      const gLight = new T.PointLight(0x8B5CF6, 1.2, 15);
      gLight.position.copy(mono.position);
      gLight.position.y = 10;
      this.scene.add(gLight);
    }

    // Oracle ambient
    const oracleLight = new T.PointLight(0x8B5CF6, 3, 80);
    oracleLight.position.set(cx, 30, cz);
    this.scene.add(oracleLight);
    this.districts.oracle.light = oracleLight;

    // Outer ring of smaller oracle lights
    for (let i = 0; i < 8; i++) {
      const a = (i / 8) * Math.PI * 2;
      const rLight = new T.PointLight(0x8B5CF6, 0.4, 20);
      rLight.position.set(cx + Math.cos(a)*22, 1, cz + Math.sin(a)*22);
      this.scene.add(rLight);
    }
  },

  _buildStreetLights() {
    const T = this.THREE;
    const positions = [];
    // Along main roads
    for (let i = -6; i <= 6; i++) {
      positions.push({ x: 10, z: i * 30 });
      positions.push({ x: -10, z: i * 30 });
      positions.push({ x: i * 30, z: 10 });
      positions.push({ x: i * 30, z: -10 });
    }
    positions.forEach(p => {
      const poleGeo = new T.CylinderGeometry(0.15, 0.2, 10, 6);
      const poleMat = new T.MeshPhongMaterial({ color: 0x0d1530 });
      const pole = new T.Mesh(poleGeo, poleMat);
      pole.position.set(p.x, 5, p.z);
      this.scene.add(pole);

      const headGeo = new T.SphereGeometry(0.5, 8, 8);
      const headMat = new T.MeshBasicMaterial({ color: 0xCCDDFF });
      const head = new T.Mesh(headGeo, headMat);
      head.position.set(p.x, 10.5, p.z);
      this.scene.add(head);

      const light = new T.PointLight(0x8899CC, 0.5, 25);
      light.position.set(p.x, 10, p.z);
      this.scene.add(light);
      this.streetLights.push(light);
    });
  },

  _buildParticles() {
    const T = this.THREE;

    // Rain particles
    const rainGeo = new T.BufferGeometry();
    const rainCount = 3000;
    const positions = new Float32Array(rainCount * 3);
    for (let i = 0; i < rainCount; i++) {
      positions[i*3]   = (Math.random()-0.5)*400;
      positions[i*3+1] = Math.random()*200;
      positions[i*3+2] = (Math.random()-0.5)*400;
    }
    rainGeo.setAttribute('position', new T.BufferAttribute(positions, 3));
    const rainMat = new T.PointsMaterial({ color: 0x2244AA, size: 0.3, transparent: true, opacity: 0.4 });
    this.rainParticles = new T.Points(rainGeo, rainMat);
    this.scene.add(this.rainParticles);

    // Electrical arc particles around Signal Tower
    const arcGeo = new T.BufferGeometry();
    const arcCount = 200;
    const arcPositions = new Float32Array(arcCount * 3);
    for (let i = 0; i < arcCount; i++) {
      const a = Math.random() * Math.PI * 2;
      const r = 6 + Math.random() * 8;
      const h = 130 + Math.random() * 30;
      arcPositions[i*3]   = Math.cos(a) * r;
      arcPositions[i*3+1] = h;
      arcPositions[i*3+2] = Math.sin(a) * r;
    }
    arcGeo.setAttribute('position', new T.BufferAttribute(arcPositions, 3));
    const arcMat = new T.PointsMaterial({ color: 0x2563EB, size: 0.5, transparent: true, opacity: 0.7 });
    this.arcParticles = new T.Points(arcGeo, arcMat);
    this.scene.add(this.arcParticles);

    // Oracle Plaza floating particles
    const oGeo = new T.BufferGeometry();
    const oCount = 400;
    const oPos = new Float32Array(oCount * 3);
    for (let i = 0; i < oCount; i++) {
      const a = Math.random() * Math.PI * 2;
      const r = Math.random() * 20;
      oPos[i*3]   = Math.cos(a)*r;
      oPos[i*3+1] = Math.random()*35;
      oPos[i*3+2] = -50 + Math.sin(a)*r;
    }
    oGeo.setAttribute('position', new T.BufferAttribute(oPos, 3));
    const oMat = new T.PointsMaterial({ color: 0x8B5CF6, size: 0.4, transparent: true, opacity: 0.6 });
    this.oracleParticles = new T.Points(oGeo, oMat);
    this.scene.add(this.oracleParticles);

    // City atmosphere haze
    const hazeGeo = new T.BufferGeometry();
    const hCount = 1500;
    const hPos = new Float32Array(hCount * 3);
    for (let i = 0; i < hCount; i++) {
      hPos[i*3]   = (Math.random()-0.5)*500;
      hPos[i*3+1] = 20 + Math.random()*80;
      hPos[i*3+2] = (Math.random()-0.5)*500;
    }
    hazeGeo.setAttribute('position', new T.BufferAttribute(hPos, 3));
    const hazeMat = new T.PointsMaterial({ color: 0x0a1428, size: 2, transparent: true, opacity: 0.15 });
    this.hazeParticles = new T.Points(hazeGeo, hazeMat);
    this.scene.add(this.hazeParticles);
  },

  _buildAmbientCrowd() {
    // Additional ambient walkers across the whole city
    const T = this.THREE;
    for (let i = 0; i < 30; i++) {
      const pGeo = new T.CylinderGeometry(0.2, 0.2, 1.4, 6);
      const col = [0x1a2540, 0x0d1a30, 0x1a1030, 0x0a1820][Math.floor(Math.random()*4)];
      const pMat = new T.MeshPhongMaterial({ color: col });
      const person = new T.Mesh(pGeo, pMat);
      person.position.set(
        (Math.random()-0.5)*200,
        0.7,
        (Math.random()-0.5)*200
      );
      person.userData = {
        isPerson: true,
        walkAngle: Math.random() * Math.PI * 2,
        walkSpeed: 0.005 + Math.random()*0.01,
        walkRadius: 0,
        ambient: true,
        cx: person.position.x,
        cz: person.position.z
      };
      this.scene.add(person);
      this.particles.push({ mesh: person, type: 'ambientPerson' });
    }
  },

  _buildMetroSystem() {
    const T = this.THREE;
    // Elevated metro track
    const trackPoints = [
      new T.Vector3(-120, 12, -80),
      new T.Vector3(-60, 12, -40),
      new T.Vector3(0, 12, -20),
      new T.Vector3(60, 12, -40),
      new T.Vector3(120, 12, -80),
      new T.Vector3(80, 12, -20),
      new T.Vector3(0, 12, 30),
      new T.Vector3(-80, 12, 50),
      new T.Vector3(-120, 12, 80),
    ];
    const curve = new T.CatmullRomCurve3(trackPoints, true);
    const trackGeo = new T.TubeGeometry(curve, 120, 0.3, 6, true);
    const trackMat = new T.MeshPhongMaterial({ color: 0x0d1530, emissive: 0x1A6CF0, emissiveIntensity: 0.15 });
    const track = new T.Mesh(trackGeo, trackMat);
    this.scene.add(track);

    // Metro train car
    const trainGeo = new T.BoxGeometry(12, 4, 5);
    const trainMat = new T.MeshPhongMaterial({
      color: 0x060c1a, shininess: 80,
      emissive: 0x1A6CF0, emissiveIntensity: 0.2
    });
    const train = new T.Mesh(trainGeo, trainMat);
    this.scene.add(train);
    this.metroTrain = { mesh: train, curve, t: 0, speed: 0.0008 };

    // Train windows
    for (let w = -2; w <= 2; w++) {
      const wGeo = new T.PlaneGeometry(1.5, 1.5);
      const wMat = new T.MeshBasicMaterial({ color: 0x1A6CF0, transparent: true, opacity: 0.6 });
      const win = new T.Mesh(wGeo, wMat);
      win.position.set(w*2.5, 0.5, 2.55);
      train.add(win);
    }

    // Support pillars for elevated track
    [[-80,-60],[-30,-30],[0,0],[60,-40],[80,-20],[0,30],[-80,50]].forEach(([x,z]) => {
      const pillarGeo = new T.CylinderGeometry(0.6, 0.8, 12, 8);
      const pillarMat = new T.MeshPhongMaterial({ color: 0x0a0e1a });
      const pillar = new T.Mesh(pillarGeo, pillarMat);
      pillar.position.set(x, 6, z);
      this.scene.add(pillar);
    });
  },

  _buildSkyline() {
    const T = this.THREE;
    // Background skyline buildings (far distance, fog silhouettes)
    for (let i = 0; i < 60; i++) {
      const angle = (i / 60) * Math.PI * 2;
      const radius = 200 + Math.random() * 80;
      const h = 20 + Math.random() * 120;
      const w = 6 + Math.random() * 16;
      const geo = new T.BoxGeometry(w, h, w * 0.7);
      const mat = new T.MeshPhongMaterial({ color: 0x040608, transparent: true, opacity: 0.7 });
      const mesh = new T.Mesh(geo, mat);
      mesh.position.set(Math.cos(angle)*radius, h/2, Math.sin(angle)*radius);
      this.scene.add(mesh);
      // Sparse window lights on skyline
      if (Math.random() > 0.5) this._addWindows(mesh, w, h, w*0.7, 0x3366AA, 0.2);
    }
  },

  _buildBridges() {
    const T = this.THREE;
    // Walkway bridges between districts
    const bridges = [
      { x1:-80, z1:-40, x2:-20, z2:-20, y: 8 },
      { x1: 80, z1:-40, x2: 20, z2:-20, y: 8 },
      { x1:-20, z1: 20, x2:-80, z2: 50, y: 8 },
    ];
    bridges.forEach(b => {
      const dx = b.x2-b.x1, dz = b.z2-b.z1;
      const len = Math.sqrt(dx*dx+dz*dz);
      const geo = new T.BoxGeometry(2.5, 0.5, len);
      const mat = new T.MeshPhongMaterial({ color: 0x0a0e1a, emissive: 0x1A6CF0, emissiveIntensity: 0.08 });
      const mesh = new T.Mesh(geo, mat);
      mesh.position.set((b.x1+b.x2)/2, b.y, (b.z1+b.z2)/2);
      mesh.rotation.y = Math.atan2(dx, dz);
      this.scene.add(mesh);
    });
  },

  _addWindows(parentMesh, w, h, d, color, density) {
    const T = this.THREE;
    const cols = Math.floor(w / 3);
    const rows = Math.floor(h / 4);
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        if (Math.random() > density) continue;
        const wGeo = new T.PlaneGeometry(0.9, 1.1);
        const wMat = new T.MeshBasicMaterial({ color, transparent: true, opacity: 0.4 + Math.random()*0.4 });
        const win = new T.Mesh(wGeo, wMat);
        win.position.set(
          -w/2 + (c+0.5) * (w/cols) + (Math.random()-0.5)*0.3,
          -h/2 + (r+0.5) * (h/rows) + (Math.random()-0.5)*0.3,
          d/2 + 0.05
        );
        win.userData = { isWindow: true, phase: Math.random()*Math.PI*2, flickerRate: 0.001+Math.random()*0.003 };
        parentMesh.add(win);
      }
    }
  },

  _addNeonSign(x, y, z, text, color) {
    const T = this.THREE;
    const canvas = document.createElement('canvas');
    canvas.width = 256; canvas.height = 64;
    const ctx = canvas.getContext('2d');
    const hexColor = '#' + color.toString(16).padStart(6, '0');
    ctx.shadowColor = hexColor;
    ctx.shadowBlur = 20;
    ctx.fillStyle = hexColor;
    ctx.font = 'bold 32px DM Mono, monospace';
    ctx.textAlign = 'center';
    ctx.fillText(text, 128, 44);
    const tex = new T.CanvasTexture(canvas);
    const mat = new T.SpriteMaterial({ map: tex, transparent: true });
    const sprite = new T.Sprite(mat);
    sprite.scale.set(16, 4, 1);
    sprite.position.set(x, y, z);
    this.scene.add(sprite);
    this.neonSigns.push({ sprite, color, phase: Math.random()*Math.PI*2 });
  },

  _addTickerScreen(x, y, z, width, color) {
    const T = this.THREE;
    const canvas = document.createElement('canvas');
    canvas.width = 512; canvas.height = 128;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#020408';
    ctx.fillRect(0, 0, 512, 128);
    ctx.fillStyle = '#' + color.toString(16).padStart(6, '0');
    ctx.font = '20px DM Mono, monospace';
    ctx.fillText('▲ SIGNAL ALERT ▲  DUKE: RF hiring +340%  FLUX: $2.1B USDT moved', 10, 40);
    ctx.fillStyle = 'rgba(255,255,255,0.4)';
    ctx.font = '16px DM Mono, monospace';
    ctx.fillText('IRON ORE -18.3% YoY  ·  ARCHIVES: 3 PRE-PRINTS  ·  FCC LICENSE FILED', 10, 80);
    const tex = new T.CanvasTexture(canvas);
    const geo = new T.PlaneGeometry(width, 3);
    const mat = new T.MeshBasicMaterial({ map: tex, transparent: true, opacity: 0.85 });
    const mesh = new T.Mesh(geo, mat);
    mesh.position.set(x, y, z + 0.3);
    this.scene.add(mesh);
  },

  _addPermitProjection(x, y, z) {
    const T = this.THREE;
    const canvas = document.createElement('canvas');
    canvas.width = 256; canvas.height = 512;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = 'rgba(2,4,12,0.0)';
    ctx.fillRect(0, 0, 256, 512);
    ctx.fillStyle = 'rgba(37,99,235,0.6)';
    ctx.font = '11px DM Mono, monospace';
    const lines = [
      'FCC PERMIT #2024-RF-00341', 'STATUS: ACTIVE', '',
      'FAA NOTAM: MTN-2024-0892','COORD: 46.87N 112.44W','',
      'FEDERAL REGISTER: VOL 89','PAGE 41203','COMMENT: 21 DAYS','',
      'APPLICANT: [REDACTED]','DELAWARE LLC','FILED: 2024-04-02','',
      'SPECTRUM: 3.5-3.7 GHz','POWER: 47 dBm','RANGE: 85 km','',
      '>>> CONVERGENCE DETECTED <<<','CONFIDENCE: HIGH'
    ];
    lines.forEach((l, i) => { ctx.fillText(l, 10, 20 + i * 26); });
    const tex = new T.CanvasTexture(canvas);
    const geo = new T.PlaneGeometry(9, 18);
    const mat = new T.MeshBasicMaterial({ map: tex, transparent: true, opacity: 0.7 });
    const mesh = new T.Mesh(geo, mat);
    mesh.position.set(x, y, z);
    this.scene.add(mesh);
  },

  // ── ANIMATE EVERYTHING ──────────────────────────────
  update(delta, time) {
    // Rain
    if (this.rainParticles) {
      const pos = this.rainParticles.geometry.attributes.position.array;
      for (let i = 1; i < pos.length; i += 3) {
        pos[i] -= 0.8;
        if (pos[i] < 0) pos[i] = 200;
      }
      this.rainParticles.geometry.attributes.position.needsUpdate = true;
    }

    // Arc particles around tower
    if (this.arcParticles) {
      const pos = this.arcParticles.geometry.attributes.position.array;
      for (let i = 0; i < pos.length; i += 3) {
        const a = Math.atan2(pos[i+2], pos[i]) + 0.01;
        const r = Math.sqrt(pos[i]*pos[i]+pos[i+2]*pos[i+2]);
        pos[i]   = Math.cos(a)*r + (Math.random()-0.5)*0.3;
        pos[i+2] = Math.sin(a)*r + (Math.random()-0.5)*0.3;
        pos[i+1] += (Math.random()-0.5)*0.2;
        if (pos[i+1] > 165) pos[i+1] = 128;
      }
      this.arcParticles.geometry.attributes.position.needsUpdate = true;
    }

    // Oracle particles
    if (this.oracleParticles) {
      const pos = this.oracleParticles.geometry.attributes.position.array;
      for (let i = 0; i < pos.length; i += 3) {
        pos[i+1] += 0.02;
        if (pos[i+1] > 35) pos[i+1] = 0;
        pos[i]   += Math.sin(time * 0.001 + i) * 0.01;
        pos[i+2] += Math.cos(time * 0.001 + i) * 0.01;
      }
      this.oracleParticles.geometry.attributes.position.needsUpdate = true;
    }

    // Blink lights
    this.particles.forEach(p => {
      if (p.type === 'blink') {
        const on = Math.sin(time * 0.002 + p.mesh.userData.phase) > 0;
        p.mesh.material.color.setHex(on ? 0xFF2222 : 0x330000);
      }
      if (p.type === 'person') {
        const d = p.mesh.userData;
        d.angle += d.speed;
        p.mesh.position.x = d.cx + Math.cos(d.angle) * d.radius;
        p.mesh.position.z = d.cz + Math.sin(d.angle) * d.radius;
        p.mesh.position.y = 0.7 + Math.abs(Math.sin(time * 0.006)) * 0.08;
        p.mesh.rotation.y = d.angle + Math.PI / 2;
      }
      if (p.type === 'ambientPerson') {
        const d = p.mesh.userData;
        d.walkAngle += d.walkSpeed;
        p.mesh.position.x += Math.cos(d.walkAngle) * 0.05;
        p.mesh.position.z += Math.sin(d.walkAngle) * 0.05;
        // Bounce back toward home
        const dx = d.cx - p.mesh.position.x;
        const dz = d.cz - p.mesh.position.z;
        if (Math.sqrt(dx*dx+dz*dz) > 60) {
          d.walkAngle += Math.PI + (Math.random()-0.5);
        }
        p.mesh.position.y = 0.7 + Math.abs(Math.sin(time * 0.008)) * 0.08;
      }
    });

    // Neon signs flicker
    this.neonSigns.forEach(n => {
      const flicker = 0.7 + 0.3 * Math.sin(time * 0.004 + n.phase);
      n.sprite.material.opacity = flicker;
    });

    // Metro train
    if (this.metroTrain) {
      this.metroTrain.t = (this.metroTrain.t + this.metroTrain.speed) % 1;
      const pos = this.metroTrain.curve.getPoint(this.metroTrain.t);
      const tan = this.metroTrain.curve.getTangent(this.metroTrain.t);
      this.metroTrain.mesh.position.copy(pos);
      this.metroTrain.mesh.lookAt(pos.clone().add(tan));
    }

    // Pyramid slow rotation
    if (this.districts.oracle?.pyramid) {
      this.districts.oracle.pyramid.rotation.y += 0.001;
    }

    // Beacon pulse
    if (this.districts.tower?.beacon) {
      this.districts.tower.beacon.material.opacity = 0.2 + 0.2 * Math.sin(time * 0.003);
    }

    // Window flicker
    this.buildings.forEach(b => {
      b.children.forEach(child => {
        if (child.userData.isWindow) {
          const flicker = Math.sin(time * child.userData.flickerRate + child.userData.phase);
          child.material.opacity = Math.max(0.1, 0.3 + flicker * 0.25);
        }
      });
    });
  },

  // Alert mode — tower flash
  setAlertMode(on) {
    const towerLight = this.districts.tower?.light;
    if (towerLight) towerLight.color.setHex(on ? 0xE03E3E : 0x2563EB);
    if (this.districts.tower?.spot) this.districts.tower.spot.color.setHex(on ? 0xE03E3E : 0x2563EB);
    if (this.rainParticles) this.rainParticles.material.color.setHex(on ? 0x441111 : 0x2244AA);
  },

  // Convergence lighting
  setConvergence(pct) {
    // Golden hour at high convergence
    const oLight = this.districts.oracle?.light;
    if (oLight) oLight.intensity = 1.5 + (pct / 100) * 3;
    if (this.oracleParticles) this.oracleParticles.material.opacity = 0.3 + (pct / 100) * 0.6;
  },

  getNearestDistrict(position) {
    let nearest = null, nearestDist = Infinity;
    Object.entries(this.districts).forEach(([name, d]) => {
      const dist = position.distanceTo(d.center);
      if (dist < nearestDist) { nearestDist = dist; nearest = name; }
    });
    return { name: nearest, dist: nearestDist };
  },
};
