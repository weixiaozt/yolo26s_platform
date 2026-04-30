// 单元测试：标注器关键纯逻辑（不依赖 fabric.js / 浏览器）
// 复制 Annotator.vue 中的逻辑，用 Node 跑断言验证。

// ====== sanitizePolygon ======
function sanitizePolygon(polygon) {
  const out = []
  for (const p of polygon) {
    const x = Math.max(0, Math.min(1, Number(p.x) || 0))
    const y = Math.max(0, Math.min(1, Number(p.y) || 0))
    const last = out[out.length - 1]
    if (!last || Math.abs(last.x - x) > 1e-6 || Math.abs(last.y - y) > 1e-6) {
      out.push({ x, y })
    }
  }
  return out
}

// ====== 矩形 → 4 点 polygon ======
function rectToPolygon(p1, p2, W, H) {
  const x1 = Math.min(p1.x, p2.x), y1 = Math.min(p1.y, p2.y)
  const x2 = Math.max(p1.x, p2.x), y2 = Math.max(p1.y, p2.y)
  return [
    { x: x1 / W, y: y1 / H },
    { x: x2 / W, y: y1 / H },
    { x: x2 / W, y: y2 / H },
    { x: x1 / W, y: y2 / H },
  ]
}

// ====== 复制粘贴（带偏移）======
function pasteWithOffset(clipboard, W, H) {
  const dx = 20 / W, dy = 20 / H
  return {
    class_id: clipboard.class_id,
    polygon: clipboard.polygon.map(p => ({
      x: Math.max(0, Math.min(1, p.x + dx)),
      y: Math.max(0, Math.min(1, p.y + dy)),
    })),
  }
}

let pass = 0, fail = 0
function ok(name, cond, detail = '') {
  if (cond) { pass++; console.log(`  [OK] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name} ${detail}`) }
}

console.log('=== sanitizePolygon ===')
{
  const sanitized = sanitizePolygon([
    { x: -0.1, y: 0.5 },
    { x: 0.5, y: -0.05 },
    { x: 1.1, y: 0.5 },
    { x: 0.5, y: 1.5 },
  ])
  ok('clamp 4 越界点', sanitized.length === 4)
  ok('左越界 x → 0', sanitized[0].x === 0, JSON.stringify(sanitized[0]))
  ok('上越界 y → 0', sanitized[1].y === 0)
  ok('右越界 x → 1', sanitized[2].x === 1)
  ok('下越界 y → 1', sanitized[3].y === 1)
}
{
  // 连续重复点去重
  const sanitized = sanitizePolygon([
    { x: 0.1, y: 0.1 },
    { x: 0.1, y: 0.1 }, // 完全相同
    { x: 0.5, y: 0.5 },
    { x: 0.5, y: 0.5 }, // 完全相同
  ])
  ok('连续重复点去重', sanitized.length === 2, `got ${sanitized.length}`)
}
{
  // 历史 VOC 数据典型场景 (-1px / 640px = -0.001563)
  const sanitized = sanitizePolygon([
    { x: -0.001563, y: 0.05 },
    { x: 0.05, y: 0.05 },
    { x: 0.05, y: 0.10 },
    { x: -0.001563, y: 0.10 },
  ])
  ok('VOC 历史数据 -0.001563 → 0', sanitized[0].x === 0 && sanitized[3].x === 0)
}

console.log('\n=== rectToPolygon ===')
{
  const poly = rectToPolygon({ x: 100, y: 200 }, { x: 300, y: 400 }, 640, 480)
  ok('返回 4 个点', poly.length === 4)
  ok('左上顶点', poly[0].x === 100/640 && poly[0].y === 200/480)
  ok('右上顶点', poly[1].x === 300/640 && poly[1].y === 200/480)
  ok('右下顶点', poly[2].x === 300/640 && poly[2].y === 400/480)
  ok('左下顶点', poly[3].x === 100/640 && poly[3].y === 400/480)
}
{
  // 反向拖拽（先点右下，再拖到左上）也应该产生正确矩形
  const poly = rectToPolygon({ x: 300, y: 400 }, { x: 100, y: 200 }, 640, 480)
  ok('反向拖拽：x1<x2', poly[0].x === 100/640)
  ok('反向拖拽：y1<y2', poly[0].y === 200/480)
}

console.log('\n=== pasteWithOffset ===')
{
  const clip = {
    class_id: 1,
    polygon: [
      { x: 0.1, y: 0.1 }, { x: 0.2, y: 0.1 },
      { x: 0.2, y: 0.2 }, { x: 0.1, y: 0.2 },
    ]
  }
  const pasted = pasteWithOffset(clip, 640, 480)
  ok('class_id 保留', pasted.class_id === 1)
  ok('每个顶点偏移 20/W', Math.abs(pasted.polygon[0].x - (0.1 + 20/640)) < 1e-9)
  ok('每个顶点偏移 20/H', Math.abs(pasted.polygon[0].y - (0.1 + 20/480)) < 1e-9)
  // 边缘场景：粘贴时偏移导致越界
  const edgeClip = {
    class_id: 1,
    polygon: [{ x: 0.99, y: 0.99 }, { x: 1.0, y: 0.99 }, { x: 1.0, y: 1.0 }],
  }
  const edgePasted = pasteWithOffset(edgeClip, 640, 480)
  ok('粘贴越界自动 clamp', edgePasted.polygon.every(p => p.x <= 1 && p.y <= 1))
}

console.log(`\n=== 结果: ${pass} passed, ${fail} failed ===`)
if (fail > 0) process.exit(1)
