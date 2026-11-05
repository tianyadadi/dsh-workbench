/**
 * DSH 记忆银河系 —— three.js 3D 星图（v2：改用内置材质，保证能渲染）
 * ============================================================================
 * 映射规则：
 *   · 核球   = importance ≥ 0.85 的记忆（单独一层，尺寸更大）
 *   · 旋臂   = 按 kind 分 5 条：决定 / 踩坑 / 偏好 / 背景 / 待办
 *   · 位置   = 越重要越靠内
 *   · 亮度   = activation（颜色按活跃度调明暗）
 *   · 星尘   = 4200 个粒子，沿旋臂铺开
 *   · 自转   = 缓慢旋转；可拖拽、滚轮缩放、点星看详情
 *
 * v2 说明：v1 用自定义 ShaderMaterial，attribute 名与 three 内置 color 冲突，
 * 整个 Points 编译失败（只剩核球光晕）。v2 改用内置 PointsMaterial +
 * vertexColors，确保一定能出图。
 * ============================================================================
 */
(function () {
  'use strict'

  var KIND_ORDER = ['decision', 'pitfall', 'preference', 'context', 'todo']
  var KIND_COLOR = {
    decision: 0x4dd0e1,
    pitfall: 0xff8a50,
    preference: 0xc792ea,
    context: 0x9ccc65,
    todo: 0xffd54f
  }
  var CORE_TINT = 0xffe9a8

  function glowTexture() {
    var s = 128
    var cv = document.createElement('canvas')
    cv.width = cv.height = s
    var ctx = cv.getContext('2d')
    var g = ctx.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2)
    g.addColorStop(0, 'rgba(255,255,255,1)')
    g.addColorStop(0.25, 'rgba(255,255,255,0.85)')
    g.addColorStop(0.55, 'rgba(255,255,255,0.25)')
    g.addColorStop(1, 'rgba(255,255,255,0)')
    ctx.fillStyle = g
    ctx.fillRect(0, 0, s, s)
    var tex = new THREE.CanvasTexture(cv)
    tex.colorSpace = THREE.SRGBColorSpace
    return tex
  }

  /* ── 星芒纹理：模拟明亮恒星的衍射芒（4 长 + 4 短，共 8 条） ── */
  function starburstTexture() {
    var s = 512, c = s / 2
    var cv = document.createElement('canvas')
    cv.width = cv.height = s
    var ctx = cv.getContext('2d')

    // 中心极亮核
    var core = ctx.createRadialGradient(c, c, 0, c, c, c * 0.16)
    core.addColorStop(0, 'rgba(255,255,255,1)')
    core.addColorStop(0.35, 'rgba(255,250,235,0.95)')
    core.addColorStop(0.7, 'rgba(255,238,200,0.35)')
    core.addColorStop(1, 'rgba(255,230,180,0)')
    ctx.fillStyle = core
    ctx.fillRect(0, 0, s, s)

    // 8 条星芒：主轴 4 条长、对角 4 条短
    for (var i = 0; i < 8; i++) {
      var a = i * Math.PI / 4
      var isMain = (i % 2 === 0)
      var len = isMain ? c * 0.96 : c * 0.52
      var g = ctx.createLinearGradient(c, c, c + Math.cos(a) * len, c + Math.sin(a) * len)
      g.addColorStop(0, 'rgba(255,255,250,0.95)')
      g.addColorStop(0.18, 'rgba(255,248,225,0.62)')
      g.addColorStop(0.45, 'rgba(255,238,195,0.22)')
      g.addColorStop(1, 'rgba(255,225,170,0)')
      ctx.strokeStyle = g
      ctx.lineWidth = isMain ? 4.5 : 2.4
      ctx.lineCap = 'round'
      ctx.beginPath()
      // 芒从核心外侧开始，避免中心过曝成一片
      ctx.moveTo(c + Math.cos(a) * len * 0.06, c + Math.sin(a) * len * 0.06)
      ctx.lineTo(c + Math.cos(a) * len, c + Math.sin(a) * len)
      ctx.stroke()
    }
    var tex = new THREE.CanvasTexture(cv)
    tex.colorSpace = THREE.SRGBColorSpace
    return tex
  }

  function rng(seed) {
    var s = seed % 2147483647
    if (s <= 0) s += 2147483646
    return function () {
      s = (s * 16807) % 2147483647
      return (s - 1) / 2147483646
    }
  }

  function spiral(armIndex, arms, t, jitterR, jitterA) {
    // 对数螺旋：r = a·e^(bθ)，真实旋臂的形态
    var base = (armIndex / arms) * Math.PI * 2
    var theta = t * 3.1
    var angle = base + theta + jitterA
    var radius = 1.8 * Math.exp(0.62 * theta)
    var rr = Math.min(radius, 14.2)
    // 抖动量按半径缩放：内圈更紧、外圈更松散（符合真实旋臂）
    var spread = jitterR * (0.35 + t * 0.95)
    return [
      Math.cos(angle) * rr + spread,
      (Math.random() - 0.5) * Math.max(0.25, 1.3 - t * 1.0),
      Math.sin(angle) * rr + spread * 0.7
    ]
  }

  function create(container, items, onPick) {
    if (typeof THREE === 'undefined') {
      container.innerHTML = '<div style="padding:24px;color:#7b8ea6">three.js 没加载成功</div>'
      return null
    }

    var W = container.clientWidth || 800
    var H = container.clientHeight || 500
    var scene = new THREE.Scene()
    var camera = new THREE.PerspectiveCamera(52, W / H, 0.1, 500)
    var camDist = 52, camTheta = 0.6, camPhi = 1.02

    var renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    renderer.setSize(W, H)
    renderer.setClearColor(0x01040a, 0)
    container.appendChild(renderer.domElement)
    renderer.domElement.style.display = 'block'
    renderer.domElement.style.cursor = 'grab'

    var galaxy = new THREE.Group()
    scene.add(galaxy)
    var sprite = glowTexture()

    /* ── 记忆点 ─────────────────────────────────────────────── */
    var arms = KIND_ORDER.length
    var buckets = {}
    items.forEach(function (m) {
      var k = m.kind || 'context'
      ;(buckets[k] = buckets[k] || []).push(m)
    })

    var posMain = [], colMain = []
    var posCore = [], colCore = []
    var nodeData = []

    KIND_ORDER.forEach(function (kind, armIdx) {
      var list = buckets[kind] || []
      var rd = rng(1000 + armIdx * 137)
      list.forEach(function (m) {
        var imp = Math.max(0.15, Math.min(1, m.importance || 0.6))
        var act = Math.max(0.1, Math.min(1, m.activation || 0.7))
        var p
        if (imp >= 0.85) {
          var rr = 1.0 + rd() * 2.6
          var th = rd() * Math.PI * 2
          var ph = Math.acos(2 * rd() - 1)
          p = [rr * Math.sin(ph) * Math.cos(th), rr * Math.cos(ph) * 0.5, rr * Math.sin(ph) * Math.sin(th)]
        } else {
          var t = Math.max(0.05, Math.min(0.97, 0.12 + (1 - imp) * 0.83 + (rd() - 0.5) * 0.08))
          var spread = 0.55 + t * 1.15
          p = spiral(armIdx, arms, t, (rd() - 0.5) * spread, (rd() - 0.5) * 0.22)
        }
        var c = new THREE.Color(KIND_COLOR[kind] || 0x8899aa)
        if (imp >= 0.85) c.lerp(new THREE.Color(CORE_TINT), 0.5)
        c.multiplyScalar(0.60 + act * 0.85)
        if (imp >= 0.85) {
          posCore.push(p[0], p[1], p[2]); colCore.push(c.r, c.g, c.b)
        } else {
          posMain.push(p[0], p[1], p[2]); colMain.push(c.r, c.g, c.b)
        }
        nodeData.push({ m: m, pos: p, color: c })
      })
    })

    function makePoints(pos, col, size, opacity) {
      var g = new THREE.BufferGeometry()
      g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
      g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3))
      g.computeBoundingSphere()
      var mat = new THREE.PointsMaterial({
        size: size,
        map: sprite,
        vertexColors: true,
        transparent: true,
        opacity: opacity,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        sizeAttenuation: true
      })
      return new THREE.Points(g, mat)
    }

    var pointsMain = makePoints(posMain, colMain, 0.42, 0.95)
    galaxy.add(pointsMain)
    var pointsCore = makePoints(posCore, colCore, 0.85, 1.0)
    galaxy.add(pointsCore)

    /* ── 星尘 ───────────────────────────────────────────────── */
    var DUST = 9500
    var dpos = [], dcol = []
    var rd2 = rng(20261106)
    for (var i = 0; i < DUST; i++) {
      var arm = Math.floor(rd2() * arms)
      var t2 = Math.pow(rd2(), 0.62)
      var spread2 = 0.7 + t2 * 1.6
      var pp = spiral(arm, arms, t2, (rd2() - 0.5) * spread2, (rd2() - 0.5) * 0.5)
      dpos.push(pp[0], pp[1] * (2.2 - t2) * 0.85, pp[2])
      // 真实旋臂：内圈偏黄白（年老恒星），外圈偏蓝白（年轻恒星）
      var cc = new THREE.Color(0xfff2d0).lerp(new THREE.Color(0x9fc8ff), Math.min(1, t2 * 1.15))
      cc.lerp(new THREE.Color(0xffffff), rd2() * 0.32)
      var dim = 0.46 + rd2() * 0.50
      dcol.push(cc.r * dim, cc.g * dim, cc.b * dim)
    }
    var pointsDust = makePoints(dpos, dcol, 0.17, 0.66)
    galaxy.add(pointsDust)

    /* ── 星云气体：大颗粒 + 低透明度，做出粉蓝雾感 ───────────── */
    var NEB = 1100
    var npos = [], ncol = []
    var rd3 = rng(777)
    for (var j = 0; j < NEB; j++) {
      var arm3 = Math.floor(rd3() * arms)
      var t3 = Math.pow(rd3(), 0.52)
      var spread3 = 1.1 + t3 * 2.4
      var q = spiral(arm3, arms, t3, (rd3() - 0.5) * spread3, (rd3() - 0.5) * 0.65)
      npos.push(q[0], q[1] * 1.5, q[2])
      // 蓝紫 → 粉红 → 白青 混合，模拟真实旋臂气体
      var hue = (0.54 + rd3() * 0.30) % 1
      var sat = 0.42 + rd3() * 0.3
      var c3 = new THREE.Color().setHSL(hue, sat, 0.60)
      var d3 = 0.17 + rd3() * 0.23
      ncol.push(c3.r * d3, c3.g * d3, c3.b * d3)
    }
    var pointsNeb = makePoints(npos, ncol, 1.05, 0.12)
    galaxy.add(pointsNeb)

    /* ── 四周小星系：320 个，盘状同层分布，各自绕自身中心自转 ──────
       实现：顶点存"相对星系中心的偏移"，另带 aCenter(中心) / aPhase(初相)
       / aSpeed(自转速度) 三个属性，顶点着色器里做绕 Y 轴旋转。
       好处：320 个星系只有 1 次 draw call，每个还能独立转。
    ───────────────────────────────────────────────────────────── */
    var MINI_COUNT = 480
    var mLocal = [], mCenter = [], mColor = [], mPhase = [], mSpeed = []
    var mGlowCenter = [], mGlowColor = []
    var rdm = rng(20261106)

    for (var mi = 0; mi < MINI_COUNT; mi++) {
      var isBig = rdm() < 0.10
      var msize = isBig ? (0.34 + rdm() * 0.30) : (0.06 + rdm() * 0.15)
      var mcount = isBig ? (150 + Math.floor(rdm() * 110)) : (30 + Math.floor(rdm() * 42))
      var marms = 2 + Math.floor(rdm() * 2)
      var mhue = 0.42 + rdm() * 0.44
      var msat = 0.40 + rdm() * 0.40
      // 倾斜收窄：±0.6 弧度（±34°），大部分接近正面朝向
      var mtilt = (rdm() - 0.5) * 1.2

      // 半径：内圈更密（小的用 1.15 次方压向中心）
      var mrad = isBig ? (40 + rdm() * 60) : (8 + Math.pow(rdm(), 1.15) * 72)
      var mang = rdm() * Math.PI * 2
      var mcx = Math.cos(mang) * mrad
      var mcz = Math.sin(mang) * mrad
      // 高度三层：40% 完全同层，50% 薄盘，10% 稍有高低
      var yr = rdm()
      var mcy = (yr < 0.40) ? ((rdm() - 0.5) * 4)
              : (yr < 0.90 ? ((rdm() - 0.5) * 16) : ((rdm() - 0.5) * 46))

      var myPhase = rdm() * Math.PI * 2
      var mySpeed = (rdm() < 0.5 ? 1 : -1) * (0.06 + rdm() * 0.20)

      for (var mk = 0; mk < mcount; mk++) {
        var mt = Math.pow(rdm(), 0.58)
        var marm = Math.floor(rdm() * marms)
        var mma = (marm / marms) * Math.PI * 2 + mt * 4.6 + (rdm() - 0.5) * 0.55
        var mrr = mt * msize * 9 + (rdm() - 0.5) * msize * 1.4
        var lx = Math.cos(mma) * mrr
        var lz = Math.sin(mma) * mrr * 0.72
        var ly = (rdm() - 0.5) * msize * 0.9
        var rx = lx * Math.cos(mtilt) - ly * Math.sin(mtilt)
        var ry = lx * Math.sin(mtilt) + ly * Math.cos(mtilt)
        mLocal.push(rx, ry, lz)
        mCenter.push(mcx, mcy, mcz)
        var mc = new THREE.Color().setHSL(mhue, msat, 0.74)
        var md = 0.34 + rdm() * 0.62
        mColor.push(mc.r * md, mc.g * md, mc.b * md)
        mPhase.push(myPhase)
        mSpeed.push(mySpeed)
      }

      var gc = new THREE.Color().setHSL(mhue, Math.min(1, msat + 0.1), 0.80)
      mGlowCenter.push(mcx, mcy, mcz)
      mGlowColor.push(gc.r * 0.6, gc.g * 0.6, gc.b * 0.6)
    }

    var miniGeo = new THREE.BufferGeometry()
    miniGeo.setAttribute('position', new THREE.Float32BufferAttribute(mLocal, 3))
    miniGeo.setAttribute('aCenter', new THREE.Float32BufferAttribute(mCenter, 3))
    miniGeo.setAttribute('aColor', new THREE.Float32BufferAttribute(mColor, 3))
    miniGeo.setAttribute('aPhase', new THREE.Float32BufferAttribute(mPhase, 1))
    miniGeo.setAttribute('aSpeed', new THREE.Float32BufferAttribute(mSpeed, 1))
    miniGeo.computeBoundingSphere()

    var miniMat = new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uHeight: { value: (renderer.domElement.height || H) * 0.5 },
        uSize: { value: 0.15 },
        uTex: { value: sprite }
      },
      vertexShader: [
        'attribute vec3 aCenter;',
        'attribute vec3 aColor;',
        'attribute float aPhase;',
        'attribute float aSpeed;',
        'uniform float uTime;',
        'uniform float uHeight;',
        'uniform float uSize;',
        'varying vec3 vColor;',
        'void main() {',
        '  float ang = uTime * aSpeed + aPhase;',
        '  float ca = cos(ang), sa = sin(ang);',
        '  vec3 p = position;',
        '  vec3 rp = vec3(p.x * ca - p.z * sa, p.y, p.x * sa + p.z * ca);',
        '  vec3 world = aCenter + rp;',
        '  vec4 mv = modelViewMatrix * vec4(world, 1.0);',
        '  gl_PointSize = uSize * uHeight / -mv.z;',
        '  gl_Position = projectionMatrix * mv;',
        '  vColor = aColor;',
        '}'
      ].join('\n'),
      fragmentShader: [
        'uniform sampler2D uTex;',
        'varying vec3 vColor;',
        'void main() {',
        '  vec4 t = texture2D(uTex, gl_PointCoord);',
        '  if (t.a < 0.03) discard;',
        '  gl_FragColor = vec4(vColor, t.a);',
        '}'
      ].join('\n'),
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending
    })

    var pointsMini = new THREE.Points(miniGeo, miniMat)
    galaxy.add(pointsMini)

    // 星系中心微光（仍是普通 Points，不参与自转）
    var pointsMiniGlow = makePoints(mGlowCenter, mGlowColor, 2.2, 0.30)
    galaxy.add(pointsMiniGlow)

    /* ── 核球：四层叠加做出"最亮恒星"的光 ─────────────────────── */
    // 内核：中心接近纯白
    var coreCv = document.createElement('canvas')
    coreCv.width = coreCv.height = 256
    var cctx = coreCv.getContext('2d')
    var cg = cctx.createRadialGradient(128, 128, 0, 128, 128, 128)
    cg.addColorStop(0, 'rgba(255,255,255,1)')
    cg.addColorStop(0.12, 'rgba(255,252,238,0.98)')
    cg.addColorStop(0.32, 'rgba(255,226,160,0.62)')
    cg.addColorStop(0.62, 'rgba(255,186,96,0.18)')
    cg.addColorStop(1, 'rgba(255,160,60,0)')
    cctx.fillStyle = cg
    cctx.fillRect(0, 0, 256, 256)
    var coreTex = new THREE.CanvasTexture(coreCv)

    var core = new THREE.Sprite(new THREE.SpriteMaterial({
      map: coreTex, transparent: true, blending: THREE.AdditiveBlending,
      depthWrite: false, opacity: 1.0
    }))
    core.scale.set(4.6, 4.6, 1)
    galaxy.add(core)

    // 中晕：暖橙色扩散
    var halo = new THREE.Sprite(new THREE.SpriteMaterial({
      map: coreTex, transparent: true, blending: THREE.AdditiveBlending,
      depthWrite: false, opacity: 0.30, color: 0xffd9a0
    }))
    halo.scale.set(12, 12, 1)
    galaxy.add(halo)

    // 外晕：很淡的一层，让核心"溢出"到旋臂
    var outerGlow = new THREE.Sprite(new THREE.SpriteMaterial({
      map: coreTex, transparent: true, blending: THREE.AdditiveBlending,
      depthWrite: false, opacity: 0.12, color: 0xffc880
    }))
    outerGlow.scale.set(21, 21, 1)
    galaxy.add(outerGlow)

    // 星芒：8 条衍射芒（真实望远镜里亮恒星的样子）
    var burstTex = starburstTexture()
    var burst = new THREE.Sprite(new THREE.SpriteMaterial({
      map: burstTex, transparent: true, blending: THREE.AdditiveBlending,
      depthWrite: false, opacity: 0.46
    }))
    burst.scale.set(13.5, 13.5, 1)
    galaxy.add(burst)

    /* ── 交互 ───────────────────────────────────────────────── */
    var el = renderer.domElement
    var dragging = false, lastX = 0, lastY = 0, autoSpin = true
    var mouseV = new THREE.Vector3()
    var hoveredData = null

    function onDown(e) { dragging = true; autoSpin = false; lastX = e.clientX; lastY = e.clientY }
    function onMove(e) {
      if (!dragging) return
      camTheta -= (e.clientX - lastX) * 0.005
      camPhi -= (e.clientY - lastY) * 0.004
      camPhi = Math.max(0.16, Math.min(Math.PI - 0.16, camPhi))
      lastX = e.clientX; lastY = e.clientY
    }
    function onUp() { dragging = false }
    function onWheel(e) {
      e.preventDefault()
      camDist *= (1 + Math.sign(e.deltaY) * 0.08)
      camDist = Math.max(8, Math.min(220, camDist))
    }

    // 命中检测：投影每个节点到屏幕，找最近的一个（比 Points raycast 稳）
    var cachedRect = null
    function canvasRect() {
      if (!cachedRect) cachedRect = el.getBoundingClientRect()
      return cachedRect
    }

    function pick(ev) {
      var rect = canvasRect()
      var mx = ev.clientX - rect.left
      var my = ev.clientY - rect.top
      var best = null, bestD = 18 * 18
      for (var i = 0; i < nodeData.length; i++) {
        var nd = nodeData[i]
        mouseV.set(nd.pos[0], nd.pos[1], nd.pos[2])
        mouseV.applyMatrix4(galaxy.matrixWorld)
        mouseV.project(camera)
        var sx = (mouseV.x * 0.5 + 0.5) * rect.width
        var sy = (-mouseV.y * 0.5 + 0.5) * rect.height
        var d = (sx - mx) * (sx - mx) + (sy - my) * (sy - my)
        if (d < bestD) { bestD = d; best = nd }
      }
      return best
    }

    var lastPickTs = 0
    function onHover(e) {
      var now = (typeof performance !== 'undefined' ? performance.now() : Date.now())
      if (now - lastPickTs < 55) return          // 节流：60ms 内不重复投影 131 个点
      lastPickTs = now
      hoveredData = pick(e)
      el.style.cursor = hoveredData ? 'pointer' : 'grab'
      container.title = hoveredData ? (hoveredData.m.title || '') : ''
    }
    function onClick() {
      if (hoveredData && typeof onPick === 'function') onPick(hoveredData.m)
    }

    el.addEventListener('mousedown', onDown)
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    el.addEventListener('wheel', onWheel, { passive: false })
    el.addEventListener('mousemove', onHover)
    el.addEventListener('click', onClick)

    /* ── 渲染循环 ───────────────────────────────────────────── */
    var raf = 0
    var clock = new THREE.Clock()
    var selfChecked = false

    function frame() {
      var dt = clock.getDelta()
      if (!selfChecked && clock.elapsedTime > 1.2) {
        selfChecked = true
        var pts = renderer.info.render.points
        if (pts < 100) {
          var warn = document.createElement('div')
          warn.style.cssText = 'position:absolute;left:12px;top:12px;padding:8px 12px;' +
            'background:rgba(255,80,80,.14);border:1px solid rgba(255,80,80,.5);border-radius:8px;' +
            'color:#ffb3b3;font-size:12px;z-index:5;pointer-events:none'
          warn.textContent = '星点渲染异常：points=' + pts
          container.appendChild(warn)
        }
      }

      galaxy.rotation.y += dt * (autoSpin ? 0.072 : 0.008)
      miniMat.uniforms.uTime.value = clock.elapsedTime   // 小星系各自自转
      var pulse = 1 + Math.sin(clock.elapsedTime * 0.8) * 0.04
      core.scale.set(4.6 * pulse, 4.6 * pulse, 1)
      halo.scale.set(12 * (1 + (pulse - 1) * 0.6), 12 * (1 + (pulse - 1) * 0.6), 1)
      outerGlow.scale.set(21 * (1 + (pulse - 1) * 0.4), 21 * (1 + (pulse - 1) * 0.4), 1)
      // 星芒缓慢自转，跟着星系一起转的感觉
      burst.material.rotation += dt * 0.09
      burst.scale.set(13.5 * (1 + (pulse - 1) * 1.1), 13.5 * (1 + (pulse - 1) * 1.1), 1)
      burst.material.opacity = 0.42 + Math.sin(clock.elapsedTime * 1.1) * 0.06

      camera.position.set(
        camDist * Math.sin(camPhi) * Math.sin(camTheta),
        camDist * Math.cos(camPhi) + 1.5,
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
      cachedRect = null
      miniMat.uniforms.uHeight.value = renderer.domElement.height * 0.5
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
        ;[pointsMain, pointsCore, pointsDust, pointsNeb, pointsMini, pointsMiniGlow].forEach(function (p) {
          p.geometry.dispose(); p.material.dispose()
        })
        coreTex.dispose(); burstTex.dispose(); sprite.dispose()
        ;[core, halo, outerGlow, burst].forEach(function (o) { o.material.dispose() })
        try { renderer.forceContextLoss && renderer.forceContextLoss() } catch (_e) {}
        renderer.dispose()
        if (el.parentNode) el.parentNode.removeChild(el)
        Array.prototype.slice.call(container.querySelectorAll('div')).forEach(function (d) { d.remove() })
      }
    }
  }

  window.DSHGalaxy = { create: create }
})()
