/* 记忆编年环 —— 第五种记忆视图
 *
 * 映射规则（可视化必须对应真实数据）：
 *   · 一圈 = 一天，由内向外按日期推进（内圈最早，外圈最新）
 *   · 一个光点 = 一条真实记忆，角度 = 该天内的排布位置，亮度/大小 = importance
 *   · 颜色 = 记忆类型（跟随主题的 --kind-*）
 *   · 一根细线 = 两条记忆共享同一个 tag（跨天也能连）
 *   · 底部数字：总条数 / 天数 / 单日峰值 / 最近一天
 * 纯 2D Canvas，零依赖、零 token、不联网。
 */
(function () {
  'use strict'

  var KIND_ORDER = ['decision', 'pitfall', 'preference', 'context', 'todo']
  var FALLBACK = {
    decision: '#4dd0e1', pitfall: '#ff8a65', preference: '#c792ea',
    context: '#9ccc65', todo: '#ffd54f'
  }
  var TILT = 0.56          // 椭圆压扁比例（俯视 3D 感）
  var DAY_GAP = 34         // 相邻两天的半径差

  function hexToRgb(h) {
    var s = String(h || '').replace('#', '')
    if (s.length === 3) s = s[0] + s[0] + s[1] + s[1] + s[2] + s[2]
    var n = parseInt(s, 16)
    if (!isFinite(n)) return [150, 170, 190]
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
  }

  function create(container, items, onPick, colorMap) {
    var W = container.clientWidth || 900
    var H = container.clientHeight || 560

    var canvas = document.createElement('canvas')
    canvas.style.display = 'block'
    canvas.style.background = '#03060c'
    canvas.style.cursor = 'grab'
    container.appendChild(canvas)
    var ctx = canvas.getContext('2d')

    function colorOf(k) {
      return (colorMap && colorMap[k]) || FALLBACK[k] || '#9aa7b4'
    }

    /* ── 按天分桶 ─────────────────────────────────────────── */
    var byDay = {}
    items.forEach(function (m) {
      var d = String(m.created || '').slice(0, 10)
      if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) d = '未知日期'
      ;(byDay[d] = byDay[d] || []).push(m)
    })
    var days = Object.keys(byDay).sort()
    if (days.length === 1 && days[0] === '未知日期') days = ['未知日期']

    var maxCount = 1
    days.forEach(function (d) { maxCount = Math.max(maxCount, byDay[d].length) })

    /* 每个 tag 出现在哪些记忆里 —— 画跨圈连线用 */
    var tagMembers = {}
    items.forEach(function (m) {
      String(m.tags || '').split(',').forEach(function (t) {
        t = t.trim()
        if (!t) return
        ;(tagMembers[t] = tagMembers[t] || []).push(m.id)
      })
    })

    var idPos = {}       // mem.id -> {x, y, day, ang}
    var pickable = []
    var scale = 1
    var rot = 0
    var autoSpin = true
  /* 自动旋转的暂停与恢复：点击/拖动只是「暂时」停转，4 秒后自己回来 */
  var spinTimer = 0
  function pauseAutoSpin(ms) {
    autoSpin = false
    if (spinTimer) clearTimeout(spinTimer)
    spinTimer = setTimeout(function () { autoSpin = true }, ms || 4000)
  }

    var dragging = false
    var lastX = 0, downX = 0, downY = 0

    function resize() {
      W = container.clientWidth || W
      H = container.clientHeight || H
      var dpr = window.devicePixelRatio || 1
      canvas.width = Math.round(W * dpr)
      canvas.height = Math.round(H * dpr)
      canvas.style.width = W + 'px'
      canvas.style.height = H + 'px'
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    /* 半径按画布铺满：内圈 46px，外圈贴到边缘，天数少也不会缩成一小坨 */
    function dayRadius(di) {
      var maxR = Math.min(W, H * 1.45) / 2 - 30
      var inner = 96
      if (days.length <= 1) return inner
      var step = (maxR - inner) / (days.length - 1)
      return inner + di * step
    }

    function position(dayIdx, i, total) {
      var cx = W / 2, cy = H / 2
      var jitter = ((i % 5) - 2) * 7
      var r = dayRadius(dayIdx) * scale + jitter
      var ang = (i / Math.max(1, total)) * Math.PI * 2 + dayIdx * 0.6 + rot
      return {
        x: cx + Math.cos(ang) * r,
        y: cy + Math.sin(ang) * r * TILT,
        ang: ang
      }
    }

    function draw(hlId) {
      ctx.clearRect(0, 0, W, H)
      var cx = W / 2, cy = H / 2
      pickable = []

      /* 1) 日期圈 */
      days.forEach(function (d, di) {
        var r = dayRadius(di) * scale
        ctx.beginPath()
        ctx.ellipse(cx, cy, r, r * TILT, 0, 0, Math.PI * 2)
        var ratio = byDay[d].length / maxCount
        ctx.strokeStyle = 'rgba(90,200,250,' + (0.10 + ratio * 0.22) + ')'
        ctx.lineWidth = 1
        ctx.stroke()

        /* 日期标签：贴在圈的正上方（放左侧会挤成一坨） */
        ctx.fillStyle = 'rgba(150,175,200,.78)'
        ctx.font = '11px "Segoe UI",system-ui,sans-serif'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'bottom'
        ctx.fillText(d.slice(5), cx, cy - r * TILT - 3)
      })

      /* 2) 跨圈 tag 连线（先画，压在点下面） */
      ctx.lineWidth = 0.7
      Object.keys(tagMembers).forEach(function (t) {
        var ids = tagMembers[t]
        if (ids.length < 2 || ids.length > 12) return
        for (var i = 0; i < ids.length; i++) {
          var a = idPos[ids[i]], b = idPos[ids[(i + 1) % ids.length]]
          if (!a || !b) continue
          var ka = byDay[a.day] ? byDay[a.day][a.idx] : null
          var kb = byDay[b.day] ? byDay[b.day][b.idx] : null
          var ca = ka ? hexToRgb(colorOf(ka.kind)) : [120, 160, 190]
          ctx.strokeStyle = 'rgba(' + ca[0] + ',' + ca[1] + ',' + ca[2] + ',0.16)'
          ctx.beginPath()
          ctx.moveTo(a.x, a.y)
          ctx.lineTo(b.x, b.y)
          ctx.stroke()
        }
      })

      /* 3) 记忆光点 */
      days.forEach(function (d, di) {
        var list = byDay[d]
        list.forEach(function (m, i) {
          var p = position(di, i, list.length)
          var c = hexToRgb(colorOf(m.kind))
          var imp = Math.max(0.25, Math.min(1, m.importance || 0.5))
          var r = 1.1 + imp * 2.0
          var isHl = m.id === hlId

          /* 光晕 */
          var g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, r * 3.2)
          g.addColorStop(0, 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + (isHl ? 0.42 : 0.11) + ')')
          g.addColorStop(1, 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',0)')
          ctx.fillStyle = g
          ctx.beginPath()
          ctx.arc(p.x, p.y, r * 3.2, 0, Math.PI * 2)
          ctx.fill()

          /* 实心点 */
          ctx.fillStyle = 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ')'
          ctx.beginPath()
          ctx.arc(p.x, p.y, isHl ? r * 1.8 : r, 0, Math.PI * 2)
          ctx.fill()

          idPos[m.id] = { x: p.x, y: p.y, day: di, idx: i }
          pickable.push({ x: p.x, y: p.y, mem: m })
        })
      })

      /* 中心：总量（内圈留得够大，不会和点叠在一起） */
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillStyle = 'rgba(230,240,250,.92)'
      ctx.font = '600 26px "Segoe UI",system-ui,sans-serif'
      ctx.fillText(String(items.length), cx, cy - 4)
      ctx.fillStyle = 'rgba(150,170,190,.85)'
      ctx.font = '12px "Segoe UI",system-ui,sans-serif'
      ctx.fillText(days.length + ' 天 · 条记忆', cx, cy + 22)
    }

    /* ── 交互 ─────────────────────────────────────────────── */
    var raf = 0
    function loop() {
      raf = requestAnimationFrame(loop)
      if (autoSpin && !dragging) rot += 0.0016
      draw(hoverId)
    }

    var hoverId = null
    canvas.addEventListener('pointerdown', function (e) {
      dragging = true; pauseAutoSpin(6000)
      lastX = e.clientX; downX = e.clientX; downY = e.clientY
      canvas.style.cursor = 'grabbing'
    })
    function onMove(e) {
      if (dragging) {
        rot += (e.clientX - lastX) * 0.006
        lastX = e.clientX
        return
      }
      var rect = canvas.getBoundingClientRect()
      var mx = e.clientX - rect.left, my = e.clientY - rect.top
      var best = null, bestD = 1e9
      pickable.forEach(function (p) {
        var d = Math.hypot(p.x - mx, p.y - my)
        if (d < bestD) { bestD = d; best = p }
      })
      var nid = (best && bestD < 14) ? best.mem.id : null
      if (nid !== hoverId) { hoverId = nid; draw(hoverId) }
      canvas.style.cursor = nid ? 'pointer' : (dragging ? 'grabbing' : 'grab')
    }
    function onUp() { dragging = false; canvas.style.cursor = 'grab'; pauseAutoSpin(4000) }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    canvas.addEventListener('wheel', function (e) {
      e.preventDefault()
      pauseAutoSpin(4000)
      scale = Math.max(0.45, Math.min(3.2, scale * (1 + Math.sign(e.deltaY) * -0.1)))
    }, { passive: false })
    canvas.addEventListener('click', function (e) {
      if (Math.abs(e.clientX - downX) > 4 || Math.abs(e.clientY - downY) > 4) return
      var rect = canvas.getBoundingClientRect()
      var mx = e.clientX - rect.left, my = e.clientY - rect.top
      var best = null, bestD = 1e9
      pickable.forEach(function (p) {
        var d = Math.hypot(p.x - mx, p.y - my)
        if (d < bestD) { bestD = d; best = p }
      })
      if (best && bestD < 16 && onPick) onPick(best.mem)
    })

    window.addEventListener('resize', resize)
    resize()
    draw(null)
    loop()

    return {
      dispose: function () {
        cancelAnimationFrame(raf)
        window.removeEventListener('resize', resize)
        window.removeEventListener('pointermove', onMove)
        window.removeEventListener('pointerup', onUp)
        if (canvas.parentNode) canvas.parentNode.removeChild(canvas)
      }
    }
  }

  window.DSHChronicle = { create: create }
})()