<template>
  <div class="annotator" tabindex="0" ref="rootRef">
    <div class="toolbar">
      <div class="toolbar-left">
        <el-button text @click="goBack"><el-icon><ArrowLeft /></el-icon> 返回</el-button>
        <el-divider direction="vertical" />
        <span class="filename">{{ currentImage?.filename }}</span>
        <el-tag :type="statusTagType" size="small" style="margin-left:8px">{{ statusLabel }}</el-tag>
      </div>
      <div class="toolbar-center">
        <el-radio-group v-model="currentTool" size="small" @change="onToolChange">
          <el-radio-button label="select">选择</el-radio-button>
          <el-radio-button label="polygon">多边形</el-radio-button>
          <el-radio-button label="rect">矩形</el-radio-button>
          <el-radio-button label="brush">涂抹</el-radio-button>
          <el-radio-button label="circle">圆形</el-radio-button>
          <el-radio-button label="polyline">折线</el-radio-button>
          <el-radio-button label="eraser">擦除</el-radio-button>
          <el-radio-button label="boxEraser">框选擦除</el-radio-button>
        </el-radio-group>
        <el-divider direction="vertical" />
        <div v-if="showBrushSize" class="brush-size-ctrl">
          <span class="ctrl-label">{{ currentTool==='eraser'?'橡皮':'画笔' }}</span>
          <el-slider v-model="brushSize" :min="1" :max="100" :step="1" style="width:100px" />
          <span class="ctrl-value">{{ brushSize }}px</span>
        </div>
        <el-divider direction="vertical" />
        <el-button size="small" :disabled="!canUndo" @click="undo">撤销</el-button>
        <el-button size="small" :disabled="!canRedo" @click="redo">重做</el-button>
        <el-button size="small" @click="zoomFit">适应窗口</el-button>
        <el-button size="small" type="danger" :disabled="annotations.length===0" @click="clearAll">清空</el-button>
      </div>
      <div class="toolbar-right">
        <span class="save-indicator" :class="saveState">{{ saveStateText }}</span>
        <el-button v-if="currentImage?.status!=='reviewed'" @click="markAsOk" size="small" type="success">标记OK</el-button>
        <el-button v-else @click="unmarkOk" size="small" type="warning">取消OK</el-button>
      </div>
    </div>
    <div class="main-area">
      <div class="nav-panel">
        <div class="nav-header">图像列表</div>
        <div class="nav-list">
          <div v-for="img in imageList" :key="img.id" :class="['nav-item',{active:img.id===currentImageId},imgSC(img)]" @click="switchImage(img.id)">
            <img :src="getThumbUrl(img.id)" class="nav-thumb" loading="lazy" />
            <div class="nav-info">
              <div class="nav-filename">{{ img.filename }}</div>
              <div class="nav-status-row">
                <span :class="['status-dot','dot-'+img.status]"></span>
                <span class="nav-status-text">{{ stText(img.status) }}</span>
                <span v-if="img.annotation_count>0" class="nav-ann-count">{{ img.annotation_count }}</span>
              </div>
            </div>
          </div>
        </div>
        <div class="nav-footer">
          <el-button size="small" :disabled="!hasPrev" @click="prevImage">◀</el-button>
          <el-button size="small" :disabled="!hasNext" @click="nextImage">▶</el-button>
        </div>
      </div>
      <div class="canvas-area" ref="canvasAreaRef">
        <canvas ref="canvasEl" id="annotationCanvas"></canvas>
        <div v-if="toolHint" class="draw-hint">{{ toolHint }}</div>
      </div>
      <div class="side-panel">
        <div class="panel-section">
          <div class="panel-title">当前类别</div>
          <div class="class-list">
            <div v-for="dc in defectClasses" :key="dc.id" :class="['class-item',{active:selectedClassId===dc.id}]" @click="selectedClassId=dc.id!">
              <span class="class-dot" :style="{background:dc.color}"></span>
              <span class="class-name">{{ dc.name }}</span>
              <span class="class-count">{{ cntCls(dc.id!) }}</span>
            </div>
          </div>
        </div>
        <div class="panel-section" style="flex:1;overflow-y:auto">
          <div class="panel-title">标注列表 ({{ annotations.length }})</div>
          <div v-if="annotations.length===0" class="empty-hint">暂无标注</div>
          <div v-for="(ann,idx) in annotations" :key="idx" :class="['ann-item',{selected:selectedAnnIdx===idx}]" @click="selectAnn(idx)">
            <span class="class-dot" :style="{background:clsColor(ann.class_id)}"></span>
            <span class="ann-label">{{ clsName(ann.class_id) }} #{{ idx+1 }}</span>
            <span class="ann-points">{{ ann.polygon.length }}点</span>
            <el-button type="danger" text size="small" @click.stop="delAnn(idx)"><el-icon><Delete /></el-icon></el-button>
          </div>
        </div>
      </div>
    </div>
    <div class="statusbar">
      <span v-if="currentImage">{{ currentImage.width }}×{{ currentImage.height }}</span>
      <span>标注:{{ annotations.length }}</span>
      <span>缩放:{{ Math.round(zoomLevel*100) }}%</span>
      <span v-if="currentImageIdx>=0">{{ currentImageIdx+1 }}/{{ imageList.length }}</span>
      <span style="margin-left:auto;color:#666">空格+拖拽移动 · 滚轮缩放</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fabric } from 'fabric'
import { projectApi, type DefectClass } from '../api/project'
import { imageApi, type ImageInfo } from '../api/image'
import { annotationApi, type AnnotationData, type Point } from '../api/annotation'

const props = defineProps<{ projectId: string; imageId: string }>()
const router = useRouter()
const rootRef = ref<HTMLElement>()
const currentImageId = ref(parseInt(props.imageId))
const currentImage = ref<ImageInfo|null>(null)
const imageList = ref<ImageInfo[]>([])
const defectClasses = ref<DefectClass[]>([])
const annotations = ref<AnnotationData[]>([])
const selectedClassId = ref<number>(0)
const selectedAnnIdx = ref(-1)
const currentTool = ref('polygon')
const brushSize = ref(2)
const isDrawing = ref(false)
const saving = ref(false)
const saveState = ref<'idle'|'pending'|'saving'|'saved'|'error'>('idle')
const saveStateText = computed(()=>({
  idle:'',pending:'未保存',saving:'保存中…',saved:'已自动保存',error:'保存失败'
}[saveState.value]))
const zoomLevel = ref(1)
const dirty = ref(false)
const spaceDown = ref(false)
const undoStack = ref<string[]>([])
const redoStack = ref<string[]>([])
const canUndo = computed(()=>undoStack.value.length>0)
const canRedo = computed(()=>redoStack.value.length>0)
const currentImageIdx = computed(()=>imageList.value.findIndex(i=>i.id===currentImageId.value))
const hasPrev = computed(()=>currentImageIdx.value>0)
const hasNext = computed(()=>currentImageIdx.value<imageList.value.length-1)
const statusLabel = computed(()=>({unlabeled:'未标注',labeling:'标注中',labeled:'已标注',reviewed:'OK'})[currentImage.value?.status||'']||'')
const statusTagType = computed(()=>({unlabeled:'info',labeling:'warning',labeled:'',reviewed:'success'})[currentImage.value?.status||''] as any||'info')
const showBrushSize = computed(()=>['brush','circle','polyline','eraser'].includes(currentTool.value))
const toolHint = computed(()=>{
  if(spaceDown.value) return '按住空格拖拽移动画布'
  return({
    polygon:isDrawing.value?'点击加顶点·双击/回车完成·Esc取消':'点击开始画多边形',
    rect:'点击拖拽画矩形',
    brush:'按住涂抹·松开生成标注',circle:'点击拖拽画圆',
    polyline:isDrawing.value?'点击加折点·双击/回车完成':'点击开始画折线',
    eraser:'按住涂抹擦除标注区域',boxEraser:'拖拽框选删除',select:'点击标注后可拖动顶点编辑·Ctrl+C复制·Ctrl+V粘贴',
  })[currentTool.value]||''
})
const canvasAreaRef = ref<HTMLElement>()
let canvas:fabric.Canvas|null=null
let drawingPoints:{x:number;y:number}[]=[]
let brushPts:{x:number;y:number}[]=[]
let isBrushing=false
let isErasing=false
let eraserPts:{x:number;y:number}[]=[]
let circleStart:{x:number;y:number}|null=null
let rectStart:{x:number;y:number}|null=null
let boxEraserStart:{x:number;y:number}|null=null
let editHandles:fabric.Circle[]=[]
let clipboard:AnnotationData|null=null
let autoSaveTimer:any=null
let isPanning=false,lastPanX=0,lastPanY=0

// ================================================================
// 栅格化→轮廓提取（涂抹/折线共用）
// ================================================================
function rasterContour(points:{x:number;y:number}[],lw:number,W:number,H:number):Point[]{
  if(points.length<2)return[]
  const pad=lw+2
  let x1=Infinity,y1=Infinity,x2=-Infinity,y2=-Infinity
  for(const p of points){if(p.x<x1)x1=p.x;if(p.y<y1)y1=p.y;if(p.x>x2)x2=p.x;if(p.y>y2)y2=p.y}
  x1=Math.max(0,Math.floor(x1-pad));y1=Math.max(0,Math.floor(y1-pad))
  x2=Math.min(W,Math.ceil(x2+pad));y2=Math.min(H,Math.ceil(y2+pad))
  const cw=x2-x1,ch=y2-y1;if(cw<1||ch<1)return[]
  const cv=document.createElement('canvas');cv.width=cw;cv.height=ch
  const ctx=cv.getContext('2d')!;ctx.fillStyle='#000';ctx.fillRect(0,0,cw,ch)
  ctx.strokeStyle='#FFF';ctx.fillStyle='#FFF';ctx.lineWidth=lw;ctx.lineCap='round';ctx.lineJoin='round'
  ctx.beginPath();ctx.moveTo(points[0].x-x1,points[0].y-y1)
  for(let i=1;i<points.length;i++)ctx.lineTo(points[i].x-x1,points[i].y-y1)
  ctx.stroke()
  for(const p of points){ctx.beginPath();ctx.arc(p.x-x1,p.y-y1,lw/2,0,Math.PI*2);ctx.fill()}
  return scanContour(ctx,cw,ch,x1,y1,W,H)
}

function scanContour(ctx:CanvasRenderingContext2D,cw:number,ch:number,ox:number,oy:number,W:number,H:number):Point[]{
  const d=ctx.getImageData(0,0,cw,ch).data
  const left:{x:number;y:number}[]=[],right:{x:number;y:number}[]=[]
  const step=Math.max(1,Math.floor(ch/200))
  for(let y=0;y<ch;y+=step){
    let lx=-1,rx=-1
    for(let x=0;x<cw;x++){if(d[(y*cw+x)*4]>128){if(lx===-1)lx=x;rx=x}}
    if(lx!==-1){left.push({x:(lx+ox)/W,y:(y+oy)/H});right.push({x:(rx+ox)/W,y:(y+oy)/H})}
  }
  if(left.length<2)return[]
  const poly=[...left,...right.reverse()]
  if(poly.length>120){const s=Math.ceil(poly.length/120);return poly.filter((_,i)=>i%s===0)}
  return poly
}

// ================================================================
// 像素级擦除：栅格化标注→减去擦除笔画→重新提取轮廓
// ================================================================
function subtractEraserFromAnnotations(eraserPath:{x:number;y:number}[],eraserWidth:number){
  if(!currentImage.value||eraserPath.length<2)return
  const W=currentImage.value.width,H=currentImage.value.height
  const pad=eraserWidth+4
  // 擦除路径包围盒
  let ex1=Infinity,ey1=Infinity,ex2=-Infinity,ey2=-Infinity
  for(const p of eraserPath){if(p.x<ex1)ex1=p.x;if(p.y<ey1)ey1=p.y;if(p.x>ex2)ex2=p.x;if(p.y>ey2)ey2=p.y}
  ex1-=pad;ey1-=pad;ex2+=pad;ey2+=pad

  let changed=false
  const newAnns:AnnotationData[]=[]

  for(const ann of annotations.value){
    // 检查标注是否与擦除区域有交集
    let overlap=false
    for(const p of ann.polygon){
      const px=p.x*W,py=p.y*H
      if(px>=ex1&&px<=ex2&&py>=ey1&&py<=ey2){overlap=true;break}
    }
    if(!overlap){newAnns.push(ann);continue}

    // 该标注与擦除区域有交集，需要处理
    // 计算标注的包围盒
    let ax1=Infinity,ay1=Infinity,ax2=-Infinity,ay2=-Infinity
    for(const p of ann.polygon){
      const px=p.x*W,py=p.y*H
      if(px<ax1)ax1=px;if(py<ay1)ay1=py;if(px>ax2)ax2=px;if(py>ay2)ay2=py
    }
    ax1=Math.max(0,Math.floor(ax1-2));ay1=Math.max(0,Math.floor(ay1-2))
    ax2=Math.min(W,Math.ceil(ax2+2));ay2=Math.min(H,Math.ceil(ay2+2))
    const cw=ax2-ax1,ch=ay2-ay1
    if(cw<1||ch<1)continue

    // 创建画布：画标注多边形(白色)，再用擦除笔画减去(黑色)
    const cv=document.createElement('canvas');cv.width=cw;cv.height=ch
    const ctx=cv.getContext('2d')!
    ctx.fillStyle='#000';ctx.fillRect(0,0,cw,ch)

    // 画标注多边形
    ctx.fillStyle='#FFF';ctx.beginPath()
    const pts=ann.polygon.map(p=>({x:p.x*W-ax1,y:p.y*H-ay1}))
    ctx.moveTo(pts[0].x,pts[0].y)
    for(let i=1;i<pts.length;i++)ctx.lineTo(pts[i].x,pts[i].y)
    ctx.closePath();ctx.fill()

    // 用擦除笔画减去（黑色覆盖）
    ctx.globalCompositeOperation='destination-out'
    ctx.strokeStyle='#FFF';ctx.fillStyle='#FFF'
    ctx.lineWidth=eraserWidth;ctx.lineCap='round';ctx.lineJoin='round'
    ctx.beginPath()
    ctx.moveTo(eraserPath[0].x-ax1,eraserPath[0].y-ay1)
    for(let i=1;i<eraserPath.length;i++)ctx.lineTo(eraserPath[i].x-ax1,eraserPath[i].y-ay1)
    ctx.stroke()
    for(const p of eraserPath){ctx.beginPath();ctx.arc(p.x-ax1,p.y-ay1,eraserWidth/2,0,Math.PI*2);ctx.fill()}
    ctx.globalCompositeOperation='source-over'

    // 重新提取轮廓
    const newPoly=scanContour(ctx,cw,ch,ax1,ay1,W,H)
    if(newPoly.length>=3){
      newAnns.push({class_id:ann.class_id,polygon:newPoly})
    }
    // 如果 newPoly 为空，说明标注被完全擦掉了，不加入 newAnns
    changed=true
  }

  if(changed){
    pushUndo()
    annotations.value=newAnns
    dirty.value=true
    renderAnnotations()
    scheduleAutoSave()
  }
}

// ================================================================
// 初始化
// ================================================================
onMounted(async()=>{
  await loadProject();await loadImageList();initCanvas();await loadImageAndAnnotations()
  window.addEventListener('keydown',onKD);window.addEventListener('keyup',onKU)
  window.addEventListener('beforeunload',onBeforeUnload)
  rootRef.value?.focus()
})
onBeforeUnmount(async ()=>{
  // 组件卸载前 flush 未保存改动
  if(dirty.value){try{await handleSave({silent:true,immediate:true})}catch{}}
  if(autoSaveTimer)clearTimeout(autoSaveTimer)
  window.removeEventListener('keydown',onKD);window.removeEventListener('keyup',onKU)
  window.removeEventListener('beforeunload',onBeforeUnload)
  if(canvas)canvas.dispose()
})

function onBeforeUnload(e:BeforeUnloadEvent){
  if(dirty.value){
    e.preventDefault()
    e.returnValue=''
    // 同步发起保存（async 不会等，但浏览器 beacon 可以）
    try{
      const url=`/api/images/${currentImageId.value}/annotations`
      const blob=new Blob([JSON.stringify({annotations:annotations.value})],{type:'application/json'})
      navigator.sendBeacon&&navigator.sendBeacon(url,blob)
    }catch{}
  }
}

async function loadProject(){
  const{data}=await projectApi.get(parseInt(props.projectId))
  defectClasses.value=data.defect_classes
  if(data.defect_classes.length>0)selectedClassId.value=data.defect_classes[0].id!
}
async function loadImageList(){
  const{data}=await imageApi.list(parseInt(props.projectId),{page:1,page_size:999})
  imageList.value=data.items
}

function initCanvas(){
  if(!canvasAreaRef.value)return
  const w=canvasAreaRef.value.clientWidth,h=canvasAreaRef.value.clientHeight
  canvas=new fabric.Canvas('annotationCanvas',{width:w,height:h,backgroundColor:'#2a2a2a',selection:false})

  canvas.on('mouse:wheel',(opt)=>{
    let z=canvas!.getZoom()*(opt.e.deltaY>0?0.92:1.08)
    z=Math.max(0.05,Math.min(30,z))
    canvas!.zoomToPoint({x:opt.e.offsetX,y:opt.e.offsetY} as fabric.Point,z)
    zoomLevel.value=z;opt.e.preventDefault();opt.e.stopPropagation()
  })

  canvas.on('mouse:down',(opt)=>{
    if(spaceDown.value||opt.e.button===2||opt.e.button===1){
      isPanning=true;lastPanX=opt.e.clientX;lastPanY=opt.e.clientY;canvas!.setCursor('grab');return
    }
    if(opt.e.button!==0)return
    const p=canvas!.getPointer(opt.e),tool=currentTool.value
    // select 工具：点 polygon 选中（顶点 handle 由 fabric 自己处理 evented）
    if(tool==='select'){
      const tgt=opt.target as any
      if(tgt&&tgt._ann)selectAnn(tgt._idx)
      else if(tgt&&tgt._handle){/* 让 fabric 处理拖动 */}
      else if(!tgt){selectedAnnIdx.value=-1;removeVertexHandles();highlightSelected()}
      return
    }
    if(tool==='polygon')onPolyClick(p)
    else if(tool==='polyline')onPolylineClick(p)
    else if(tool==='brush'){isBrushing=true;brushPts=[{x:p.x,y:p.y}]}
    else if(tool==='eraser'){isErasing=true;eraserPts=[{x:p.x,y:p.y}]}
    else if(tool==='circle')circleStart={x:p.x,y:p.y}
    else if(tool==='rect')rectStart={x:p.x,y:p.y}
    else if(tool==='boxEraser')boxEraserStart={x:p.x,y:p.y}
  })

  canvas.on('mouse:move',(opt)=>{
    if(isPanning){
      const vpt=canvas!.viewportTransform!
      vpt[4]+=opt.e.clientX-lastPanX;vpt[5]+=opt.e.clientY-lastPanY
      canvas!.requestRenderAll();lastPanX=opt.e.clientX;lastPanY=opt.e.clientY;return
    }
    const p=canvas!.getPointer(opt.e)
    if(currentTool.value==='polygon'&&isDrawing.value)drawTmpLine(p)
    else if(currentTool.value==='polyline'&&isDrawing.value)drawTmpLine(p)
    else if(currentTool.value==='brush'&&isBrushing){brushPts.push({x:p.x,y:p.y});drawDotAt(p,clsColor(selectedClassId.value)+'66')}
    else if(currentTool.value==='eraser'&&isErasing){eraserPts.push({x:p.x,y:p.y});drawDotAt(p,'rgba(255,80,80,0.5)')}
    else if(currentTool.value==='circle'&&circleStart)drawCirclePrev(p)
    else if(currentTool.value==='rect'&&rectStart)drawRectPrev(p)
    else if(currentTool.value==='boxEraser'&&boxEraserStart)drawBoxRect(p)
  })

  canvas.on('mouse:up',(opt)=>{
    if(isPanning){isPanning=false;canvas!.setCursor('default');return}
    const p=canvas!.getPointer(opt.e)
    if(currentTool.value==='brush'&&isBrushing)finishBrush()
    else if(currentTool.value==='eraser'&&isErasing)finishEraser()
    else if(currentTool.value==='circle'&&circleStart)finishCircle(p)
    else if(currentTool.value==='rect'&&rectStart)finishRect(p)
    else if(currentTool.value==='boxEraser'&&boxEraserStart)finishBoxEraser()
  })

  canvas.on('mouse:dblclick',()=>{
    if(currentTool.value==='polygon'&&isDrawing.value)finishPolygon()
    else if(currentTool.value==='polyline'&&isDrawing.value)finishPolyline()
  })
  canvasAreaRef.value.addEventListener('contextmenu',e=>e.preventDefault())
}

function onToolChange(){
  cancelDrawing()
  // 重建 polygon 让 selectable 状态切换（select 工具可拖整体，其他工具不可）
  renderAnnotations()
  // 仅在 select 工具下显示顶点 handle，其他工具关掉避免事件冲突
  if(currentTool.value==='select'){
    if(selectedAnnIdx.value>=0) showVertexHandles(selectedAnnIdx.value)
  }else{
    removeVertexHandles()
  }
}

async function loadImageAndAnnotations(){
  if(!canvas)return
  currentImage.value=imageList.value.find(i=>i.id===currentImageId.value)||null
  removeVertexHandles()
  canvas.clear();canvas.backgroundColor='#2a2a2a'
  const url=imageApi.getFileUrl(currentImageId.value,false)
  fabric.Image.fromURL(url,(img)=>{
    if(!canvas)return
    img.set({selectable:false,evented:false,originX:'left',originY:'top'})
    canvas.add(img);canvas.sendToBack(img);zoomFit()
  },{crossOrigin:'anonymous'})
  try{
    const{data}=await annotationApi.get(currentImageId.value)
    annotations.value=data.map(a=>({
      class_id:a.class_id,
      // 加载时也 clamp，避免历史 VOC 导入的越界数据被原样回写造成 422
      polygon:sanitizePolygon((a.polygon as any[]).map(p => Array.isArray(p) ? {x:p[0],y:p[1]} : {x:p.x,y:p.y}))
    })).filter(a=>a.polygon.length>=3)
    await nextTick();renderAnnotations()
  }catch{annotations.value=[]}
  dirty.value=false;undoStack.value=[];redoStack.value=[];selectedAnnIdx.value=-1
}

function renderAnnotations(){
  if(!canvas||!currentImage.value)return
  canvas.getObjects().filter(o=>(o as any)._ann).forEach(o=>canvas!.remove(o))
  const W=currentImage.value.width,H=currentImage.value.height
  // select 工具下让 polygon 可拖动整体平移（其他工具下保持 evented=true 用于点击选中，但禁拖）
  const isSelectTool=currentTool.value==='select'
  annotations.value.forEach((ann,idx)=>{
    const c=clsColor(ann.class_id)
    const pts=ann.polygon.map(p=>({x:p.x*W,y:p.y*H}))
    const poly=new fabric.Polygon(pts,{
      fill:c+'55',stroke:c,strokeWidth:0.75,
      selectable:isSelectTool,
      hasControls:false,hasBorders:false,
      lockRotation:true,lockScalingX:true,lockScalingY:true,
      hoverCursor:isSelectTool?'move':'default',
      objectCaching:false,
    })
    ;(poly as any)._ann=true
    ;(poly as any)._idx=idx
    // 整体拖动：mousedown 记录原点，moving 同步 handles，modified 应用偏移到数据
    let dragOrigin:{left:number,top:number}|null=null
    poly.on('mousedown',()=>{
      if(currentTool.value!=='select')return
      dragOrigin={left:poly.left||0,top:poly.top||0}
    })
    poly.on('moving',()=>{
      if(!dragOrigin||!currentImage.value)return
      const dx=(poly.left||0)-dragOrigin.left
      const dy=(poly.top||0)-dragOrigin.top
      // 实时同步顶点 handles 跟随
      const W2=currentImage.value.width,H2=currentImage.value.height
      const ann_=annotations.value[idx]
      if(!ann_)return
      editHandles.forEach((h,i)=>{
        const pt=ann_.polygon[i]
        if(!pt)return
        h.set({left:pt.x*W2+dx-6,top:pt.y*H2+dy-6})
        h.setCoords()
      })
      canvas!.requestRenderAll()
    })
    poly.on('modified',()=>{
      if(!dragOrigin||!currentImage.value)return
      const dx=(poly.left||0)-dragOrigin.left
      const dy=(poly.top||0)-dragOrigin.top
      dragOrigin=null
      // 阈值过滤：< 0.5px 视为没动（避免单击也触发 dirty）
      if(Math.abs(dx)<0.5&&Math.abs(dy)<0.5)return
      pushUndo()
      const W2=currentImage.value.width,H2=currentImage.value.height
      annotations.value[idx].polygon=annotations.value[idx].polygon.map(p=>({
        x:Math.max(0,Math.min(1,p.x+dx/W2)),
        y:Math.max(0,Math.min(1,p.y+dy/H2)),
      }))
      dirty.value=true
      scheduleAutoSave()
      // 重建 polygon（让 fabric 的 left/top 复位）+ 重建 handles
      renderAnnotations()
      if(selectedAnnIdx.value===idx) showVertexHandles(idx)
      highlightSelected()
    })
    canvas!.add(poly)
  })
  canvas.requestRenderAll()
}

// ====== 多边形 ======
function onPolyClick(p:{x:number;y:number}){
  if(!isDrawing.value){isDrawing.value=true;drawingPoints=[{x:p.x,y:p.y}]}
  else drawingPoints.push({x:p.x,y:p.y})
  drawDotFixed(p.x,p.y)
}
function finishPolygon(){
  if(!currentImage.value||drawingPoints.length<3){cancelDrawing();return}
  const W=currentImage.value.width,H=currentImage.value.height
  addAnn(drawingPoints.map(p=>({x:p.x/W,y:p.y/H})));cancelDrawing()
}

// ====== 涂抹 ======
function finishBrush(){
  isBrushing=false;cleanTmp()
  if(!currentImage.value||brushPts.length<2)return
  const W=currentImage.value.width,H=currentImage.value.height
  const poly=rasterContour(brushPts,brushSize.value,W,H)
  if(poly.length>=3)addAnn(poly)
}

// ====== 折线 ======
function onPolylineClick(p:{x:number;y:number}){
  if(!isDrawing.value){isDrawing.value=true;drawingPoints=[{x:p.x,y:p.y}]}
  else drawingPoints.push({x:p.x,y:p.y})
  drawDotFixed(p.x,p.y)
}
function finishPolyline(){
  if(!currentImage.value||drawingPoints.length<2){cancelDrawing();return}
  const W=currentImage.value.width,H=currentImage.value.height
  const poly=rasterContour(drawingPoints,brushSize.value,W,H)
  if(poly.length>=3)addAnn(poly);cancelDrawing()
}

// ====== 圆形 ======
function drawCirclePrev(p:{x:number;y:number}){
  if(!canvas||!circleStart)return;cleanTmp()
  const c=clsColor(selectedClassId.value)
  const r=Math.sqrt((p.x-circleStart.x)**2+(p.y-circleStart.y)**2)
  const ci=new fabric.Circle({left:circleStart.x-r,top:circleStart.y-r,radius:r,fill:c+'33',stroke:c,strokeWidth:1,selectable:false,evented:false})
  ;(ci as any)._tmp=true;canvas.add(ci);canvas.requestRenderAll()
}
function finishCircle(p:{x:number;y:number}){
  if(!currentImage.value||!circleStart){circleStart=null;cleanTmp();return}
  const r=Math.sqrt((p.x-circleStart.x)**2+(p.y-circleStart.y)**2)
  if(r<2){circleStart=null;cleanTmp();return}
  const W=currentImage.value.width,H=currentImage.value.height
  const poly:Point[]=[];for(let i=0;i<32;i++){const a=2*Math.PI*i/32;poly.push({x:Math.max(0,Math.min(1,(circleStart.x+r*Math.cos(a))/W)),y:Math.max(0,Math.min(1,(circleStart.y+r*Math.sin(a))/H))})}
  addAnn(poly);circleStart=null;cleanTmp()
}

// ====== 矩形 ======
function drawRectPrev(p:{x:number;y:number}){
  if(!canvas||!rectStart)return;cleanTmp()
  const c=clsColor(selectedClassId.value)
  const x=Math.min(rectStart.x,p.x),y=Math.min(rectStart.y,p.y)
  const w=Math.abs(p.x-rectStart.x),h=Math.abs(p.y-rectStart.y)
  const r=new fabric.Rect({left:x,top:y,width:w,height:h,fill:c+'33',stroke:c,strokeWidth:1,selectable:false,evented:false})
  ;(r as any)._tmp=true;canvas.add(r);canvas.requestRenderAll()
}
function finishRect(p:{x:number;y:number}){
  if(!currentImage.value||!rectStart){rectStart=null;cleanTmp();return}
  const W=currentImage.value.width,H=currentImage.value.height
  const x1=Math.min(rectStart.x,p.x),y1=Math.min(rectStart.y,p.y)
  const x2=Math.max(rectStart.x,p.x),y2=Math.max(rectStart.y,p.y)
  if(x2-x1<3||y2-y1<3){rectStart=null;cleanTmp();return} // 太小忽略
  // 4 点多边形：左上 → 右上 → 右下 → 左下
  const poly:Point[]=[
    {x:x1/W,y:y1/H},{x:x2/W,y:y1/H},{x:x2/W,y:y2/H},{x:x1/W,y:y2/H},
  ]
  addAnn(poly);rectStart=null;cleanTmp()
}

// ====== 像素级擦除 ======
function finishEraser(){
  isErasing=false;cleanTmp()
  if(eraserPts.length<2)return
  subtractEraserFromAnnotations(eraserPts,brushSize.value)
  eraserPts=[]
}

// ====== 框选擦除 ======
function drawBoxRect(p:{x:number;y:number}){
  if(!canvas||!boxEraserStart)return;cleanTmp()
  const x=Math.min(boxEraserStart.x,p.x),y=Math.min(boxEraserStart.y,p.y)
  const r=new fabric.Rect({left:x,top:y,width:Math.abs(p.x-boxEraserStart.x),height:Math.abs(p.y-boxEraserStart.y),fill:'rgba(255,0,0,0.15)',stroke:'#F44',strokeWidth:0.5,strokeDashArray:[4,4],selectable:false,evented:false})
  ;(r as any)._tmp=true;canvas.add(r);canvas.requestRenderAll()
}
function finishBoxEraser(){
  if(!canvas||!boxEraserStart||!currentImage.value){boxEraserStart=null;cleanTmp();return}
  const W=currentImage.value.width,H=currentImage.value.height
  const t=canvas.getObjects().find(o=>(o as any)._tmp&&o.type==='rect') as fabric.Rect
  if(!t){boxEraserStart=null;return}
  const l=(t.left||0)/W,tp=(t.top||0)/H,r=l+(t.width||0)/W,b=tp+(t.height||0)/H
  const rm:number[]=[];annotations.value.forEach((a,i)=>{if(a.polygon.some(p=>p.x>=l&&p.x<=r&&p.y>=tp&&p.y<=b))rm.push(i)})
  if(rm.length>0){pushUndo();for(let i=rm.length-1;i>=0;i--)annotations.value.splice(rm[i],1);dirty.value=true;selectedAnnIdx.value=-1;removeVertexHandles();scheduleAutoSave()}
  boxEraserStart=null;cleanTmp();renderAnnotations()
}

// ====== 标记OK / 取消OK ======
async function markAsOk(){
  if(!currentImage.value)return
  // 清空标注并保存到数据库（OK=无缺陷的负样本）
  pushUndo(); annotations.value=[]; dirty.value=false
  await annotationApi.save(currentImageId.value,[])
  await imageApi.updateStatus(currentImageId.value,'reviewed')
  currentImage.value.status='reviewed'
  const il=imageList.value.find(i=>i.id===currentImageId.value)
  if(il){il.status='reviewed';il.annotation_count=0}
  renderAnnotations(); ElMessage.success('已标记为OK（负样本）')
}
async function unmarkOk(){
  if(!currentImage.value)return
  const newStatus=annotations.value.length>0?'labeled':'unlabeled'
  await imageApi.updateStatus(currentImageId.value,newStatus)
  currentImage.value.status=newStatus
  const il=imageList.value.find(i=>i.id===currentImageId.value)
  if(il)il.status=newStatus
  ElMessage.info('已取消OK标记')
}
async function clearAll(){
  try{await ElMessageBox.confirm('确定清空所有标注？','清空',{confirmButtonText:'清空',cancelButtonText:'取消',type:'warning'})}catch{return}
  pushUndo();annotations.value=[];dirty.value=true;selectedAnnIdx.value=-1;removeVertexHandles();renderAnnotations();scheduleAutoSave()
}

// ====== 通用 ======
/**
 * 将顶点 clamp 到 [0,1]，并去除连续重复点。
 * 确保后端校验 (PointSchema ge=0 le=1) 不会因越界报 422。
 */
function sanitizePolygon(polygon:Point[]):Point[]{
  const out:Point[]=[]
  for(const p of polygon){
    const x=Math.max(0,Math.min(1,Number(p.x)||0))
    const y=Math.max(0,Math.min(1,Number(p.y)||0))
    // 去重相邻完全相同点（避免 0 长度边）
    const last=out[out.length-1]
    if(!last||Math.abs(last.x-x)>1e-6||Math.abs(last.y-y)>1e-6) out.push({x,y})
  }
  return out
}

function addAnn(polygon:Point[]){
  const cleaned=sanitizePolygon(polygon)
  if(cleaned.length<3)return // 至少 3 点
  pushUndo()
  annotations.value.push({class_id:selectedClassId.value,polygon:cleaned})
  dirty.value=true
  renderAnnotations()
  scheduleAutoSave()
}
function drawDotFixed(x:number,y:number){
  if(!canvas)return;const c=clsColor(selectedClassId.value)
  const d=new fabric.Circle({left:x-2,top:y-2,radius:2,fill:'#FFF',stroke:c,strokeWidth:1,selectable:false,evented:false})
  ;(d as any)._tmp=true;canvas.add(d);canvas.requestRenderAll()
}
function drawDotAt(p:{x:number;y:number},color:string){
  if(!canvas)return
  const d=new fabric.Circle({left:p.x-brushSize.value/2,top:p.y-brushSize.value/2,radius:brushSize.value/2,fill:color,selectable:false,evented:false})
  ;(d as any)._tmp=true;canvas.add(d)
}
function drawTmpLine(p:{x:number;y:number}){
  if(!canvas||drawingPoints.length===0)return
  canvas.getObjects().filter(o=>(o as any)._tl).forEach(o=>canvas!.remove(o))
  const last=drawingPoints[drawingPoints.length-1],c=clsColor(selectedClassId.value)
  const ln=new fabric.Line([last.x,last.y,p.x,p.y],{stroke:c,strokeWidth:0.75,strokeDashArray:[5,3],selectable:false,evented:false})
  ;(ln as any)._tmp=true;(ln as any)._tl=true;canvas.add(ln);canvas.requestRenderAll()
}
function cancelDrawing(){isDrawing.value=false;drawingPoints=[];isBrushing=false;brushPts=[];isErasing=false;eraserPts=[];circleStart=null;rectStart=null;boxEraserStart=null;cleanTmp()}
function cleanTmp(){if(!canvas)return;canvas.getObjects().filter(o=>(o as any)._tmp).forEach(o=>canvas!.remove(o));canvas.requestRenderAll()}
function selectAnn(idx:number){
  selectedAnnIdx.value=idx
  highlightSelected()
  // 选中后显示顶点 handles（仅在 select 工具下，避免与其他工具的鼠标事件冲突）
  if(currentTool.value==='select') showVertexHandles(idx)
  else removeVertexHandles()
}

function highlightSelected(){
  if(!canvas)return
  const idx=selectedAnnIdx.value
  canvas.getObjects().forEach(o=>{
    if((o as any)._ann){
      const i=(o as any)._idx
      o.set({strokeWidth:i===idx?1.5:0.75,opacity:idx<0?1:(i===idx?1:0.7)})
    }
  })
  canvas.requestRenderAll()
}

// ====== 顶点编辑（仅 select 工具）======
function showVertexHandles(idx:number){
  removeVertexHandles()
  if(!canvas||!currentImage.value)return
  const ann=annotations.value[idx]
  if(!ann)return
  const W=currentImage.value.width,H=currentImage.value.height
  ann.polygon.forEach((p,i)=>{
    const handle=new fabric.Circle({
      left:p.x*W-3,top:p.y*H-3,radius:3,
      fill:'#fff',stroke:'#409EFF',strokeWidth:1,
      hasControls:false,hasBorders:false,
      selectable:true,evented:true,
      hoverCursor:'move',
      originX:'left',originY:'top',
      lockRotation:true,lockScalingX:true,lockScalingY:true,
    })
    ;(handle as any)._handle=true
    ;(handle as any)._annIdx=idx
    ;(handle as any)._ptIdx=i
    let firstMove=true
    handle.on('mousedown',()=>{firstMove=true})
    handle.on('moving',()=>{
      if(!currentImage.value)return
      // 第一次移动才入栈，避免单击也 push undo
      if(firstMove){pushUndo();firstMove=false}
      const W2=currentImage.value.width,H2=currentImage.value.height
      const cx=(handle.left||0)+3,cy=(handle.top||0)+3
      // clamp 到画布范围（防止越界后端 422）
      const nx=Math.max(0,Math.min(1,cx/W2))
      const ny=Math.max(0,Math.min(1,cy/H2))
      annotations.value[idx].polygon[i]={x:nx,y:ny}
      // 实时更新对应 polygon 形状（不全量重绘，性能更好）
      const polyObj=canvas!.getObjects().find(o=>(o as any)._ann&&(o as any)._idx===idx) as fabric.Polygon|undefined
      if(polyObj){
        const pts=annotations.value[idx].polygon.map(pt=>({x:pt.x*W2,y:pt.y*H2}))
        polyObj.set({points:pts as any})
        ;(polyObj as any)._calcDimensions?.()
        polyObj.setCoords()
        polyObj.dirty=true
      }
      canvas!.requestRenderAll()
    })
    handle.on('modified',()=>{
      if(firstMove)return // 没真的拖动
      dirty.value=true;scheduleAutoSave()
      // 拖动结束后完整重建 polygon 形状 + handles，
      // 避免 fabric 内部 pathOffset/边界不一致导致后续选中显示错位
      renderAnnotations()
      showVertexHandles(idx)
      highlightSelected()
    })
    canvas!.add(handle)
    editHandles.push(handle)
  })
  canvas!.requestRenderAll()
}

function removeVertexHandles(){
  if(!canvas)return
  canvas.getObjects().filter(o=>(o as any)._handle).forEach(o=>canvas!.remove(o))
  editHandles=[]
}

// ====== 复制粘贴 ======
function copyAnn(){
  if(selectedAnnIdx.value<0)return
  const ann=annotations.value[selectedAnnIdx.value]
  if(!ann)return
  clipboard=JSON.parse(JSON.stringify(ann))
  ElMessage.info('已复制')
}
function pasteAnn(){
  if(!clipboard||!currentImage.value)return
  const W=currentImage.value.width,H=currentImage.value.height
  // 像素偏移 20px，转归一化
  const dx=20/W,dy=20/H
  const newPoly=clipboard.polygon.map(p=>({
    x:Math.max(0,Math.min(1,p.x+dx)),
    y:Math.max(0,Math.min(1,p.y+dy)),
  }))
  pushUndo()
  annotations.value.push({class_id:clipboard.class_id,polygon:newPoly})
  dirty.value=true
  selectedAnnIdx.value=annotations.value.length-1
  renderAnnotations()
  if(currentTool.value==='select') showVertexHandles(selectedAnnIdx.value)
  scheduleAutoSave()
  ElMessage.success('已粘贴')
}
function delAnn(idx:number){pushUndo();annotations.value.splice(idx,1);dirty.value=true;selectedAnnIdx.value=-1;removeVertexHandles();renderAnnotations();scheduleAutoSave()}
function pushUndo(){undoStack.value.push(JSON.stringify(annotations.value));redoStack.value=[];if(undoStack.value.length>50)undoStack.value.shift()}
function undo(){if(!canUndo.value)return;redoStack.value.push(JSON.stringify(annotations.value));annotations.value=JSON.parse(undoStack.value.pop()!);dirty.value=true;selectedAnnIdx.value=-1;removeVertexHandles();renderAnnotations();scheduleAutoSave()}
function redo(){if(!canRedo.value)return;undoStack.value.push(JSON.stringify(annotations.value));annotations.value=JSON.parse(redoStack.value.pop()!);dirty.value=true;selectedAnnIdx.value=-1;removeVertexHandles();renderAnnotations();scheduleAutoSave()}

/**
 * 标注变化后调度自动保存（600ms 防抖）。
 * 频繁拖动顶点不会每次都触发请求，最后一次操作 600ms 后才发。
 */
function scheduleAutoSave(){
  if(!dirty.value) return
  saveState.value='pending'
  if(autoSaveTimer) clearTimeout(autoSaveTimer)
  autoSaveTimer=setTimeout(()=>{handleSave({silent:true})},600)
}

async function handleSave(opt:{silent?:boolean;immediate?:boolean}={}){
  if(autoSaveTimer){clearTimeout(autoSaveTimer);autoSaveTimer=null}
  if(saving.value) return // 上一次保存还在进行
  if(!dirty.value && !opt.immediate) return
  const imgId=currentImageId.value
  saving.value=true; saveState.value='saving'
  // 提交前对所有标注做兜底 sanitize：兼容历史 VOC 导入数据中的越界顶点
  // (后端 PointSchema 强制 [0,1]，越界值会 422)
  const safeAnns=annotations.value.map(a=>({
    ...a,
    polygon:sanitizePolygon(a.polygon),
  })).filter(a=>a.polygon.length>=3)
  try{
    await annotationApi.save(imgId,safeAnns)
    // 仅当当前图未切换时才更新状态（防止用户切图后异步回写覆盖新图状态）
    if(imgId===currentImageId.value){
      dirty.value=false
      saveState.value='saved'
      // 2s 后清掉"已保存"提示
      setTimeout(()=>{if(saveState.value==='saved')saveState.value='idle'},2000)
    }
    const il=imageList.value.find(i=>i.id===imgId)
    if(il){
      const cur=currentImage.value
      if(cur?.id===imgId && cur.status!=='reviewed'){
        il.status=annotations.value.length>0?'labeled':'unlabeled'
        cur.status=il.status
      }
      il.annotation_count=annotations.value.length
    }
    if(!opt.silent) ElMessage.success('保存成功')
  }catch(e:any){
    saveState.value='error'
    if(!opt.silent) ElMessage.error('保存失败：'+(e?.response?.data?.detail||e?.message||''))
  }finally{saving.value=false}
}

async function switchImage(id:number){
  // 切图前 flush 自动保存（避免丢失最近改动）
  if(dirty.value){
    try{await handleSave({silent:true,immediate:true})}
    catch{
      try{await ElMessageBox.confirm('保存失败，仍要切换吗？','提示',{confirmButtonText:'丢弃切换',cancelButtonText:'留下',type:'warning'})}
      catch{return}
    }
  }
  removeVertexHandles();selectedAnnIdx.value=-1
  currentImageId.value=id;await loadImageAndAnnotations()
}
function prevImage(){if(hasPrev.value)switchImage(imageList.value[currentImageIdx.value-1].id)}
function nextImage(){if(hasNext.value)switchImage(imageList.value[currentImageIdx.value+1].id)}
function goBack(){router.push(`/project/${props.projectId}`)}
function zoomFit(){
  if(!canvas||!canvasAreaRef.value)return
  const bg=canvas.getObjects().find(o=>!(o as any)._ann&&!(o as any)._tmp);if(!bg)return
  const cw=canvasAreaRef.value.clientWidth,ch=canvasAreaRef.value.clientHeight
  const iw=(bg as fabric.Image).width||1,ih=(bg as fabric.Image).height||1
  const z=Math.min(cw/iw,ch/ih)*0.95
  canvas.setViewportTransform([1,0,0,1,0,0])
  canvas.zoomToPoint(new fabric.Point(cw/2,ch/2),z)
  const vpt=canvas.viewportTransform!;vpt[4]=(cw-iw*z)/2;vpt[5]=(ch-ih*z)/2
  canvas.requestRenderAll();zoomLevel.value=z
}
function onKD(e:KeyboardEvent){
  if(e.code==='Space'){e.preventDefault();spaceDown.value=true}
  else if(e.key==='Escape')cancelDrawing()
  else if(e.key==='Enter'&&isDrawing.value){if(currentTool.value==='polygon')finishPolygon();else if(currentTool.value==='polyline')finishPolyline()}
  else if(e.ctrlKey&&e.key==='z'){e.preventDefault();undo()}
  else if(e.ctrlKey&&e.key==='y'){e.preventDefault();redo()}
  else if(e.ctrlKey&&e.key==='s'){e.preventDefault();handleSave({immediate:true})}
  else if(e.ctrlKey&&(e.key==='c'||e.key==='C')){e.preventDefault();copyAnn()}
  else if(e.ctrlKey&&(e.key==='v'||e.key==='V')){e.preventDefault();pasteAnn()}
  else if(!e.ctrlKey&&(e.key==='a'||e.key==='ArrowLeft'))prevImage()
  else if(!e.ctrlKey&&(e.key==='d'||e.key==='ArrowRight'))nextImage()
}
function onKU(e:KeyboardEvent){if(e.code==='Space')spaceDown.value=false}
function getThumbUrl(id:number){return imageApi.getFileUrl(id,true)}
function clsColor(cid:number){return defectClasses.value.find(c=>c.id===cid)?.color||'#FF0000'}
function clsName(cid:number){return defectClasses.value.find(c=>c.id===cid)?.name||'未知'}
function cntCls(cid:number){return annotations.value.filter(a=>a.class_id===cid).length}
function stText(s:string){return({unlabeled:'未标注',labeling:'标注中',labeled:'已标注',reviewed:'OK'})[s]||s}
function imgSC(img:ImageInfo){return{'sc-u':img.status==='unlabeled','sc-l':img.status==='labeled','sc-r':img.status==='reviewed'}}
let rt:any;window.addEventListener('resize',()=>{clearTimeout(rt);rt=setTimeout(()=>{if(canvas&&canvasAreaRef.value){canvas.setWidth(canvasAreaRef.value.clientWidth);canvas.setHeight(canvasAreaRef.value.clientHeight);zoomFit()}},200)})
</script>

<style scoped>
.annotator{display:flex;flex-direction:column;height:100vh;background:#1a1a1a;color:#ddd;outline:none}
.toolbar{display:flex;align-items:center;justify-content:space-between;padding:6px 12px;background:#2d2d2d;border-bottom:1px solid #444;min-height:48px;gap:8px;flex-wrap:wrap}
.toolbar-left,.toolbar-center,.toolbar-right{display:flex;align-items:center;gap:6px}
.filename{font-weight:500;font-size:14px}
.brush-size-ctrl{display:flex;align-items:center;gap:6px}
.ctrl-label{font-size:12px;color:#aaa}.ctrl-value{font-size:12px;color:#aaa;min-width:36px}
.main-area{display:flex;flex:1;overflow:hidden}
.nav-panel{width:200px;background:#252525;border-right:1px solid #444;display:flex;flex-direction:column}
.nav-header{padding:10px 12px;font-size:13px;font-weight:600;border-bottom:1px solid #333;color:#aaa}
.nav-list{flex:1;overflow-y:auto}
.nav-item{display:flex;align-items:center;gap:8px;padding:6px 8px;cursor:pointer;border-bottom:1px solid #333;border-left:3px solid transparent;transition:all .15s}
.nav-item:hover{background:#333}.nav-item.active{background:#1a3a5c;border-left-color:#409EFF}
.nav-item.sc-u{border-left-color:#555}.nav-item.sc-l{border-left-color:#E6A23C}.nav-item.sc-r{border-left-color:#67C23A}
.nav-thumb{width:48px;height:48px;object-fit:cover;border-radius:4px;background:#333}
.nav-info{flex:1;min-width:0}.nav-filename{font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#ccc}
.nav-status-row{display:flex;align-items:center;gap:4px;margin-top:2px}
.status-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.dot-unlabeled{background:#555}.dot-labeling{background:#E6A23C}.dot-labeled{background:#E6A23C;box-shadow:0 0 4px #E6A23C}.dot-reviewed{background:#67C23A;box-shadow:0 0 4px #67C23A}
.nav-status-text{font-size:10px;color:#999}
.nav-ann-count{font-size:10px;background:#555;color:#eee;padding:0 5px;border-radius:8px;margin-left:auto}
.nav-footer{display:flex;gap:4px;padding:8px;border-top:1px solid #333}
.canvas-area{flex:1;position:relative;overflow:hidden}
.draw-hint{position:absolute;bottom:12px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,.7);color:#eee;padding:6px 16px;border-radius:20px;font-size:12px;pointer-events:none}
.side-panel{width:240px;background:#252525;border-left:1px solid #444;display:flex;flex-direction:column}
.panel-section{border-bottom:1px solid #333}.panel-title{padding:10px 12px;font-size:13px;font-weight:600;color:#aaa}
.class-list{padding:0 8px 10px}
.class-item{display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:6px;cursor:pointer;transition:background .15s}
.class-item:hover{background:#333}.class-item.active{background:#1a3a5c}
.class-dot{width:14px;height:14px;border-radius:3px;flex-shrink:0}.class-name{flex:1;font-size:13px}.class-count{font-size:12px;color:#888}
.empty-hint{padding:20px;text-align:center;color:#666;font-size:13px}
.ann-item{display:flex;align-items:center;gap:6px;padding:6px 12px;cursor:pointer;transition:background .15s}
.ann-item:hover{background:#333}.ann-item.selected{background:#1a3a5c}
.ann-label{flex:1;font-size:12px}.ann-points{font-size:11px;color:#888}
.statusbar{display:flex;gap:24px;padding:4px 16px;background:#2d2d2d;border-top:1px solid #444;font-size:12px;color:#888}
.save-indicator{font-size:12px;min-width:80px;text-align:right;transition:color .2s}
.save-indicator.idle{color:transparent}
.save-indicator.pending{color:#E6A23C}
.save-indicator.saving{color:#909399}
.save-indicator.saved{color:#67C23A}
.save-indicator.error{color:#F56C6C;font-weight:600}
</style>
