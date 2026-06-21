// 独立验证 Moore-Neighbor 轮廓追踪算法
// 模拟 Annotator.vue scanContour() 在 S/U/L/直线/圆 形 mask 上的行为

function trace(mask, cw, ch) {
  let sx = -1, sy = -1
  for (let y = 0; y < ch && sx < 0; y++) for (let x = 0; x < cw; x++) if (mask[y*cw+x]) { sx = x; sy = y; break }
  if (sx < 0) return []
  const dxs = [1,1,0,-1,-1,-1,0,1], dys = [0,1,1,1,0,-1,-1,-1]
  const path = [{x:sx, y:sy}]
  let cx = sx, cy = sy, prev = 6
  const maxIter = cw*ch*4
  for (let it = 0; it < maxIter; it++) {
    let nd = -1
    for (let i = 1; i <= 8; i++) {
      const d = (prev+i)%8
      const nx = cx+dxs[d], ny = cy+dys[d]
      if (nx<0||nx>=cw||ny<0||ny>=ch) continue
      if (mask[ny*cw+nx]) { nd = d; cx = nx; cy = ny; break }
    }
    if (nd < 0) break
    if (cx === sx && cy === sy) break
    path.push({x:cx, y:cy})
    prev = (nd+4)%8
  }
  return path
}

// 在 mask 上画线（Bresenham），同时膨胀 r（模拟笔刷 round cap）
function drawLine(m, cw, ch, x0, y0, x1, y1, r) {
  const dx = Math.abs(x1-x0), dy = Math.abs(y1-y0)
  const sx = x0<x1?1:-1, sy = y0<y1?1:-1
  let err = dx-dy, x = x0, y = y0
  while (true) {
    for (let dy2 = -r; dy2 <= r; dy2++) for (let dx2 = -r; dx2 <= r; dx2++) {
      if (dx2*dx2+dy2*dy2 <= r*r) {
        const nx = x+dx2, ny = y+dy2
        if (nx>=0&&nx<cw&&ny>=0&&ny<ch) m[ny*cw+nx] = 1
      }
    }
    if (x === x1 && y === y1) break
    const e2 = 2*err
    if (e2 > -dy) { err -= dy; x += sx }
    if (e2 < dx) { err += dx; y += sy }
  }
}

function drawPath(m, cw, ch, pts, r) {
  if (pts.length === 1) { drawLine(m, cw, ch, pts[0][0], pts[0][1], pts[0][0], pts[0][1], r); return }
  for (let i = 1; i < pts.length; i++) drawLine(m, cw, ch, pts[i-1][0], pts[i-1][1], pts[i][0], pts[i][1], r)
}

function renderAscii(mask, cw, ch, polygon) {
  // polygon 边界点用 '#'，mask 内部用 '.'，背景空格
  const polyset = new Set(polygon.map(p => p.y*cw+p.x))
  const lines = []
  for (let y = 0; y < ch; y++) {
    let line = ''
    for (let x = 0; x < cw; x++) {
      if (polyset.has(y*cw+x)) line += '#'
      else if (mask[y*cw+x]) line += '.'
      else line += ' '
    }
    lines.push(line)
  }
  return lines.join('\n')
}

function testCase(name, drawFn, cw = 60, ch = 30) {
  const m = new Uint8Array(cw*ch)
  drawFn(m, cw, ch)
  const path = trace(m, cw, ch)
  // 用 polygon 重新填充 mask，检查"填充区域" vs 原 mask
  const filled = polyFill(path, cw, ch)
  let mPixels = 0, fPixels = 0, extra = 0
  for (let i = 0; i < cw*ch; i++) {
    if (m[i]) mPixels++
    if (filled[i]) fPixels++
    if (filled[i] && !m[i]) extra++
  }
  console.log(`\n=== ${name} ===`)
  console.log(`mask pixels: ${mPixels}, polygon points: ${path.length}, polygon fill: ${fPixels} (over-fill: ${extra} = ${(extra*100/mPixels).toFixed(1)}%)`)
  console.log(renderAscii(m, cw, ch, path))
}

function polyFill(path, cw, ch) {
  // 简单点-in-polygon 填充（射线法），用 mask 输出
  const out = new Uint8Array(cw*ch)
  if (path.length < 3) return out
  for (let y = 0; y < ch; y++) {
    for (let x = 0; x < cw; x++) {
      let inside = false
      for (let i = 0, j = path.length-1; i < path.length; j = i++) {
        const xi = path[i].x, yi = path[i].y
        const xj = path[j].x, yj = path[j].y
        if (((yi>y)!==(yj>y)) && (x < (xj-xi)*(y-yi)/(yj-yi)+xi)) inside = !inside
      }
      if (inside) out[y*cw+x] = 1
    }
  }
  return out
}

// === 测试用例 ===
testCase('直线（横向）', (m, cw, ch) => {
  drawPath(m, cw, ch, [[5,15],[55,15]], 3)
})

testCase('圆团', (m, cw, ch) => {
  drawPath(m, cw, ch, [[30,15]], 8)
})

testCase('L 形', (m, cw, ch) => {
  drawPath(m, cw, ch, [[10,5],[10,25],[50,25]], 3)
})

testCase('U 形', (m, cw, ch) => {
  drawPath(m, cw, ch, [[10,5],[10,25],[50,25],[50,5]], 3)
})

testCase('S 形（关键 bug 用例）', (m, cw, ch) => {
  drawPath(m, cw, ch, [[10,5],[50,5],[50,15],[10,15],[10,25],[50,25]], 3)
})

testCase('C 形', (m, cw, ch) => {
  drawPath(m, cw, ch, [[50,5],[10,5],[10,25],[50,25]], 3)
})
