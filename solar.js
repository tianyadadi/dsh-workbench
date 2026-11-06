/**
 * DSH 记忆太阳系 —— three.js 太阳系视图
 * ============================================================================
 * 太阳 = 全部记忆的核心（发光球体 + 日冕光晕）
 * 8 颗行星 = 按记忆类型分组映射，真实公转周期比例 + 各自自转 + 轴倾角
 * 纹理全部用 canvas 程序生成（不需要外部图片），土星带环
 * ============================================================================
 */
(function () {
  'use strict'

  /* 行星纹理：条纹型（木星/土星）或斑块型（类地行星） */
  function planetTexture(opt) {
    var W = 512, H = 256
    var cv = document.createElement('canvas')
    cv.width = W; cv.height = H
    var ctx = cv.getContext('2d')
    ctx.fillStyle = opt.base
    ctx.fillRect(0, 0, W, H)

    if (opt.bands) {
      for (var b = 0; b < opt.bands; b++) {
        var y = (b / opt.bands) * H + (Math.random() - 0.5) * 6
        var h = H / opt.bands * (0.5 + Math.random() * 0.8)
        ctx.fillStyle = opt.accent
        ctx.globalAlpha = 0.10 + Math.random() * 0.22
        ctx.fillRect(0, y, W, h)
      }
    } else {
      for (var i = 0; i < 90; i++) {
        var x = Math.random() * W, yy = Math.random() * H
        var r = 3 + Math.random() * 22
        ctx.fillStyle = opt.accent
        ctx.globalAlpha = 0.06 + Math.random() * 0.28
        ctx.beginPath()
        ctx.ellipse(x, yy, r, r * (0.4 + Math.random() * 0.9), Math.random() * 3, 0, 6.283)
        ctx.fill()
      }
    }
    ctx.globalAlpha = 1
    for (var n = 0; n < 2600; n++) {
      ctx.fillStyle = Math.random() > 0.5 ? '#ffffff' : '#000000'
      ctx.globalAlpha = 0.025 + Math.random() * 0.05
      ctx.fillRect(Math.random() * W, Math.random() * H, 1.5, 1.5)
    }
    ctx.globalAlpha = 1
    var tex = new THREE.CanvasTexture(cv)
    tex.colorSpace = THREE.SRGBColorSpace
    return tex
  }

  /* 太阳纹理：亮核 + 表面颗粒 */
  function sunTexture() {
    var S = 512
    var cv = document.createElement('canvas')
    cv.width = cv.height = S
    var ctx = cv.getContext('2d')
    var g = ctx.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S / 2)
    g.addColorStop(0, '#fffdf0')
    g.addColorStop(0.45, '#ffe27a')
    g.addColorStop(0.8, '#ff9a3c')
    g.addColorStop(1, '#ff6a00')
    ctx.fillStyle = g
    ctx.fillRect(0, 0, S, S)
    for (var i = 0; i < 900; i++) {
      ctx.fillStyle = Math.random() > 0.5 ? '#fff3c0' : '#ff7b1a'
      ctx.globalAlpha = 0.05 + Math.random() * 0.18
      ctx.beginPath()
      ctx.arc(Math.random() * S, Math.random() * S, 2 + Math.random() * 14, 0, 6.283)
      ctx.fill()
    }
    ctx.globalAlpha = 1
    var tex = new THREE.CanvasTexture(cv)
    tex.colorSpace = THREE.SRGBColorSpace
    return tex
  }

  function glowTexture() {
    var S = 256
    var cv = document.createElement('canvas')
    cv.width = cv.height = S
    var ctx = cv.getContext('2d')
    var g = ctx.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S / 2)
    g.addColorStop(0, 'rgba(255,240,180,0.95)')
    g.addColorStop(0.3, 'rgba(255,150,40,0.35)')
    g.addColorStop(1, 'rgba(255,100,0,0)')
    ctx.fillStyle = g
    ctx.fillRect(0, 0, S, S)
    return new THREE.CanvasTexture(cv)
  }

  /* 真实数据（NASA Planetary Fact Sheet）
     rEarth = 赤道半径（地球=1）    day = 自转周期（地球日，负值=逆行）
     year   = 公转周期（地球年）    tilt = 轴倾角（度）                      */
  var PLANETS = [
    { name: '水星', au: 0.387, e: 0.2056, rEarth: 0.383, day: 58.646, year: 0.2408, tilt: 0.034,
      base: '#9c8e83', accent: '#5c5148' },
    { name: '金星', au: 0.723, e: 0.0068, rEarth: 0.949, day: -243.02, year: 0.6152, tilt: 177.4,
      base: '#d9b382', accent: '#a67c4e' },
    { name: '地球', au: 1.000, e: 0.0167, rEarth: 1.000, day: 0.9973, year: 1.0000, tilt: 23.44,
      base: '#1c5fb8', accent: '#3f9e5a' },
    { name: '火星', au: 1.524, e: 0.0934, rEarth: 0.532, day: 1.0259, year: 1.8808, tilt: 25.19,
      base: '#b5471a', accent: '#7a2c10' },
    { name: '木星', au: 5.203, e: 0.0484, rEarth: 10.97, day: 0.4135, year: 11.862, tilt: 3.13,
      base: '#c9b48a', accent: '#8a7550', bands: 14 },
    { name: '土星', au: 9.537, e: 0.0542, rEarth: 9.140, day: 0.4440, year: 29.457, tilt: 26.73,
      base: '#d8c99b', accent: '#a89770', bands: 10, ring: true },
    { name: '天王星', au: 19.19, e: 0.0472, rEarth: 3.981, day: -0.7183, year: 84.011, tilt: 97.77,
      base: '#8fd8e0', accent: '#5fa8b5' },
    { name: '海王星', au: 30.07, e: 0.0086, rEarth: 3.865, day: 0.6713, year: 164.79, tilt: 28.32,
      base: '#3a5bd9', accent: '#213a8f' }
  ]

  // 视觉缩放：半径按 sqrt 压缩（真实 109 倍的地球/太阳在屏幕上没法看）
  var PLANET_SCALE = 0.050
  var SUN_R = 2.6

  function create(container, items, onPick) {
    items = items || []
    if (typeof THREE === 'undefined') {
      container.innerHTML = '<div style="padding:24px;color:#7b8ea6">three.js 没加载成功</div>'
      return null
    }
    var W = container.clientWidth || 800
    var H = container.clientHeight || 500

    var scene = new THREE.Scene()
    var camera = new THREE.PerspectiveCamera(48, W / H, 0.1, 3000)
    var camDist = 30, camTheta = 0.6, camPhi = 1.1

    var renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    renderer.setSize(W, H)
    renderer.setClearColor(0x02030a, 0)
    container.appendChild(renderer.domElement)
    renderer.domElement.style.display = 'block'
    renderer.domElement.style.cursor = 'grab'

    // 远景星空
    var starGeo = new THREE.BufferGeometry()
    var starPos = new Float32Array(2600 * 3)
    for (var i = 0; i < starPos.length; i += 3) {
      var rr = 200 + Math.random() * 600
      var th = Math.random() * Math.PI * 2
      var ph = Math.acos(2 * Math.random() - 1)
      starPos[i] = rr * Math.sin(ph) * Math.cos(th)
      starPos[i + 1] = rr * Math.cos(ph)
      starPos[i + 2] = rr * Math.sin(ph) * Math.sin(th)
    }
    starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3))
    var starMat = new THREE.PointsMaterial({
      color: 0xffffff, size: 1.4, sizeAttenuation: true, transparent: true, opacity: 0.7
    })
    scene.add(new THREE.Points(starGeo, starMat))

    // 太阳
    var sunTex = sunTexture()
    var sunGeo = new THREE.SphereGeometry(SUN_R, 48, 48)
    var sunMat = new THREE.MeshBasicMaterial({ map: sunTex })
    var sun = new THREE.Mesh(sunGeo, sunMat)
    scene.add(sun)

    var glowTex = glowTexture()
    // 恒星核心 = importance 最高的记忆（必须先定义，后面光晕要用）
    var sortedByImp = items.slice().sort(function (a, b) { return (b.importance || 0) - (a.importance || 0) })
    var coreMems = sortedByImp.slice(0, 5)
    var coreImp = coreMems.length
      ? coreMems.reduce(function (a, m) { return a + (m.importance || 0) }, 0) / coreMems.length
      : 0.6
    var sunGlow = new THREE.Sprite(new THREE.SpriteMaterial({
      map: glowTex, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false
    }))
    sunGlow.scale.set(14 + coreImp * 10, 14 + coreImp * 10, 1)
    scene.add(sunGlow)

    // 光照
    var sunLight = new THREE.PointLight(0xfff2d0, 3.4, 0, 0)
    scene.add(sunLight)
    var ambient = new THREE.AmbientLight(0x404060, 1.0)
    scene.add(ambient)

    // 真实 AU 太大，用对数压缩成视觉半径
    function compressAU(au) {
      return 4.2 + Math.log10(1 + au * 2.2) * 10
    }

    // 按类型分组，行星绑定真实记忆
    var groups = {}
    items.forEach(function (m) { (groups[m.kind] = groups[m.kind] || []).push(m) })
    var kinds = Object.keys(groups).sort(function (a, b) { return groups[b].length - groups[a].length })
    var KIND_CN = { decision: '决定', pitfall: '踩坑', preference: '偏好', context: '背景', todo: '待办' }

    var planets = []
    PLANETS.forEach(function (p, pIdx) {
      var orbitR = compressAU(p.au)

      // 轨道线：真实椭圆 r = a(1-e²)/(1+e·cosθ)
      var e = p.e || 0
      var pts = []
      for (var a = 0; a <= 200; a++) {
        var nu = (a / 200) * Math.PI * 2
        var rr = orbitR * (1 - e * e) / (1 + e * Math.cos(nu))
        pts.push(new THREE.Vector3(Math.cos(nu) * rr, 0, Math.sin(nu) * rr))
      }
      var orbitGeo = new THREE.BufferGeometry().setFromPoints(pts)
      var orbitMat = new THREE.LineBasicMaterial({ color: 0x4a5a7a, transparent: true, opacity: 0.32 })
      scene.add(new THREE.Line(orbitGeo, orbitMat))

      // 行星
      var tex = planetTexture({ base: p.base, accent: p.accent, bands: p.bands })
      var visR = Math.pow(p.rEarth, 0.5) * PLANET_SCALE * 10
      var geo = new THREE.SphereGeometry(visR, 40, 40)
      var mat = new THREE.MeshStandardMaterial({ map: tex, roughness: 0.92, metalness: 0.0 })
      var mesh = new THREE.Mesh(geo, mat)
      mesh.rotation.z = p.tilt * Math.PI / 180

      var holder = new THREE.Group()
      holder.add(mesh)
      scene.add(holder)

      // 土星环：挂在 holder 上（不随行星自转），水平放置
      if (p.ring) {
        var ringGeo = new THREE.RingGeometry(visR * 1.28, visR * 2.15, 128)
        var ringMat = new THREE.MeshBasicMaterial({
          color: 0xe0d3a8, side: THREE.DoubleSide, transparent: true, opacity: 0.42
        })
        var ring = new THREE.Mesh(ringGeo, ringMat)
        ring.rotation.x = Math.PI / 2 + p.tilt * Math.PI / 180   // 与行星轴倾角一致
        holder.add(ring)
        // 内外两道细环，做出层次
        var ring2 = new THREE.Mesh(
          new THREE.RingGeometry(visR * 2.32, visR * 2.72, 128),
          new THREE.MeshBasicMaterial({
            color: 0xcbbf96, side: THREE.DoubleSide, transparent: true, opacity: 0.22
          })
        )
        ring2.rotation.x = Math.PI / 2 + p.tilt * Math.PI / 180
        holder.add(ring2)
      }

      var boundKind = kinds.length ? kinds[pIdx % kinds.length] : null
      var memList = boundKind ? (groups[boundKind] || []) : []
      planets.push({
        data: p, mesh: mesh, holder: holder, orbitR: orbitR, e: e,
        M: Math.random() * Math.PI * 2,   // 平近点角
        kind: boundKind, memList: memList, kindCn: boundKind ? (KIND_CN[boundKind] || boundKind) : ''
      })
    })

    /* ── 交互 ─────────────────────────────────────── */
    var el = renderer.domElement
    var dragging = false, lastX = 0, lastY = 0, autoSpin = true
  /* 自动旋转的暂停与恢复：点击/拖动只是「暂时」停转，4 秒后自己回来 */
  var spinTimer = 0
  function pauseAutoSpin(ms) {
    autoSpin = false
    if (spinTimer) clearTimeout(spinTimer)
    spinTimer = setTimeout(function () { autoSpin = true }, ms || 4000)
  }

    var raycaster = new THREE.Raycaster()
    var pointer = new THREE.Vector2()
    var hovered = null

    function onDown(e) { dragging = true; pauseAutoSpin(6000); lastX = e.clientX; lastY = e.clientY }
    function onMove(e) {
      if (!dragging) return
      camTheta -= (e.clientX - lastX) * 0.005
      camPhi -= (e.clientY - lastY) * 0.004
      camPhi = Math.max(0.15, Math.min(Math.PI - 0.15, camPhi))
      lastX = e.clientX; lastY = e.clientY
    }
    function onUp() { dragging = false; pauseAutoSpin(4000) }
    function onWheel(e) {
      e.preventDefault()
      camDist *= (1 + Math.sign(e.deltaY) * 0.08)
      camDist = Math.max(8, Math.min(120, camDist))
    }
    var sunHovered = false
    function onHover(e) {
      var rect = el.getBoundingClientRect()
      pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1
      pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1
      raycaster.setFromCamera(pointer, camera)
      var targets = planets.map(function (p) { return p.mesh })
      targets.push(sun)
      var hit = raycaster.intersectObjects(targets, false)
      hovered = null
      sunHovered = false
      if (hit.length) {
        if (hit[0].object === sun) {
          sunHovered = true
        } else {
          hovered = planets.filter(function (p) { return p.mesh === hit[0].object })[0]
        }
      }
      el.style.cursor = (hovered || sunHovered) ? 'pointer' : 'grab'
      container.title = sunHovered
        ? ('恒星核心 · 最重要 ' + coreMems.length + ' 条记忆')
        : (hovered ? (hovered.data.name + (hovered.kindCn ? ' · ' + hovered.kindCn + ' ' + hovered.memList.length + ' 条' : '')) : '')
    }
    function onClick() {
      if (sunHovered && typeof onPick === 'function') {
        onPick({ name: '恒星核心', isCore: true, memList: coreMems, kindCn: '最重要' })
        return
      }
      if (hovered && typeof onPick === 'function') {
        onPick({
          name: hovered.data.name,
          au: hovered.data.au,
          e: hovered.data.e,
          rEarth: hovered.data.rEarth,
          year: hovered.data.year,
          day: hovered.data.day,
          tilt: hovered.data.tilt,
          kind: hovered.kind,
          kindCn: hovered.kindCn,
          memList: hovered.memList
        })
      }
    }

    el.addEventListener('mousedown', onDown)
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    el.addEventListener('wheel', onWheel, { passive: false })
    el.addEventListener('mousemove', onHover)
    el.addEventListener('click', onClick)

    /* ── 动画 ─────────────────────────────────────── */
    var raf = 0
    var clock = new THREE.Clock()
    var EARTH_ORBIT_SEC = 26   // 地球公转一圈 26 秒
    var EARTH_DAY_SEC = 2.2    // 地球自转一圈 2.2 秒

    function frame() {
      var dt = clock.getDelta()
      var t = clock.elapsedTime

      planets.forEach(function (p) {
        var period = EARTH_ORBIT_SEC * Math.pow(p.data.year, 0.55)
        // 平近点角均匀推进，再由开普勒方程解出真实位置（近日点快、远日点慢）
        p.M += (Math.PI * 2 / period) * dt
        var e = p.e
        var E = p.M
        for (var it = 0; it < 5; it++) {
          E = E - (E - e * Math.sin(E) - p.M) / (1 - e * Math.cos(E))
        }
        // 真近点角
        var nu = 2 * Math.atan2(Math.sqrt(1 + e) * Math.sin(E / 2), Math.sqrt(1 - e) * Math.cos(E / 2))
        // 到太阳的距离
        var r = p.orbitR * (1 - e * Math.cos(E))
        p.holder.position.set(Math.cos(nu) * r, 0, Math.sin(nu) * r)

        // 自转：真实日长做 0.6 次幂压缩，负值=逆行
        var dayPeriod = EARTH_DAY_SEC * Math.pow(Math.abs(p.data.day), 0.6)
        p.mesh.rotation.y += (Math.PI * 2 / dayPeriod) * dt * (p.data.day < 0 ? -1 : 1)
      })

      sun.rotation.y += dt * 0.08   // 太阳赤道自转约 25 天
      var pulse = 1 + Math.sin(t * 1.1) * 0.02
      var gs = (14 + coreImp * 10) * pulse
      sunGlow.scale.set(gs, gs, 1)

      if (autoSpin && !dragging) camTheta += dt * 0.02
      camera.position.set(
        camDist * Math.sin(camPhi) * Math.sin(camTheta),
        camDist * Math.cos(camPhi) + 3,
        camDist * Math.sin(camPhi) * Math.cos(camTheta)
      )
      camera.lookAt(0, 0, 0)
      renderer.render(scene, camera)
      raf = requestAnimationFrame(frame)
    }
    frame()

    function onResize() {
      var w = container.clientWidth || W
      var h = container.clientHeight || H
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      renderer.setSize(w, h)
    }
    window.addEventListener('resize', onResize)

    return {
      dispose: function () {
        cancelAnimationFrame(raf)
        window.removeEventListener('mousemove', onMove)
        window.removeEventListener('mouseup', onUp)
        window.removeEventListener('resize', onResize)
        el.removeEventListener('mousedown', onDown)
        el.removeEventListener('wheel', onWheel)
        el.removeEventListener('mousemove', onHover)
        el.removeEventListener('click', onClick)
        scene.traverse(function (o) {
          if (o.geometry) o.geometry.dispose()
          if (o.material) {
            if (o.material.map) o.material.map.dispose()
            o.material.dispose()
          }
        })
        try { renderer.forceContextLoss && renderer.forceContextLoss() } catch (_e) {}
        renderer.dispose()
        if (el.parentNode) el.parentNode.removeChild(el)
      }
    }
  }

  window.DSHSolar = { create: create }
})()