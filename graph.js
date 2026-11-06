/* 关系图谱视图 —— 外层戴森球包裹，每条记忆一条连线
 *
 * 映射规则（可视化必须对应真实数据）：
 *   · 一条记忆 = 内层一个光点（落在所属类型的花上）+ 外层球壳一个光点
 *   · 内外两层之间那根线 = 「同一条记忆的两层投影」，143 条记忆 = 143 根放射缆
 *   · 一朵花 = 一个记忆类型；花心亮度跟条数走；每朵花各自自转
 *   · 球壳网格 = 相邻记忆之间的近邻关系（Fibonacci 排序相邻）
 *   · 位置/大小跟 importance 走，亮度跟 activation 走
 * 零外部依赖，只用本地 three.js。
 */
(function () {
  'use strict'

  var KIND_ORDER = ['decision', 'pitfall', 'preference', 'context', 'todo']
  var FALLBACK = {
    decision: '#4dd0e1', pitfall: '#ff8a65', preference: '#c792ea',
    context: '#9ccc65', todo: '#ffd54f'
  }
  var SHELL_R = 58
  var SPIN = {
    decision: 0.055, pitfall: -0.042, preference: 0.075,
    context: -0.065, todo: 0.09
  }

  function hexToRgb(h) {
    var s = String(h || '').replace('#', '')
    if (s.length === 3) s = s[0] + s[0] + s[1] + s[1] + s[2] + s[2]
    var n = parseInt(s, 16)
    if (!isFinite(n)) return [150, 170, 190]
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
  }

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

  /* Fibonacci 球面：均匀撒点，索引稳定（同一条记忆永远落同一位置） */
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
    var camera = new THREE.PerspectiveCamera(50, W / H, 0.1, 900)
    var camDist = 152, camTheta = 0.7, camPhi = 1.08

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
    renderer.domElement.style.background = '#03060c'
    renderer.domElement.addEventListener('webglcontextlost', function (e) {
      e.preventDefault()
      container.innerHTML = '<div style="padding:24px;color:#e8b45a;font-size:13px;line-height:1.9">' +
        'GPU 上下文丢了（显存吃紧或驱动重置）。切到别的视图再切回来即可重建。</div>'
    })

    var root = new THREE.Group()
    scene.add(root)
    var tex = glowTexture()

    function colorOf(k) {
      return (colorMap && colorMap[k]) || FALLBACK[k] || '#9aa7b4'
    }
    function rgbOf(k) {
      var c = hexToRgb(colorOf(k))
      return [c[0] / 255, c[1] / 255, c[2] / 255]
    }

    /* ── 分桶 ─────────────────────────────────────────────── */
    var buckets = {}
    items.forEach(function (m) {
      var k = KIND_ORDER.indexOf(m.kind) >= 0 ? m.kind : 'context'
      ;(buckets[k] = buckets[k] || []).push(m)
    })
    var kinds = KIND_ORDER.filter(function (k) { return buckets[k] && buckets[k].length })

    /* 花心摆位：比球壳小很多，保证被完全包裹 */
    var MAXR = kinds.length > 1 ? 15 : 0
    var total = items.length || 1
    var centers = {}
    kinds.forEach(function (k, i) {
      var ang = (i / kinds.length) * Math.PI * 2 + 0.4
      var share = buckets[k].length / total
      centers[k] = new THREE.Vector3(
        Math.cos(ang) * MAXR * (0.55 + share * 1.6),
        Math.sin(i * 1.7) * 2,
        Math.sin(ang) * MAXR * (0.55 + share * 1.6)
      )
    })

    var lineMats = []
    function lineMat(op) {
      var m = new THREE.LineBasicMaterial({
        vertexColors: true, transparent: true, opacity: op,
        blending: THREE.AdditiveBlending, depthWrite: false
      })
      lineMats.push(m)
      return m
    }

    var flowers = []
    var pickables = []
    var nodeOf = {}

    /* ── 内层：每类一朵花（各自自转） ─────────────────────── */
    kinds.forEach(function (kind) {
      var list = buckets[kind]
      var rgb = rgbOf(kind)
      var col = new THREE.Color(rgb[0], rgb[1], rgb[2])
      var n = list.length
      var radius = 9 + Math.min(8, n * 0.1)

      var grp = new THREE.Group()
      grp.position.copy(centers[kind])
      root.add(grp)

      var nodePos = [], nodeCol = []
      for (var i = 0; i < n; i++) {
        var p = spherePoint(i, n, radius)
        var imp = Math.max(0.2, Math.min(1, list[i].importance || 0.5))
        var s = radius * (1 - imp * 0.35)
        var lx = p.x * (s / radius), ly = p.y * (s / radius), lz = p.z * (s / radius)
        nodePos.push(lx, ly, lz)
        nodeCol.push(col.r, col.g, col.b)

        var w = centers[kind].clone()
        w.x += lx; w.y += ly; w.z += lz
        nodeOf[list[i].id] = { x: w.x, y: w.y, z: w.z }
        pickables.push({ grp: grp, local: new THREE.Vector3(lx, ly, lz), mem: list[i] })

        var ux = p.x / radius, uy = p.y / radius, uz = p.z / radius
        nodePos.push(lx + ux * 0.9, ly + uy * 0.9, lz + uz * 0.9)
        nodeCol.push(col.r * 0.24, col.g * 0.24, col.b * 0.24)
        nodePos.push(lx + ux * 2.0, ly + uy * 2.0, lz + uz * 2.0)
        nodeCol.push(col.r * 0.06, col.g * 0.06, col.b * 0.06)
      }

      var pg = new THREE.BufferGeometry()
      pg.setAttribute('position', new THREE.Float32BufferAttribute(nodePos, 3))
      pg.setAttribute('color', new THREE.Float32BufferAttribute(nodeCol, 3))
      grp.add(new THREE.Points(pg, new THREE.PointsMaterial({
        size: 1.8, map: tex, vertexColors: true, transparent: true,
        opacity: 0.92, blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true
      })))

      var pg2 = new THREE.BufferGeometry()
      pg2.setAttribute('position', new THREE.Float32BufferAttribute(nodePos, 3))
      pg2.setAttribute('color', new THREE.Float32BufferAttribute(nodeCol, 3))
      grp.add(new THREE.Points(pg2, new THREE.PointsMaterial({
        size: 3.4, map: tex, vertexColors: true, transparent: true,
        opacity: 0.06, blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true
      })))

      var lpos = [], lcol = []
      var dim = 0.42
      function link(a, b) {
        if (a === b) return
        lpos.push(nodePos[a * 3], nodePos[a * 3 + 1], nodePos[a * 3 + 2],
                  nodePos[b * 3], nodePos[b * 3 + 1], nodePos[b * 3 + 2])
        lcol.push(col.r * dim, col.g * dim, col.b * dim)
        lcol.push(col.r * dim, col.g * dim, col.b * dim)
      }
      for (var j = 0; j < n; j++) {
        lpos.push(0, 0, 0, nodePos[j * 3], nodePos[j * 3 + 1], nodePos[j * 3 + 2])
        lcol.push(col.r * 0.8, col.g * 0.8, col.b * 0.8)
        lcol.push(col.r, col.g, col.b)
      }
      if (n >= 4) {
        var seenL = {}
        function linkOnce(a, b) {
          var key = a < b ? a + '_' + b : b + '_' + a
          if (seenL[key]) return
          seenL[key] = 1
          link(a, b)
        }
        // 每点连最近的 5 个邻居（球面局部坐标里算），比索引相邻更像网
        var KN2 = n > 40 ? 3 : 2
        for (var q = 0; q < n; q++) {
          var cand = []
          for (var w2 = 0; w2 < n; w2++) {
            if (w2 === q) continue
            var dx2 = nodePos[q * 3] - nodePos[w2 * 3]
            var dy2 = nodePos[q * 3 + 1] - nodePos[w2 * 3 + 1]
            var dz2 = nodePos[q * 3 + 2] - nodePos[w2 * 3 + 2]
            cand.push([dx2 * dx2 + dy2 * dy2 + dz2 * dz2, w2])
          }
          cand.sort(function (x, y) { return x[0] - y[0] })
          for (var k2 = 0; k2 < Math.min(KN2, cand.length); k2++) linkOnce(q, cand[k2][1])
          linkOnce(q, (q + 1) % n)   // 索引相邻再补一条
        }
      }
      var lg = new THREE.BufferGeometry()
      lg.setAttribute('position', new THREE.Float32BufferAttribute(lpos, 3))
      lg.setAttribute('color', new THREE.Float32BufferAttribute(lcol, 3))
      grp.add(new THREE.LineSegments(lg, lineMat(0.085)))

      var core = new THREE.Sprite(new THREE.SpriteMaterial({
        map: tex, color: new THREE.Color(rgb[0], rgb[1], rgb[2]),
        transparent: true, opacity: 0.8, blending: THREE.AdditiveBlending, depthWrite: false
      }))
      core.scale.setScalar(3.0 + Math.min(5, n * 0.05))
      grp.add(core)

      var halo = new THREE.Sprite(new THREE.SpriteMaterial({
        map: tex, color: new THREE.Color(rgb[0], rgb[1], rgb[2]),
        transparent: true, opacity: 0.06, blending: THREE.AdditiveBlending, depthWrite: false
      }))
      halo.scale.setScalar(7 + Math.min(4, n * 0.05))
      grp.add(halo)

      flowers.push({ grp: grp, speed: SPIN[kind] || 0.05, kind: kind })
    })

    /* ── 外层戴森球：每条记忆一个点 + 相邻织网 ───────────── */
    var shellPos = [], shellCol = [], shellW = []
    items.forEach(function (m, i) {
      var imp = Math.max(0.2, Math.min(1, m.importance || 0.5))
      var act = Math.max(0.3, Math.min(1, m.activation || 0.7))
      var r = SHELL_R + (1 - imp) * 9
      var p = spherePoint(i, items.length, r)
      var rgb = rgbOf(m.kind)
      shellPos.push(p.x, p.y, p.z)
      shellCol.push(rgb[0] * act * 0.55, rgb[1] * act * 0.55, rgb[2] * act * 0.55)
      shellW.push({ x: p.x, y: p.y, z: p.z, rgb: rgb, kind: m.kind })
      pickables.push({ grp: null, local: new THREE.Vector3(p.x, p.y, p.z), mem: m })
    })

    var sGeo = new THREE.BufferGeometry()
    sGeo.setAttribute('position', new THREE.Float32BufferAttribute(shellPos, 3))
    sGeo.setAttribute('color', new THREE.Float32BufferAttribute(shellCol, 3))
    var shellPts = new THREE.Points(sGeo, new THREE.PointsMaterial({
      size: 2.0, map: tex, vertexColors: true, transparent: true,
      opacity: 1.0, blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true
    }))
    root.add(shellPts)

    // 球壳点再叠一层柔光，让每个点都「发亮」
    var sGlowGeo = new THREE.BufferGeometry()
    sGlowGeo.setAttribute('position', new THREE.Float32BufferAttribute(shellPos, 3))
    sGlowGeo.setAttribute('color', new THREE.Float32BufferAttribute(shellCol, 3))
    root.add(new THREE.Points(sGlowGeo, new THREE.PointsMaterial({
      size: 5.2, map: tex, vertexColors: true, transparent: true,
      opacity: 0.10, blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true
    })))

    var gl = [], gc = []
    var seenEdge = {}
    function shellLink(a, b) {
      var A = shellW[a], B = shellW[b]
      if (!A || !B) return
      var key = (a < b ? a + '-' + b : b + '-' + a)
      if (seenEdge[key]) return
      seenEdge[key] = 1
      gl.push(A.x, A.y, A.z, B.x, B.y, B.z)
      gc.push(A.rgb[0] * 0.42, A.rgb[1] * 0.42, A.rgb[2] * 0.42)
      gc.push(B.rgb[0] * 0.42, B.rgb[1] * 0.42, B.rgb[2] * 0.42)
    }
    var N = items.length
    // 每个球壳点连最近的 K 个邻居 → 一层真正的网格壳
    var KN = N > 90 ? 9 : 5
    for (var si = 0; si < N; si++) {
      var near = []
      for (var sj = 0; sj < N; sj++) {
        if (sj === si) continue
        var A2 = shellW[si], B2 = shellW[sj]
        var dx = A2.x - B2.x, dy = A2.y - B2.y, dz = A2.z - B2.z
        near.push([dx * dx + dy * dy + dz * dz, sj])
      }
      near.sort(function (x, y) { return x[0] - y[0] })
      for (var kk = 0; kk < Math.min(KN, near.length); kk++) shellLink(si, near[kk][1])
      // 再补一圈索引相邻：Fibonacci 序列本身是螺旋，这条能把「经线」方向也串起来
      shellLink(si, (si + 1) % N)
    }
    var sLines = new THREE.BufferGeometry()
    sLines.setAttribute('position', new THREE.Float32BufferAttribute(gl, 3))
    sLines.setAttribute('color', new THREE.Float32BufferAttribute(gc, 3))
    root.add(new THREE.LineSegments(sLines, lineMat(0.145)))

    /* 球体轮廓：三条大圆，让「球壳」有个看得见的边 */
    function bigCircle(plane, radius, opacity) {
      var pts = []
      for (var i = 0; i <= 160; i++) {
        var a = i / 160 * Math.PI * 2
        if (plane === 'xz') pts.push(new THREE.Vector3(Math.cos(a) * radius, 0, Math.sin(a) * radius))
        else if (plane === 'xy') pts.push(new THREE.Vector3(Math.cos(a) * radius, Math.sin(a) * radius, 0))
        else pts.push(new THREE.Vector3(0, Math.cos(a) * radius, Math.sin(a) * radius))
      }
      var g = new THREE.BufferGeometry().setFromPoints(pts)
      return new THREE.Line(g, new THREE.LineBasicMaterial({
        color: 0x4dd0e1, transparent: true, opacity: opacity,
        blending: THREE.AdditiveBlending, depthWrite: false
      }))
    }
    var ringMat = bigCircle('xz', SHELL_R + 4, 0.16)
    root.add(ringMat)
    root.add(bigCircle('xy', SHELL_R + 4, 0.09))
    root.add(bigCircle('yz', SHELL_R + 4, 0.09))

    /* 内外连线：球壳点 → 这条记忆自己在花里的那个点（不是都拉到花心，
       这样 143 条缆线是散开的，不会汇成一个漏斗）。挂进花 group 里跟着转。 */
    var flowerByKind = {}
    flowers.forEach(function (f) { flowerByKind[f.kind] = f })
    var byKindIdx = {}
    items.forEach(function (m, i) { (byKindIdx[m.kind] = byKindIdx[m.kind] || []).push(i) })
    Object.keys(byKindIdx).forEach(function (kind) {
      var f = flowerByKind[kind]
      if (!f) return
      var c = centers[kind]
      var lp = [], lc = []
      byKindIdx[kind].forEach(function (idx) {
        var w = shellW[idx]
        var mem = items[idx]
        var nd = nodeOf[mem.id]
        if (!w || !nd) return
        lp.push(w.x - c.x, w.y - c.y, w.z - c.z)
        lp.push(nd.x - c.x, nd.y - c.y, nd.z - c.z)
        var rgb = w.rgb
        lc.push(rgb[0] * 0.55, rgb[1] * 0.55, rgb[2] * 0.55)
        lc.push(rgb[0] * 0.28, rgb[1] * 0.28, rgb[2] * 0.28)
      })
      if (!lp.length) return
      var g2 = new THREE.BufferGeometry()
      g2.setAttribute('position', new THREE.Float32BufferAttribute(lp, 3))
      g2.setAttribute('color', new THREE.Float32BufferAttribute(lc, 3))
      f.grp.add(new THREE.LineSegments(g2, lineMat(0.11)))
    })

    /* 同 tag 的记忆之间再串一层（真实关联） */
    var tagMems = {}
    items.forEach(function (m) {
      String(m.tags || '').split(',').forEach(function (tg) {
        tg = tg.trim()
        if (!tg) return
        ;(tagMems[tg] = tagMems[tg] || []).push(m)
      })
    })
    var tl = [], tc = []
    Object.keys(tagMems).forEach(function (tg) {
      var ms = tagMems[tg].filter(function (m) { return nodeOf[m.id] })
      if (ms.length < 2) return
      var lim = Math.min(ms.length, 6)
      for (var i = 0; i < lim; i++) {
        var A = nodeOf[ms[i].id], B = nodeOf[ms[(i + 1) % lim].id]
        tl.push(A.x, A.y, A.z, B.x, B.y, B.z)
        var br = Math.min(1, 0.45 + ms.length * 0.06)
        tc.push(0.40 * br, 0.92 * br, 0.66 * br, 0.40 * br, 0.92 * br, 0.66 * br)
      }
    })
    if (tl.length) {
      var tGeo = new THREE.BufferGeometry()
      tGeo.setAttribute('position', new THREE.Float32BufferAttribute(tl, 3))
      tGeo.setAttribute('color', new THREE.Float32BufferAttribute(tc, 3))
      root.add(new THREE.LineSegments(tGeo, lineMat(0.10)))
    }

    /* ── 交互 ─────────────────────────────────────────────── */
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
      e.preventDefault(); autoSpin = false
      camDist = Math.max(45, Math.min(260, camDist * (1 + Math.sign(e.deltaY) * 0.09)))
    }
    el.addEventListener('pointerdown', onDown)
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    el.addEventListener('wheel', onWheel, { passive: false })

    var ndc = new THREE.Vector2()
    function onClick(e) {
      if (Math.abs(e.clientX - downX) > 4 || Math.abs(e.clientY - downY) > 4) return
      var rect = el.getBoundingClientRect()
      ndc.x = ((e.clientX - rect.left) / rect.width) * 2 - 1
      ndc.y = -((e.clientY - rect.top) / rect.height) * 2 + 1
      var best = null, bestD = 1e9
      var v = new THREE.Vector3()
      pickables.forEach(function (pp) {
        v.copy(pp.local)
        if (pp.grp) { v.applyMatrix4(pp.grp.matrixWorld) }
        v.project(camera)
        if (v.z > 1) return
        var sx = (v.x + 1) / 2 * rect.width
        var sy = (-v.y + 1) / 2 * rect.height
        var d = Math.hypot(sx - (e.clientX - rect.left), sy - (e.clientY - rect.top))
        if (d < bestD) { bestD = d; best = pp }
      })
      if (best && bestD < 26 && onPick) onPick(best.mem)
    }
    el.addEventListener('click', onClick)

    /* 悬停：靠近任一光点时光标变手型，让「这个点能点」有反馈 */
    var hv = new THREE.Vector3()
    el.addEventListener('mousemove', function (e) {
      if (dragging) return
      var rect = el.getBoundingClientRect()
      var bestD = 1e9
      pickables.forEach(function (pp) {
        hv.copy(pp.local)
        if (pp.grp) hv.applyMatrix4(pp.grp.matrixWorld)
        hv.project(camera)
        if (hv.z > 1) return
        var sx = (hv.x + 1) / 2 * rect.width
        var sy = (-hv.y + 1) / 2 * rect.height
        var d = Math.hypot(sx - (e.clientX - rect.left), sy - (e.clientY - rect.top))
        if (d < bestD) bestD = d
      })
      el.style.cursor = bestD < 26 ? 'pointer' : (dragging ? 'grabbing' : 'grab')
    })

    /* ── 渲染 ─────────────────────────────────────────────── */
    var raf = 0
    var t0 = performance.now()
    function frame() {
      raf = requestAnimationFrame(frame)
      var t = (performance.now() - t0) / 1000
      if (autoSpin) camTheta += 0.0009

      camera.position.set(
        camDist * Math.sin(camPhi) * Math.cos(camTheta),
        camDist * Math.cos(camPhi),
        camDist * Math.sin(camPhi) * Math.sin(camTheta)
      )
      camera.lookAt(0, 0, 0)

      // 每朵花各转各的（速度不同、方向不同）
      for (var i = 0; i < flowers.length; i++) {
        flowers[i].grp.rotation.y = t * flowers[i].speed
        flowers[i].grp.rotation.x = Math.sin(t * 0.25 + i) * 0.06
      }
      // 球壳极慢反向自转，做出「包裹」的层次
      shellPts.rotation.y = -t * 0.008

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
        scene.traverse(function (o) {
          if (o.geometry) o.geometry.dispose()
          if (o.material) {
            if (Array.isArray(o.material)) o.material.forEach(function (mm) { mm.dispose() })
            else o.material.dispose()
          }
        })
        tex.dispose()
        renderer.dispose()
        if (el.parentNode) el.parentNode.removeChild(el)
      }
    }
  }

  window.DSHGraph = { create: create }
})()