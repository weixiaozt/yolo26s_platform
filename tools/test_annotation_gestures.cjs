// 隔离 API 的真实浏览器手势回归；只访问本地 Vite，不修改任何业务项目。
// 设置 NODE_PATH 为包含 playwright 的目录后运行 node tools/test_annotation_gestures.cjs。
const { chromium } = require('playwright')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const output = path.resolve('tmp/annotator-review-20261020')
fs.mkdirSync(output, { recursive: true })
const clone = value => structuredClone(value)
const box = (x,y,w=.12,h=.12) => [{x,y},{x:x+w,y},{x:x+w,y:y+h},{x,y:y+h}]
const densify = polygon => polygon.flatMap((p,i) => {
  const next=polygon[(i+1)%polygon.length]
  return Array.from({length:100},(_,j)=>({x:p.x+(next.x-p.x)*j/100,y:p.y+(next.y-p.y)*j/100}))
})
const initial = () => [
  {class_id:1,confidence:null,polygon:box(.1,.15)},
  {class_id:2,confidence:.93,polygon:box(.35,.15)},
  {class_id:1,confidence:null,polygon:box(.7,.15)},
  {class_id:2,confidence:.8,polygon:densify(box(.2,.6,.45,.03))}, // 模拟涂抹产生的 400 顶点密集区域
  {class_id:1,confidence:null,polygon:box(.75,.6,.15,.18)},
]
const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="800"><rect width="1000" height="800" fill="#777"/></svg>'
const near = (actual,expected,message,tolerance=1e-7) => assert.ok(Math.abs(actual-expected)<tolerance,`${message}: ${actual} != ${expected}`)
function samePolygons(actual,expected,message) {
  assert.equal(actual.length,expected.length,message)
  actual.forEach((ann,i) => {
    assert.equal(ann.class_id,expected[i].class_id, message)
    assert.equal(ann.confidence,expected[i].confidence, message)
    assert.equal(ann.polygon.length,expected[i].polygon.length, message)
    ann.polygon.forEach((p,j) => {
      near(p.x,expected[i].polygon[j].x,message)
      near(p.y,expected[i].polygon[j].y,message)
    })
  })
}

async function run() {
  const browser = await chromium.launch({headless:true,channel:process.env.PW_CHANNEL || 'msedge'})
  let currentPage
  try {
    for (const taskType of ['seg','det','obb']) {
      const context = await browser.newContext({viewport:{width:1920,height:1000}})
      const page = currentPage = await context.newPage()
      page.setDefaultTimeout(10000)
      const errors = []
      page.on('pageerror',e=>errors.push(e.message))
      let annotations = initial()
      let saves = []
      await page.addInitScript(() => {
        localStorage.setItem('token','isolated-gesture-test')
        localStorage.setItem('user',JSON.stringify({username:'test',role:'admin'}))
      })
      await page.route(url=>url.pathname.startsWith('/api/'),async route => {
        const req=route.request(), p=new URL(req.url()).pathname
        const json=body=>route.fulfill({json:body})
        if (/\/images\/\d+\/file$/.test(p)) return route.fulfill({contentType:'image/svg+xml',body:svg})
        if (/\/projects\/\d+$/.test(p)) return json({id:990,name:'手势回归',task_type:taskType,defect_classes:[
          {id:1,name:'人工标注',color:'#ef4444',class_index:0},
          {id:2,name:'推理标注',color:'#22c55e',class_index:1},
        ]})
        if (/\/projects\/\d+\/images$/.test(p)) return json({items:[{
          id:991,project_id:990,filename:'gesture-fixture.svg',width:1000,height:800,status:'labeled',annotation_count:annotations.length,
        }],total:1,page:1,page_size:999})
        if (p==='/api/inference/models') return json([])
        if (/\/images\/\d+\/annotations$/.test(p)) {
          if(req.method()==='POST'){annotations=req.postDataJSON().annotations;saves.push(clone(annotations))}
          return json(annotations)
        }
        throw new Error(`Unexpected API: ${req.method()} ${p}`)
      })
      await page.goto('http://localhost:5174/annotate/990/991')
      await page.locator('.ann-item').nth(4).waitFor()
      const canvas=page.locator('.upper-canvas')
      const fit=()=>page.getByRole('button',{name:'适应窗口',exact:true}).click()
      await fit()
      const bounds=await canvas.boundingBox()
      const zoom=Math.min(bounds.width/1000,bounds.height/800)*.95
      const at=(x,y)=>({x:bounds.x+(bounds.width-1000*zoom)/2+x*1000*zoom,y:bounds.y+(bounds.height-800*zoom)/2+y*800*zoom})
      const expectSelection=async expected=>{
        await page.waitForFunction(indices=>{
          const actual=[...document.querySelectorAll('.ann-item[aria-selected="true"]')].map(r=>Number(r.dataset.annIndex))
          return JSON.stringify(actual)===JSON.stringify(indices)
        },expected)
      }
      const click=async (p,key)=>{
        if(key)await page.keyboard.down(key)
        await page.mouse.click(p.x,p.y)
        if(key)await page.keyboard.up(key)
      }
      const drag=async (a,b,key,hold)=>{
        if(key)await page.keyboard.down(key)
        await page.mouse.move(a.x,a.y)
        await page.mouse.down()
        await page.mouse.move(b.x,b.y,{steps:6})
        if(hold)await hold()
        await page.mouse.up()
        if(key)await page.keyboard.up(key)
      }
      const withSave=async action=>{
        const response=page.waitForResponse(r=>/\/annotations$/.test(new URL(r.url()).pathname)&&r.request().method()==='POST')
        await action()
        await response
        return clone(saves.at(-1))
      }
      const undo=()=>withSave(()=>page.keyboard.press('Control+z'))
      const redo=()=>withSave(()=>page.keyboard.press('Control+y'))
      const baseline=initial()

      // 工具按钮保持焦点时也可按 V 回到选择；输入框和 Ctrl+V 不触发切换。
      const selectRadio=page.getByRole('radio',{name:'选择',exact:true})
      for(const tool of ['多边形','矩形','涂抹','圆形','折线','擦除','框选擦除']){
        await page.locator('.toolbar .el-radio-button').filter({hasText:new RegExp(`^${tool}$`)}).click()
        await page.keyboard.press('v')
        assert.equal(await selectRadio.isChecked(),true,`V switches ${tool} to select`)
      }
      await page.locator('.toolbar .el-radio-button').filter({hasText:/^多边形$/}).click()
      await click(at(.9,.9)) // 尚未完成的绘制应按原来的切工具逻辑取消
      await page.keyboard.press('V')
      assert.equal(await selectRadio.isChecked(),true)
      assert.equal(await page.locator('.ann-item').count(),5)
      await page.locator('.toolbar .el-radio-button').filter({hasText:/^矩形$/}).click()
      await page.keyboard.press('Control+v')
      assert.equal(await page.getByRole('radio',{name:'矩形',exact:true}).isChecked(),true)
      await page.getByRole('spinbutton',{name:'推理置信度'}).focus()
      await page.keyboard.press('v')
      assert.equal(await selectRadio.isChecked(),false,'typing V in an input keeps the tool')
      await page.locator('.annotator').focus()
      await page.keyboard.press('v')
      assert.equal(await selectRadio.isChecked(),true)
      assert.equal(saves.length,0,'switching tools must not save incomplete shapes')

      await click(at(.16,.21));await expectSelection([0])
      await click(at(.41,.21),'Shift');await expectSelection([0,1])
      await click(at(.16,.21),'Shift');await expectSelection([1])
      await click(at(.16,.21));await expectSelection([0])
      // 小于 4px 的手抖只作为点击；选中和画布操作不消耗撤销栈。
      const p=at(.41,.21)
      await drag(p,{x:p.x+2,y:p.y+1})
      await expectSelection([1])
      assert.equal(await page.getByRole('button',{name:'撤销',exact:true}).isDisabled(),true)
      await click(at(.16,.21),'Shift');await expectSelection([0,1])
      // 普通拖动已选对象内部/绿色手柄都只能平移；顶点现在由左键直接编辑。
      for (const start of [at(.16,.21),at(.16,.15-22/800)]) {
        await drag(start,{x:start.x+30,y:start.y+18})
        await expectSelection([0,1])
        assert.equal(saves.length,0,'plain drag must not save annotations')
        await fit()
      }
      await click(at(.95,.9));await expectSelection([])
      // Ctrl 拖动未选中对象也不能修改它，必须先选择。
      await drag(at(.16,.21),at(.18,.23),'Control')
      assert.equal(saves.length,0);await expectSelection([]);await fit()

      // Shift 框选为追加：接触轮廓就选中，并支持反方向框选。
      await click(at(.76,.21))
      await drag(at(.4,.19),at(.2,.1),'Shift');await expectSelection([0,1,2])
      await click(at(.95,.9))
      await drag(at(.4,.55),at(.42,.68),'Shift');await expectSelection([3])
      await click(at(.95,.9))
      await drag(at(.79,.64),at(.8,.66),'Shift');await expectSelection([4])
      await click(at(.16,.21))
      await drag(at(.9,.85),at(.95,.9),'Shift');await expectSelection([0])
      assert.equal(saves.length,0)

      await click(at(.41,.21),'Shift')
      const moved=await withSave(()=>drag(at(.16,.21),at(.21,.26),'Control',async()=>{
        await page.waitForTimeout(750)
        assert.equal(saves.length,0,'do not save partial drag while holding mouse')
      }))
      const dx=moved[0].polygon[0].x-baseline[0].polygon[0].x
      const dy=moved[0].polygon[0].y-baseline[0].polygon[0].y
      near(dx,.05,'group dx',.002);near(dy,.05,'group dy',.002)
      for(const idx of [0,1]) for(let i=0;i<4;i++){
        near(moved[idx].polygon[i].x-baseline[idx].polygon[i].x,dx,'common group dx')
        near(moved[idx].polygon[i].y-baseline[idx].polygon[i].y,dy,'common group dy')
      }
      samePolygons(moved.slice(2),baseline.slice(2),'unselected objects unchanged')
      samePolygons(await undo(),baseline,'one undo restores entire group')
      samePolygons(await redo(),moved,'one redo restores entire group')
      samePolygons(await undo(),baseline,'reset after redo')

      // 整组到边缘停止，形状和间距保持不变。
      await click(at(.16,.21));await click(at(.41,.21),'Shift')
      const edge=await withSave(()=>drag(at(.16,.21),at(1.1,.21),'Control'))
      near(Math.max(...edge[1].polygon.map(p=>p.x)),1,'group clamped at image boundary')
      const edgeDx=edge[0].polygon[0].x-baseline[0].polygon[0].x
      for(const idx of [0,1]) for(let i=0;i<4;i++)near(edge[idx].polygon[i].x-baseline[idx].polygon[i].x,edgeDx,'no clipped vertices')
      samePolygons(await undo(),baseline,'undo edge clamp')

      // 多选时 Ctrl 落在角点上，也必须移动整组，不能修改单个顶点。
      await click(at(.16,.21));await click(at(.41,.21),'Shift')
      const cornerMove=await withSave(()=>drag(at(.1,.15),at(.12,.18),'Control'))
      const cornerDx=cornerMove[0].polygon[0].x-baseline[0].polygon[0].x
      const cornerDy=cornerMove[0].polygon[0].y-baseline[0].polygon[0].y
      near(cornerDx,.02,'Ctrl corner group dx',.002);near(cornerDy,.03,'Ctrl corner group dy',.002)
      for(const idx of [0,1]) for(let i=0;i<4;i++){
        near(cornerMove[idx].polygon[i].x-baseline[idx].polygon[i].x,cornerDx,'Ctrl corner moves all vertices')
        near(cornerMove[idx].polygon[i].y-baseline[idx].polygon[i].y,cornerDy,'Ctrl corner moves all vertices')
      }
      samePolygons(await undo(),baseline,'undo Ctrl corner group move')

      // 多选时普通左键拖角点只改变对应对象的这个顶点。
      await click(at(.16,.21));await click(at(.41,.21),'Shift')
      const vertex=await withSave(()=>drag(at(.1,.15),at(.08,.12)))
      assert.notDeepEqual(vertex[0].polygon[0],baseline[0].polygon[0])
      assert.deepEqual(vertex[0].polygon.slice(1),baseline[0].polygon.slice(1))
      samePolygons(vertex.slice(1),baseline.slice(1),'vertex drag does not edit other selected object')
      samePolygons(await undo(),baseline,'undo vertex edit')

      // 密集涂抹轮廓：Ctrl 从顶点起拖保持 400 个点的相对位置，左键只编辑最近的 1 个点。
      await click(at(.4,.615))
      const denseMove=await withSave(()=>drag(at(.2,.615),at(.23,.635),'Control'))
      assert.equal(denseMove[3].polygon.length,400)
      const denseDx=denseMove[3].polygon[0].x-baseline[3].polygon[0].x
      const denseDy=denseMove[3].polygon[0].y-baseline[3].polygon[0].y
      near(denseDx,.03,'dense region dx',.002);near(denseDy,.02,'dense region dy',.002)
      for(let i=0;i<400;i++){
        near(denseMove[3].polygon[i].x-baseline[3].polygon[i].x,denseDx,'dense point dx')
        near(denseMove[3].polygon[i].y-baseline[3].polygon[i].y,denseDy,'dense point dy')
      }
      samePolygons(await undo(),baseline,'undo dense move')
      await click(at(.4,.615))
      const denseVertex=await withSave(()=>drag(at(.2,.615),at(.19,.615)))
      const changed=denseVertex[3].polygon.filter((p,i)=>
        Math.abs(p.x-baseline[3].polygon[i].x)>1e-7 || Math.abs(p.y-baseline[3].polygon[i].y)>1e-7)
      assert.equal(changed.length,1,'left drag edits one nearest dense vertex')
      samePolygons(await undo(),baseline,'undo dense vertex')

      await click(at(.16,.21));await click(at(.41,.21),'Shift')
      const center=at(.16,.21),rot=at(.16,.15-22/800)
      const rotation=await withSave(()=>drag(rot,{x:center.x+(center.y-rot.y),y:center.y},'Control'))
      assert.notDeepEqual(rotation[0].polygon,baseline[0].polygon)
      samePolygons(rotation.slice(1),baseline.slice(1),'rotation changes only its own object')
      // 接近 90°，旋转中心和边长必须保留（像素坐标）。
      const centroid=rotation[0].polygon.reduce((s,p)=>({x:s.x+p.x/4,y:s.y+p.y/4}),{x:0,y:0})
      near(centroid.x,.16,'rotation center x');near(centroid.y,.21,'rotation center y')
      const dist=(a,b)=>Math.hypot((a.x-b.x)*1000,(a.y-b.y)*800)
      near(dist(rotation[0].polygon[0],rotation[0].polygon[1]),120,'rotation preserves edge length')
      samePolygons(await undo(),baseline,'rotation undo restores original, not rotated result')

      // Esc 取消拖动不保存，也不增加撤销记录。
      await click(at(.16,.21))
      const beforeCancel=saves.length
      await drag(at(.16,.21),at(.2,.24),'Control',()=>page.keyboard.press('Escape'))
      await page.waitForTimeout(750)
      assert.equal(saves.length,beforeCancel)
      assert.equal(await page.getByRole('button',{name:'撤销',exact:true}).isDisabled(),true)

      // 双击适应窗口，平移/缩放不产生撤销。
      const fitZoomText=await page.locator('.statusbar').innerText()
      await canvas.hover();await page.mouse.wheel(0,-400)
      await page.waitForFunction(text=>document.querySelector('.statusbar').innerText!==text,fitZoomText)
      await drag(at(.95,.9),at(.9,.85))
      await page.mouse.dblclick(at(.95,.9).x,at(.95,.9).y)
      assert.equal(await page.locator('.statusbar').innerText(),fitZoomText,'double click restores fit zoom')
      await click(at(.16,.21));await expectSelection([0])
      assert.equal(await page.getByRole('button',{name:'撤销',exact:true}).isDisabled(),true)

      // 视图旋转后移动及撤销仍按原图坐标保存。
      await page.getByRole('button',{name:'向右旋转90°（快捷键 R）'}).click()
      const rotatedZoom=Math.min(bounds.width/800,bounds.height/1000)*.95
      const rotatedAt=(x,y)=>({x:bounds.x+(bounds.width-800*rotatedZoom)/2+(1-y)*800*rotatedZoom,y:bounds.y+(bounds.height-1000*rotatedZoom)/2+x*1000*rotatedZoom})
      await click(rotatedAt(.16,.21))
      const rotatedStart=rotatedAt(.16,.21)
      const rotatedMove=await withSave(()=>drag(rotatedStart,{x:rotatedStart.x+40,y:rotatedStart.y},'Control'))
      near(rotatedMove[0].polygon[0].x,.1,'view rotation preserves original x')
      near(rotatedMove[0].polygon[0].y,.15-40/rotatedZoom/800,'view rotation maps translation to original y',.002)
      samePolygons(await undo(),baseline,'undo in rotated view')
      await page.getByRole('button',{name:'向左旋转90°（仅旋转视图，保存坐标自动换算回原图）'}).click()

      // 绘制工具双击仍完成轮廓，不触发适应窗口；复制粘贴仍可用。
      for (const tool of ['多边形','折线']) {
        await page.locator('.toolbar .el-radio-button').filter({hasText:new RegExp(`^${tool}$`)}).click()
        await click(at(.08,.4));await click(at(.14,.4))
        const drawn=await withSave(()=>page.mouse.dblclick(at(.14,.47).x,at(.14,.47).y))
        assert.equal(drawn.length,6,`${tool} double click finishes drawing`)
        samePolygons(await undo(),baseline,`${tool} undo`)
      }
      await page.locator('.toolbar .el-radio-button').filter({hasText:/^选择$/}).click()
      await click(at(.41,.21));await page.keyboard.press('Control+c')
      const pasted=await withSave(()=>page.keyboard.press('Control+v'))
      assert.equal(pasted.length,6)
      assert.equal(pasted[5].confidence,undefined,'manual paste does not inherit inference confidence')
      samePolygons(await undo(),baseline,'paste undo')

      await click(at(.16,.21));await click(at(.41,.21),'Shift')
      await page.screenshot({path:path.join(output,`${taskType}-multi-selection.png`)})
      if(taskType==='seg'){
        await click(at(.4,.615))
        await page.mouse.move(at(.2,.615).x,at(.2,.615).y)
        for(let i=0;i<20;i++){
          const previous=await page.locator('.statusbar').innerText()
          await page.mouse.wheel(0,-200)
          await page.waitForFunction(text=>document.querySelector('.statusbar').innerText!==text,previous)
        }
        await page.screenshot({path:path.join(output,'dense-small-vertices.png')})
        await fit()
      }
      await page.locator('.display-options label').filter({hasText:/^显示标注$/}).click()
      await expectSelection([])
      const beforeHidden=saves.length
      await drag(at(.16,.21),at(.21,.26),'Control')
      assert.equal(saves.length,beforeHidden,'hidden annotations are not editable')
      await page.locator('.display-options label').filter({hasText:/^显示标注$/}).click()
      await fit()
      assert.deepEqual(errors,[])
      console.log(`${taskType}: selection, marquee, pan, Ctrl group/corner move, left vertex editing (including 400 dense points), rotation, bounds, undo/redo, Esc, fit, rotated coordinates, drawing and paste PASS (${saves.length} saves)`)
      await context.close()
    }
  } catch(error) {
    if(currentPage&&!currentPage.isClosed())await currentPage.screenshot({path:path.join(output,'gesture-failure.png')})
    throw error
  } finally {
    await browser.close()
  }
}
run().catch(error=>{console.error(error);process.exitCode=1})
