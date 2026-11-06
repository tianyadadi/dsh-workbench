/* 关系图谱视图 —— 每类记忆一朵「发光星云花」
 *
 * 映射规则（遵守「可视化必须对应真实数据」）：
 *   · 一朵花 = 一个记忆类型（decision / pitfall / preference / context / todo）
 *   · 花心 = 该类聚合点，亮度与大小跟条数走
 *   · 一个光点 = 一条真实记忆，半径由 importance 决定，颜色 = 类型
 *   · 一根线 = 这条记忆与它所属类心的关系；节点之间的线 = Fibonacci 球面上相邻的两条
 *   · 外围星尘 = 每条记忆再投影一个「长期层」点，亮度 = activation
 * 零外部依赖，只用本地 three.js。
 */
(function () {
  'use strict'

  var KIND_ORDER = ['decision', 'pitfall', 'preference', 'context', 'todo']
  var FALLBACK = {
    decision: '#4dd0e1', pitfall: '#ff8a65', preference: '#c792ea',
    context: '#9ccc65', todo: '#ffd54f'
  }

  function hexToRgb(h) {
    var s = h.replace('#', '')
    if (s.length === 3) s = s[0] + s[0] + s[1] + s[1] + s[2] + s[2]
    var n = parseInt(s, 16)
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
  }

  /* 圆形柔光贴图 */
  function glowTexture() {
    var s = 128
    var c = document.createElement('canvas')
    c.width = c.height = s
    var g = c.getContext('2d')
    var grd = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2)
    grd.addColorStop(0, 'rgba(255,255,255,1)')
    grd.addColorStop(0.25, 'rgba(255,255,255,.72)')
    grd.addColorStop(0.55, 'rgba(255,255,255,.20)')
    grd.addColorStop(1, 'rgba(255,255,255,0)')
    g.fillStyle = grd
    g.fillRect(0, 0, s, s)
    var t = new THREE.CanvasTexture(c)
    t.needsUpdate = true
    return t
  }

  /* Fibonacci 球面：均匀撒点 */
  function spherePoint(i, n, radius) {
    var ga = Math.PI * (3 - Math.sqrt(5))
    var y = 1 - (i / Math.max(1, n - 1)) * 2
    var r = Math.sqrt(Math.max(0, 1 - y * y))
    var th = ga * i
    return { x: Math.cos(th) * r * radius, y: y * radius, z: Math.sin(th) * r * radius }
  }

  function create(container, items, onPick, colorMap) {
    if (typeof THREE === 'undefined') {
      container.innerHTML = '<div style="padding:24px;color:#7b8ea6">three.js 没加载成功</div>'
      return null
    }
    var W = container.clientWidth || 800
    var H = container.clientHeight || 500

    var scene = new THREE.Scene()
    var camera = new THREE.PerspectiveCamera(50, W / H, 0.1, 800)
    var camDist = 104, camTheta = 0.65, camPhi = 1.05

    var renderer
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    } catch (err) {
      container.innerHTML = '<div style="padding:24px;color:#7b8ea6;font-size:13px;line-height:1.9">' +
        'WebGL 创建失败，关系图谱用不了。<br>试试换浏览器，或在设置里开启硬件加速。</div>'
      return null
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75))
    renderer.setSize(W, H)
    renderer.setClearColor(0x01040a, 0)
    container.appendChild(renderer.domElement)
    renderer.domElement.style.display = 'block'
    renderer.domElement.style.cursor = 'grab'
    // 深色底：WebGL 上下文丢失时也不会露出刺眼的白板
    renderer.domElement.style.background = '#03060c'
    renderer.domElement.addEventListener('webglcontextlost', function (e) {
      e.preventDefault()
      container.innerHTML = '<div style="padding:24px;color:#e8b45a;font-size:13px;line-height:1.9">' +
        'GPU 上下文丢了（显存吃紧或驱动重置）。切到别的视图再切回来即可重建。</div>'
    })

    var root = new THREE.Group()
    scene.add(root)
    var tex = glowTexture()

    /* ── 分桶 ─────────────────────────────────────────────── */
    var buckets = {}
    items.forEach(function (m) {
      var k = KIND_ORDER.indexOf(m.kind) >= 0 ? m.kind : 'context'
      ;(buckets[k] = buckets[k] || []).push(m)
    })
    var kinds = KIND_ORDER.filter(function (k) { return buckets[k] && buckets[k].length })

    function colorOf(k) {
      return (colorMap && colorMap[k]) || FALLBACK[k] || '#9aa7b4'
    }

    /* 花心摆位：大圆上一圈，每朵花的大小按条数走 */
    var MAXR = kinds.length > 1 ? 20 : 0
    var total = items.length || 1
    var centers = {}
    kinds.forEach(function (k, i) {
      var ang = (i / kinds.length) * Math.PI * 2 + 0.4
      var share = buckets[k].length / total
      centers[k] = new THREE.Vector3(
        Math.cos(ang) * MAXR * (0.55 + share * 1.6),
        Math.sin(i * 1.7) * 2.5,
        Math.sin(ang) * MAXR * (0.55 + share * 1.6)
      )
    })

    var texCache = {}
    function lineMat() {
      return new THREE.LineBasicMaterial({
        vertexColors: true, transparent: true, opacity: 0.3,
        blending: THREE.AdditiveBlending, depthWrite: false
      })
    }

    var lineGroups = []
    var nodeLayers = []
    var centersGroup = []
    var pickable = []   // {pos, mem}

    kinds.forEach(function (kind) {
      var list = buckets[kind]
      var c = centers[kind]
      var rgb = hexToRgb(colorOf(kind))
      var radius = 7 + Math.min(6, list.length * 0.08)
      var col = new THREE.Color(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)

      var nodePos = []
      var nodeCol = []
      var n = list.length

      /* 光点 */
      for (var i = 0; i < n; i++) {
        var p = spherePoint(i, n, radius)
        var imp = Math.max(0.2, Math.min(1, list[i].importance || 0.5))
        var s = radius * (1 - imp * 0.35)   // 越重要越靠里
        var x = c.x + p.x * (s / radius)
        var y = c.y + p.y * (s / radius)
        var z = c.z + p.z * (s / radius)
        nodePos.push(x, y, z)
        nodeCol.push(col.r, col.g, col.b)
        pickable.push({ x: x, y: y, z: z, mem: list[i] })
        // 拖尾：沿径向朝外放两个更暗的点，静止也一样有「光束」感
        var ux = p.x / radius, uy = p.y / radius, uz = p.z / radius
        nodePos.push(x + ux * 0.9, y + uy * 0.9, z + uz * 0.9)
        nodeCol.push(col.r * 0.45, col.g * 0.45, col.b * 0.45)
        nodePos.push(x + ux * 2.0, y + uy * 2.0, z + uz * 2.0)
        nodeCol.push(col.r * 0.16, col.g * 0.16, col.b * 0.16)
      }

      /* 节点云 */
      var pg = new THREE.BufferGeometry()
      pg.setAttribute('position', new THREE.Float32BufferAttribute(nodePos, 3))
      pg.setAttribute('color', new THREE.Float32BufferAttribute(nodeCol, 3))
      var pm = new THREE.PointsMaterial({
        size: 1.7, map: tex, vertexColors: true, transparent: true,
        opacity: 0.95, blending: THREE.AdditiveBlending, depthWrite: false,
        sizeAttenuation: true
      })
      var pts = new THREE.Points(pg, pm)
      root.add(pts)
      nodeLayers.push(pts)

      /* 外层大光晕点（制造 bloom 感） */
      var pg2 = new THREE.BufferGeometry()
      pg2.setAttribute('position', new THREE.Float32BufferAttribute(nodePos, 3))
      pg2.setAttribute('color', new THREE.Float32BufferAttribute(nodeCol, 3))
      var pm2 = new THREE.PointsMaterial({
        size: 5.2, map: tex, vertexColors: true, transparent: true,
        opacity: 0.16, blending: THREE.AdditiveBlending, depthWrite: false,
        sizeAttenuation: true
      })
      var pts2 = new THREE.Points(pg2, pm2)
      root.add(pts2)
      nodeLayers.push(pts2)

      /* 放射线：花心 → 每个节点 */
      var lpos = [], lcol = []
      for (var j = 0; j < n; j++) {
        lpos.push(c.x, c.y, c.z, nodePos[j * 3], nodePos[j * 3 + 1], nodePos[j * 3 + 2])
        lcol.push(col.r * 0.85, col.g * 0.85, col.b * 0.85)
        lcol.push(col.r, col.g, col.b)
      }
      /* 节点之间的近邻线：Fibonacci 顺序上连下一个，形成球面网格 */
      for (var q = 0; q < n && n >= 8; q += 2) {
        var r2 = (q + 2) % n
        lpos.push(nodePos[q * 3], nodePos[q * 3 + 1], nodePos[q * 3 + 2],
                  nodePos[r2 * 3], nodePos[r2 * 3 + 1], nodePos[r2 * 3 + 2])
        lcol.push(col.r * 0.55, col.g * 0.55, col.b * 0.55)
        lcol.push(col.r * 0.55, col.g * 0.55, col.b * 0.55)
      }
      var lg = new THREE.BufferGeometry()
      lg.setAttribute('position', new THREE.Float32BufferAttribute(lpos, 3))
      lg.setAttribute('color', new THREE.Float32BufferAttribute(lcol, 3))
      var lines = new THREE.LineSegments(lg, lineMat())
      root.add(lines)
      lineGroups.push(lines)

      /* 花心：核 + 大光晕 */
      var core = new THREE.Sprite(new THREE.SpriteMaterial({
        map: tex, color: new THREE.Color(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255),
        transparent: true, opacity: 0.95, blending: THREE.AdditiveBlending, depthWrite: false
      }))
      core.position.copy(c)
      core.scale.setScalar(3.2 + Math.min(6, n * 0.05))
      root.add(core)

      var halo = new THREE.Sprite(new THREE.SpriteMaterial({
        map: tex, color: new THREE.Color(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255),
        transparent: true, opacity: 0.22, blending: THREE.AdditiveBlending, depthWrite: false
      }))
      halo.position.copy(c)
      halo.scale.setScalar(16 + Math.min(14, n * 0.16))
      root.add(halo)
      centersGroup.push(core, halo)
    })

    /* ── 跨类型连线：同一个 tag 落在多个类型里 → 两个花心之间连一根 ──
       完全由真实 tags 驱动：一条线只代表「这批记忆共享这个词」。 */
    var tagKinds = {}
    items.forEach(function (m) {
      String(m.tags || '').split(',').forEach(function (t) {
        t = t.trim()
        if (!t) return
        ;(tagKinds[t] = tagKinds[t] || {})[m.kind] = 1
      })
    })
    var tagPos = [], tagCol = []
    Object.keys(tagKinds).forEach(function (t) {
      var ks = Object.keys(tagKinds[t]).filter(function (k) { return centers[k] })
      if (ks.length < 2) return
      var a = centers[ks[0]], b = centers[ks[1]]
      tagPos.push(a.x, a.y, a.z, b.x, b.y, b.z)
      var bright = Math.min(0.95, 0.3 + Object.keys(tagKinds[t]).length * 0.12)
      tagCol.push(0.45 * bright, 1.0 * bright, 0.72 * bright,
                  0.45 * bright, 1.0 * bright, 0.72 * bright)
    })
    if (tagPos.length) {
      var tg = new THREE.BufferGeometry()
      tg.setAttribute('position', new THREE.Float32BufferAttribute(tagPos, 3))
      tg.setAttribute('color', new THREE.Float32BufferAttribute(tagCol, 3))
      var tlines = new THREE.LineSegments(tg, new THREE.LineBasicMaterial({
        vertexColors: true, transparent: true, opacity: 0.26,
        blending: THREE.AdditiveBlending, depthWrite: false
      }))
      root.add(tlines)
      lineGroups.push(tlines)
    }

    /* ── 外围星尘：每条记忆一个长期层点，亮度 = activation ── */
    var dustPos = [], dustCol = []
    var DUST_R = 62
    items.forEach(function (m, i) {
      var p = spherePoint(i * 2 + 1, items.length * 2, DUST_R * (0.9 + Math.random() * 0.22))
      var a = Math.max(0.25, Math.min(1, m.activation || 0.5))
      var base = hexToRgb(colorOf(m.kind) || '#ffffff')
      dustPos.push(p.x, p.y * 0.62, p.z)
      dustCol.push(base[0] / 255 * a, base[1] / 255 * a, base[2] / 255 * a)
    })
    var dg = new THREE.BufferGeometry()
    dg.setAttribute('position', new THREE.Float32BufferAttribute(dustPos, 3))
    dg.setAttribute('color', new THREE.Float32BufferAttribute(dustCol, 3))
    var dust = new THREE.Points(dg, new THREE.PointsMaterial({
      size: 1.1, map: tex, vertexColors: true, transparent: true, opacity: 0.55,
      blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true
    }))
    root.add(dust)

    /* ── 交互：拖拽旋转 / 滚轮缩放 / 点击拾取 ─────────────── */
    var dragging = false, autoSpin = true
    var lastX = 0, lastY = 0, downX = 0, downY = 0
    var el = renderer.domElement

    function onDown(e) {
      dragging = true; autoSpin = false
      lastX = e.clientX; lastY = e.clientY; downX = e.clientX; downY = e.clientY
      el.style.cursor = 'grabbing'
    }
    function onMove(e) {
      if (!dragging) return
      var dx = e.clientX - lastX, dy = e.clientY - lastY
      lastX = e.clientX; lastY = e.clientY
      camTheta -= dx * 0.005
      camPhi = Math.max(0.25, Math.min(Math.PI - 0.25, camPhi - dy * 0.005))
    }
    function onUp() { dragging = false; el.style.cursor = 'grab' }
    function onWheel(e) {
      e.preventDefault()
      autoSpin = false
      camDist = Math.max(28, Math.min(180, camDist * (1 + Math.sign(e.deltaY) * 0.09)))
    }
    el.addEventListener('pointerdown', onDown)
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    el.addEventListener('wheel', onWheel, { passive: false })

    /* 点击拾取：投影到屏幕后找最近的点 */
    var raycaster = new THREE.Raycaster()
    var ndc = new THREE.Vector2()
    function onClick(e) {
      if (Math.abs(e.clientX - downX) > 4 || Math.abs(e.clientY - downY) > 4) return
      var rect = el.getBoundingClientRect()
      ndc.x = ((e.clientX - rect.left) / rect.width) * 2 - 1
      ndc.y = -((e.clientY - rect.top) / rect.height) * 2 + 1
      raycaster.setFromCamera(ndc, camera)
      var best = null, bestD = 1e9
      var v = new THREE.Vector3()
      pickable.forEach(function (p) {
        v.set(p.x, p.y, p.z).project(camera)
        if (v.z > 1) return
        var sx = (v.x + 1) / 2 * rect.width
        var sy = (-v.y + 1) / 2 * rect.height
        var d = Math.hypot(sx - (e.clientX - rect.left), sy - (e.clientY - rect.top))
        if (d < bestD) { bestD = d; best = p }
      })
      if (best && bestD < 22 && onPick) onPick(best.mem)
    }
    el.addEventListener('click', onClick)

    /* ── 渲染循环 ─────────────────────────────────────────── */
    var raf = 0
    var t0 = performance.now()
    function frame() {
      raf = requestAnimationFrame(frame)
      var t = (performance.now() - t0) / 1000
      if (autoSpin) camTheta += 0.0011

      camera.position.set(
        camDist * Math.sin(camPhi) * Math.cos(camTheta),
        camDist * Math.cos(camPhi),
        camDist * Math.sin(camPhi) * Math.sin(camTheta)
      )
      camera.lookAt(0, 0, 0)

      /* 花心轻微呼吸 + 节点层各自慢转 */
      centersGroup.forEach(function (o, i) {
        var k = 1 + Math.sin(t * 1.4 + i) * 0.05
        o.scale.setScalar(o.userData.base || (o.scale.x / k))
        o.userData.base = o.scale.x / k
      })
      nodeLayers.forEach(function (p, i) {
        p.rotation.y = t * (i % 2 ? -0.03 : 0.03)
      })
      root.rotation.y = Math.sin(t * 0.12) * 0.06

      renderer.render(scene, camera)
    }
    frame()

    function onResize() {
      var w = container.clientWidth || W, h = container.clientHeight || H
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      renderer.setSize(w, h)
    }
    window.addEventListener('resize', onResize)

    return {
      dispose: function () {
        cancelAnimationFrame(raf)
        window.removeEventListener('pointermove', onMove)
        window.removeEventListener('pointerup', onUp)
        window.removeEventListener('resize', onResize)
        el.removeEventListener('pointerdown', onDown)
        el.removeEventListener('wheel', onWheel)
        el.removeEventListener('click', onClick)
        lineGroups.forEach(function (l) { l.geometry.dispose(); l.material.dispose() })
        nodeLayers.forEach(function (p) { p.geometry.dispose(); p.material.dispose() })
        centersGroup.forEach(function (o) { o.material.dispose() })
        dust.geometry.dispose()
        dust.material.dispose()
        tex.dispose()
        renderer.dispose()
        if (el.parentNode) el.parentNode.removeChild(el)
      }
    }
  }

  window.DSHGraph = { create: create }
})()