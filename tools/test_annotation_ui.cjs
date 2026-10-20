// 浏览器回归：使用本地 Vite + 隔离的 API 数据，不写入真实项目。
// NODE_PATH 指向可用的 playwright 包后运行 node tools/test_annotation_ui.cjs。
const { chromium } = require('playwright')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const output = path.resolve('tmp/annotator-review-20261020')
fs.mkdirSync(output, { recursive: true })

const classes = [
  { id: 1, name: '隐裂 Crack', color: '#ef4444', class_index: 0 },
  { id: 2, name: '断栅 Broken finger', color: '#a855f7', class_index: 1 },
  ...Array.from({ length: 12 }, (_, i) => ({
    id: i + 3, name: `测试类别 ${i + 3}`, color: '#22c55e', class_index: i + 2,
  })),
]
const rectangle = (x, y) => [{ x, y }, { x: x + .04, y }, { x: x + .04, y: y + .05 }, { x, y: y + .05 }]
const initialAnnotations = () => Array.from({ length: 80 }, (_, i) => ({
  class_id: i % 2 + 1, confidence: i % 2 ? .912 : null,
  polygon: rectangle(.03 + (i % 10) * .09, .03 + Math.floor(i / 10) * .115),
}))
const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="800">
  <rect width="1000" height="800" fill="#80878c"/>
  <path d="M0 200H1000M0 400H1000M0 600H1000M250 0V800M500 0V800M750 0V800" stroke="#60656a" stroke-width="4"/>
</svg>`

async function run() {
  const browser = await chromium.launch({ headless: true, channel: process.env.PW_CHANNEL || 'msedge' })
  let currentPage
  try {
    for (const taskType of ['seg', 'det', 'obb']) {
      const context = await browser.newContext({ viewport: { width: 1920, height: 1000 } })
      const page = await context.newPage()
      currentPage = page
      const errors = []
      page.on('pageerror', e => errors.push(e.message))
      let annotations = initialAnnotations()
      let inferenceRequests = []
      let savedRequests = []
      await page.addInitScript(() => {
        localStorage.setItem('token', 'isolated-test')
        localStorage.setItem('user', JSON.stringify({ username: 'test', role: 'admin' }))
        if (!localStorage.getItem('annotation-preferences-v1')) {
          localStorage.setItem('annotation-preferences-v1', JSON.stringify({
            showAnnotations: false, showClassNames: true, showConfidence: true, inferConfidence: .35,
          }))
        }
        // 记录实际画布输出，验证文字内容，而非复制渲染实现。
        window.annotationDrawnText = []
        const original = CanvasRenderingContext2D.prototype.fillText
        CanvasRenderingContext2D.prototype.fillText = function (text, ...args) {
          if (this.canvas.classList.contains('lower-canvas')) {
            window.annotationDrawnText.push(String(text))
            window.annotationDrawnFont = parseFloat(this.font)
          }
          return original.call(this, text, ...args)
        }
      })
      await page.route(url => url.pathname.startsWith('/api/'), async route => {
        const request = route.request()
        const url = new URL(request.url())
        const pathname = url.pathname
        const json = body => route.fulfill({ json: body })
        if (/\/images\/\d+\/file$/.test(pathname)) return route.fulfill({ contentType: 'image/svg+xml', body: svg })
        if (/\/projects\/\d+$/.test(pathname)) return json({ id: 900, name: 'UI regression', task_type: taskType, defect_classes: classes })
        if (/\/projects\/\d+\/images$/.test(pathname)) return json({
          items: [901, 902].map(id => ({ id, project_id: 900, filename: `验收示例-${id}.png`, width: 1000,
            height: 800, status: 'labeled', annotation_count: annotations.length })),
          total: 2, page: 1, page_size: 999,
        })
        if (pathname === '/api/inference/models') return json([{ task_id: 1, model_format: 'pytorch', model_path: 'mock.pt', label: '测试模型 best.pt' }])
        if (/\/images\/\d+\/annotations$/.test(pathname)) {
          if (request.method() === 'POST') {
            annotations = request.postDataJSON().annotations
            savedRequests.push(structuredClone(annotations))
          }
          return json(annotations)
        }
        if (pathname === '/api/inference/annotation-current') {
          inferenceRequests.push(request.postDataJSON())
          return json({ count: 1, skipped: 0, annotations: [{ class_id: 2, confidence: .94, polygon: rectangle(.5, .4) }] })
        }
        throw new Error(`Unexpected API call: ${request.method()} ${pathname}`)
      })
      await page.goto('http://localhost:5174/annotate/900/901')
      await page.locator('.ann-item').nth(79).waitFor()
      assert.equal(await page.getByRole('checkbox', { name: '显示信息', exact: true }).isChecked(), false)
      assert.equal(await page.getByRole('checkbox', { name: '显示置信度', exact: true }).isChecked(), false)
      assert.equal(await page.getByRole('checkbox', { name: '显示标注', exact: true }).isChecked(), true)
      const editBar = await page.getByRole('region', { name: '编辑操作区' }).boundingBox()
      const inferBar = await page.getByRole('region', { name: '推理标注功能区' }).boundingBox()
      assert.ok(inferBar.y >= editBar.y + editBar.height, 'inference has its own second row')
      await page.evaluate(() => document.fonts.load('12px "ChillRoundF"'))
      assert.equal(await page.evaluate(() => [...document.fonts].some(font => font.family === 'ChillRoundF' && font.status === 'loaded')), true)
      await page.getByRole('button', { name: '适应窗口', exact: true }).click()
      const canvas = page.locator('.upper-canvas')
      const rect = await canvas.boundingBox()
      const zoom = Math.min(rect.width / 1000, rect.height / 800) * .95
      const point = {
        x: rect.x + (rect.width - 1000 * zoom) / 2 + (.03 + 4 * .09 + .02) * 1000 * zoom,
        y: rect.y + (rect.height - 800 * zoom) / 2 + (.03 + 5 * .115 + .025) * 800 * zoom,
      }
      await page.mouse.click(point.x, point.y)
      await page.waitForFunction(() => document.querySelector('[data-ann-index="54"]')?.getAttribute('aria-selected') === 'true')
      const delta = await page.locator('.ann-list').evaluate(list => {
        const row = list.querySelector('[aria-selected="true"]')
        const a = list.getBoundingClientRect(), b = row.getBoundingClientRect()
        return Math.abs((a.top + a.bottom - b.top - b.bottom) / 2)
      })
      assert.ok(delta < 3, `${taskType}: selected row is centered (delta=${delta})`)
      assert.match(await page.locator('.selected-summary').innerText(), /#55 隐裂 Crack/)
      // 平移画布后重新点击，命中坐标必须跟着视口移动。
      await page.mouse.click(rect.x + 20, rect.y + 20)
      await page.keyboard.down('Space')
      await page.mouse.move(point.x, point.y)
      await page.mouse.down()
      await page.mouse.move(point.x + 40, point.y + 25, { steps: 4 })
      await page.mouse.up()
      await page.keyboard.up('Space')
      await page.mouse.click(point.x + 40, point.y + 25)
      await page.waitForFunction(() => document.querySelector('[data-ann-index="54"]')?.getAttribute('aria-selected') === 'true')
      await page.getByRole('button', { name: '适应窗口', exact: true }).click()

      await page.locator('.display-options label').filter({ hasText: '显示信息' }).click()
      await page.locator('.display-options label').filter({ hasText: '显示置信度' }).click()
      await page.waitForFunction(() => window.annotationDrawnText.includes('#2 断栅 Broken finger · 91.2%'))
      const texts = await page.evaluate(() => window.annotationDrawnText)
      assert.ok(texts.includes('#1 隐裂 Crack'), 'manual annotation displays name/number')
      assert.ok(!texts.some(t => t.startsWith('#1 ') && t.includes('%')), 'manual annotation has no fabricated score')
      assert.equal(await page.locator('.ann-confidence').count(), 40)
      assert.equal(await page.evaluate(() => window.annotationDrawnFont), 2, 'previous 6px font is reduced by two thirds')
      await canvas.hover()
      await page.mouse.wheel(0, -200)
      await page.waitForFunction(() => window.annotationDrawnFont > 2)
      const zoomedFont = await page.evaluate(() => window.annotationDrawnFont)
      await page.mouse.wheel(0, 200)
      await page.waitForFunction(previous => window.annotationDrawnFont < previous, zoomedFont)
      await page.getByRole('button', { name: '适应窗口', exact: true }).click()
      await page.screenshot({ path: path.join(output, `${taskType}-selected-labels.png`) })

      await page.locator('.display-options label').filter({ hasText: /^显示标注$/ }).click()
      await page.evaluate(() => { window.annotationDrawnText = [] })
      await page.mouse.click(point.x, point.y)
      assert.equal(await page.locator('.ann-item[aria-selected="true"]').count(), 0)
      assert.equal((await page.evaluate(() => window.annotationDrawnText)).length, 0)
      await page.screenshot({ path: path.join(output, `${taskType}-hidden.png`) })
      // 切图后仍隐藏，列表选中则主动恢复显示并定位。
      await page.locator('.nav-item').nth(1).click()
      assert.equal(await page.getByRole('checkbox', { name: '显示标注', exact: true }).isChecked(), false)
      await page.locator('[data-ann-index="54"]').click()
      assert.equal(await page.getByRole('checkbox', { name: '显示标注', exact: true }).isChecked(), true)

      const confInput = page.getByRole('spinbutton', { name: '推理置信度' })
      await confInput.fill('')
      await confInput.press('Tab')
      await page.getByRole('button', { name: '推理标注', exact: true }).click()
      await page.getByText('请输入 0～1 之间的推理置信度', { exact: true }).waitFor()
      assert.equal(inferenceRequests.length, 0, 'empty confidence must not submit inference')
      await confInput.fill('0.75')
      await confInput.press('Tab')
      await page.getByRole('button', { name: '推理标注', exact: true }).click()
      await page.getByRole('button', { name: '追加到当前标注', exact: true }).click()
      await page.waitForFunction(() => document.querySelectorAll('.ann-item').length === 81)
      await page.waitForResponse(r => /\/annotations$/.test(new URL(r.url()).pathname) && r.request().method() === 'POST')
      assert.equal(inferenceRequests[0].conf, .75)
      assert.equal(savedRequests.at(-1).at(-1).confidence, .94)
      assert.equal(savedRequests.at(-1)[0].confidence, null)
      await page.locator('.display-options label').filter({ hasText: /^显示标注$/ }).click()
      await page.reload()
      await page.locator('.ann-item').nth(80).waitFor()
      assert.equal(await confInput.inputValue(), '0.75')
      assert.equal(await page.getByRole('checkbox', { name: '显示标注', exact: true }).isChecked(), true)
      assert.equal(await page.getByRole('checkbox', { name: '显示信息', exact: true }).isChecked(), false)
      assert.equal(await page.getByRole('checkbox', { name: '显示置信度', exact: true }).isChecked(), false)
      assert.equal(await page.locator('.ann-confidence').count(), 0)
      await page.locator('.display-options label').filter({ hasText: '显示信息' }).click()
      await page.locator('.display-options label').filter({ hasText: '显示置信度' }).click()
      assert.match(await page.locator('.ann-item').nth(80).innerText(), /94.0%/)
      await page.getByRole('button', { name: '删除标注 #81', exact: true }).click()
      await page.waitForFunction(() => document.querySelectorAll('.ann-item').length === 80)
      assert.equal(await page.locator('.ann-confidence').count(), 40)
      // 新画的人工标注不应继承上一条推理结果的置信度。
      await page.locator('.toolbar .el-radio-button').filter({ hasText: /^矩形$/ }).click()
      const at = (x, y) => ({
        x: rect.x + (rect.width - 1000 * zoom) / 2 + x * 1000 * zoom,
        y: rect.y + (rect.height - 800 * zoom) / 2 + y * 800 * zoom,
      })
      const start = at(.93, .92), end = at(.97, .96)
      await page.mouse.move(start.x, start.y)
      await page.mouse.down()
      await page.mouse.move(end.x, end.y, { steps: 4 })
      await page.mouse.up()
      await page.waitForFunction(() => document.querySelectorAll('.ann-item').length === 81)
      const manualSaved = await page.waitForResponse(r => /\/annotations$/.test(new URL(r.url()).pathname)
        && r.request().method() === 'POST' && r.request().postDataJSON().annotations.length === 81)
      assert.equal(manualSaved.request().postDataJSON().annotations.at(-1).confidence, undefined)
      assert.equal(await page.locator('.ann-confidence').count(), 40)
      // 浏览器缩放/画布缩放后仍能绘制，不因新增标签报错。
      await canvas.hover()
      await page.mouse.wheel(0, -200)
      await page.getByTitle('向右旋转90°（快捷键 R）').click()
      await page.getByRole('button', { name: '适应窗口', exact: true }).click()
      await page.setViewportSize({ width: 1366, height: 768 })
      await page.getByRole('button', { name: '适应窗口', exact: true }).click()
      await page.screenshot({ path: path.join(output, `${taskType}-compact.png`) })
      await page.goto('http://localhost:5174/annotate/999/901')
      await page.locator('.ann-item').nth(80).waitFor()
      assert.equal(await confInput.inputValue(), '0.75')
      assert.equal(await page.getByRole('checkbox', { name: '显示信息', exact: true }).isChecked(), false)
      assert.equal(await page.getByRole('checkbox', { name: '显示置信度', exact: true }).isChecked(), false)
      assert.equal(await page.getByRole('checkbox', { name: '显示标注', exact: true }).isChecked(), true)
      assert.deepEqual(errors, [])
      console.log(`${taskType}: canvas selection/centering, labels, hidden layer, confidence request/save/reload, delete, zoom/rotation OK`)
      await context.close()
      currentPage = null
    }
  } catch (error) {
    if (currentPage) {
      await currentPage.screenshot({ path: path.join(output, 'failure.png') })
      console.error(await currentPage.locator('.selected-summary, .draw-hint').allTextContents())
    }
    throw error
  } finally {
    await browser.close()
  }
}
run().catch(error => { console.error(error); process.exitCode = 1 })
