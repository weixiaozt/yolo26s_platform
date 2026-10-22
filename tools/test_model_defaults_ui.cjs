// 本地 Vite + 隔离 API：不提交真实训练/导出，不修改业务项目。
const { chromium } = require('playwright')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const output = path.resolve('tmp/yolo26-native-defaults-20261022')
fs.mkdirSync(output, { recursive: true })

async function run() {
  const browser = await chromium.launch({ headless: true, channel: process.env.PW_CHANNEL || 'msedge' })
  let page
  const errors = []
  try {
    const context = await browser.newContext({ viewport: { width: 1600, height: 1050 } })
    await context.addInitScript(() => {
      localStorage.setItem('token', 'isolated-test')
      localStorage.setItem('user', JSON.stringify({ username: 'test', role: 'admin' }))
    })
    page = await context.newPage()
    page.on('pageerror', error => errors.push(error.message))
    let taskType = 'seg', cache = null, savedCache = null, trainingTasks = []
    const exports = []
    const task = (id, type) => ({ task_id: id, task_name: `YOLO26 ${type}`, task_type: type,
      model_name: `yolo26s-${type}`, status: 'completed', imgsz: type === 'cls' ? 224 : 640,
      models: [{ type: 'best', path: `fixture-${id}.pt` }] })
    await page.route(url => url.pathname.startsWith('/api/'), async route => {
      const request = route.request(), pathname = new URL(request.url()).pathname
      const json = body => route.fulfill({ json: body })
      if (pathname === '/api/projects/900') return json({ id: 900, name: '隔离测试', task_type: taskType,
        defect_classes: [{ id: 1, name: '缺陷' }], last_train_config: cache })
      if (pathname === '/api/projects/900/train/tasks') return json(trainingTasks)
      if (pathname === '/api/projects/900/train-config-cache') {
        savedCache = request.postDataJSON()
        return json({ ok: true })
      }
      if (pathname === '/api/export/tasks') return json([task(1, 'seg'), task(2, 'obb'), task(3, 'cls')])
      if (pathname === '/api/export/list') return json([])
      if (pathname === '/api/export/run') {
        exports.push(request.postDataJSON())
        return json({ id: exports.length, status: 'completed' })
      }
      throw new Error(`Unexpected API: ${request.method()} ${pathname}`)
    })
    const field = label => page.locator('.el-form-item').filter({ has: page.locator('.el-form-item__label', { hasText: new RegExp(`^${label}$`) }) })
    const modelSelect = () => field('模型尺寸').locator('.el-select')
    const openTrain = async () => {
      const loaded = page.waitForResponse(response => response.url().endsWith('/projects/900/train/tasks'))
      await page.goto('http://localhost:5174/project/900/train')
      await loaded
      await page.getByRole('radio', { name: '继承训练', exact: true }).waitFor()
      const canInherit = trainingTasks.some(t => ['completed', 'cancelled'].includes(t.status) && (t.best_model_path || t.last_model_path))
      await page.locator(`input[value="${canInherit ? 'finetune' : 'scratch'}"]:checked`).waitFor({ state: 'attached' })
    }
    for (taskType of ['seg', 'det', 'cls', 'obb']) {
      cache = null
      await openTrain()
      const suffix = taskType === 'det' ? '.pt' : `-${taskType}${taskType === 'seg' ? '' : '.pt'}`
      assert.match(await modelSelect().innerText(), new RegExp(`yolo26s${suffix.replace('.', '\\.')}`))
      await modelSelect().click()
      await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').first().waitFor()
      const options = await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').allTextContents()
      assert.equal(options.length, 10)
      assert(options.slice(0, 5).every(value => value.startsWith('yolo26')))
      assert(options.slice(5).every(value => value.startsWith('yolo11')))
      if (taskType === 'seg') await page.screenshot({ path: path.join(output, 'training-options.png'), animations: 'disabled' })
      await page.keyboard.press('Escape')
      console.log(`PASS ${taskType}: YOLO26 first and Small selected`)
    }
    taskType = 'seg'
    cache = { model_name: 'yolo11s-seg', epochs: 77 }
    await openTrain()
    assert.match(await modelSelect().innerText(), /yolo26s-seg/)
    assert.equal(await field('Epochs').getByRole('spinbutton').inputValue(), '77')
    cache = { model_name: 'yolo11s-seg', epochs: 77, _model_default_policy: 'yolo26-v1' }
    await openTrain()
    assert.match(await modelSelect().innerText(), /yolo11s-seg/)
    const saveResponse = page.waitForResponse(response => response.url().includes('/train-config-cache'))
    await page.getByRole('button', { name: '保存为默认', exact: true }).click()
    await saveResponse
    assert.equal(savedCache._model_default_policy, 'yolo26-v1')
    assert.equal(savedCache.model_name, 'yolo11s-seg')
    await page.getByRole('button', { name: '恢复默认值', exact: true }).click()
    await page.getByRole('button', { name: '恢复', exact: true }).click()
    assert.match(await modelSelect().innerText(), /yolo26s-seg/)
    console.log('PASS old cache migration, manual cache, inheritance and restore')

    cache = null
    for (taskType of ['seg', 'det', 'cls', 'obb']) {
      const modelName = `yolo11s${taskType === 'det' ? '.pt' : '-' + taskType + (taskType === 'seg' ? '' : '.pt')}`
      trainingTasks = [
        { id: 2, task_name: '最近训练', status: 'completed', best_model_path: 'new-best.pt', last_model_path: 'new-last.pt', config: { model_name: modelName, epochs: 80 } },
        { id: 1, task_name: '更早训练', status: 'completed', best_model_path: 'old.pt', config: { model_name: modelName, epochs: 60 } },
      ]
      await openTrain()
      assert.match(await field('继承模型').innerText(), /最近训练/)
      assert((await modelSelect().innerText()).includes(modelName))
      assert.equal(await field('Epochs').getByRole('spinbutton').inputValue(), '80')
      assert(await page.getByRole('radio', { name: /best.pt/ }).isChecked())
      assert.equal(await page.getByText('已加载「最近训练」的训练参数', { exact: true }).count(), 1)
      await page.getByText('从头训练', { exact: true }).click()
      assert.match(await modelSelect().innerText(), /yolo26s/)
      await page.getByText('继承训练', { exact: true }).click()
      assert((await modelSelect().innerText()).includes(modelName))
      console.log(`PASS ${taskType}: later training defaults to latest inheritance; manual switch preserved`)
    }
    taskType = 'seg'
    trainingTasks = [{ id: 3, task_name: '取消的训练', status: 'cancelled', last_model_path: 'last.pt', current_epoch: 5, epochs: 100 }]
    await openTrain()
    assert(await page.getByRole('radio', { name: /last.pt/ }).isChecked())
    trainingTasks = [{ id: 4, status: 'failed' }, { id: 3, status: 'completed', best_model_path: null, last_model_path: null }]
    await openTrain()
    assert(await page.getByRole('radio', { name: '继承训练', exact: true }).isDisabled())
    console.log('PASS cancelled task with last.pt; unavailable history falls back to scratch')

    await page.goto('http://localhost:5174/project/900/export')
    const native = page.getByRole('radio', { name: '原生端到端（默认）', exact: true })
    await native.waitFor()
    assert(await native.isChecked())
    const radios = await field('YOLO26 模式').locator('.el-radio__label').allTextContents()
    assert(radios[0].includes('原生'))
    assert(radios[1].includes('兼容'))
    const submitExport = async () => {
      const response = page.waitForResponse(res => res.url().endsWith('/export/run'))
      await page.getByRole('button', { name: '开始转换', exact: true }).click()
      await response
    }
    await submitExport()
    assert.equal(exports.at(-1).head_mode, 'native')
    assert.equal(exports.at(-1).nms, false)
    await page.getByText('兼容模式（传统 NMS）', { exact: true }).click()
    await submitExport()
    assert.equal(exports.at(-1).head_mode, 'compat')
    await field('训练任务').locator('.el-select').click()
    await page.getByRole('option').filter({ hasText: 'YOLO26 obb' }).click()
    assert(await native.isChecked())
    await page.getByText('OpenVINO', { exact: true }).first().click()
    assert(await native.isChecked())
    await submitExport()
    assert.equal(exports.at(-1).head_mode, 'native')
    assert.equal(exports.at(-1).export_format, 'openvino')
    await page.screenshot({ path: path.join(output, 'export-native.png'), animations: 'disabled' })
    await page.getByText('TensorRT', { exact: true }).first().click()
    await submitExport()
    assert.equal(exports.at(-1).head_mode, 'native')
    await field('训练任务').locator('.el-select').click()
    await page.getByRole('option').filter({ hasText: 'YOLO26 cls' }).click()
    await page.getByText('ONNX', { exact: true }).first().click()
    assert.equal(await field('YOLO26 模式').count(), 0)
    assert.equal(await field('内嵌 NMS').count(), 0)
    await submitExport()
    assert.equal(exports.at(-1).head_mode, 'legacy')
    assert.equal(exports.at(-1).imgsz, 224)
    assert.deepEqual(errors, [])
    console.log('PASS export defaults, mode selection, task reset, ONNX/OpenVINO/TensorRT, classification')
  } catch (error) {
    if (page) await page.screenshot({ path: path.join(output, 'failure.png') }).catch(() => {})
    throw error
  } finally {
    await browser.close()
  }
}
run().catch(error => { console.error(error); process.exitCode = 1 })
