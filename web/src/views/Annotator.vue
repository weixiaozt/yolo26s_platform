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
        <el-button v-if="currentImage?.status!=='reviewed'" @click="markAsOk" size="small" type="success">标记OK</el-button>
        <el-button v-else @click="unmarkOk" size="small" type="warning">取消OK</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave"><el-icon><Check /></el-icon> 保存</el-button>
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
const brushSize = ref(10)
const isDrawing = ref(false)
const saving = ref(false)
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
    brush:'按住涂抹·松开生成标注',circle:'点击拖拽画圆',
    polyline:isDrawing.value?'点击加折点·双击/回车完成':'点击开始画折线',
    eraser:'按住涂抹擦除标注区域',boxEraser:'拖拽框选删除',select:'',
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
let boxEraserStart:{x:number;y:number}|null=null
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
  }
}

// ================================================================
// 初始化
// ================================================================
onMounted(async()=>{
  await loadProject();await loadImageList();initCanvas();await loadImageAndAnnotations()
  window.addEventListener('keydown',onKD);window.addEventListener('keyup',onKU)
  rootRef.value?.focus()
})
onBeforeUnmount(()=>{window.removeEventListener('keydown',onKD);window.removeEventListener('keyup',onKU);if(canvas)canvas.dispose()})

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
    if(tool==='polygon')onPolyClick(p)
    else if(tool==='polyline')onPolylineClick(p)
    else if(tool==='brush'){isBrushing=true;brushPts=[{x:p.x,y:p.y}]}
    else if(tool==='eraser'){isErasing=true;eraserPts=[{x:p.x,y:p.y}]}
    else if(tool==='circle')circleStart={x:p.x,y:p.y}
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
    else if(currentTool.value==='boxEraser'&&boxEraserStart)drawBoxRect(p)
  })

  canvas.on('mouse:up',(opt)=>{
    if(isPanning){isPanning=false;canvas!.setCursor('default');return}
    const p=canvas!.getPointer(opt.e)
    if(currentTool.value==='brush'&&isBrushing)finishBrush()
    else if(currentTool.value==='eraser'&&isErasing)finishEraser()
    else if(currentTool.value==='circle'&&circleStart)finishCircle(p)
    else if(currentTool.value==='boxEraser'&&boxEraserStart)finishBoxEraser()
  })

  canvas.on('mouse:dblclick',()=>{
    if(currentTool.value==='polygon'&&isDrawing.value)finishPolygon()
    else if(currentTool.value==='polyline'&&isDrawing.value)finishPolyline()
  })
  canvasAreaRef.value.addEventListener('contextmenu',e=>e.preventDefault())
}

function onToolChange(){cancelDrawing()}

async function loadImageAndAnnotations(){
  if(!canvas)return
  currentImage.value=imageList.value.find(i=>i.id===currentImageId.value)||null
  canvas.clear();canvas.backgroundColor='#2a2a2a'
  const url=imageApi.getFileUrl(currentImageId.value,false)
  fabric.Image.fromURL(url,(img)=>{
    if(!canvas)return
    img.set({selectable:false,evented:false,originX:'left',originY:'top'})
    canvas.add(img);canvas.sendToBack(img);zoomFit()
  },{crossOrigin:'anonymous'})
  try{
    const{data}=await annotationApi.get(currentImageId.value)
    annotations.value=data.map(a=>({class_id:a.class_id,polygon:a.polygon as Point[]}))
    await nextTick();renderAnnotations()
  }catch{annotations.value=[]}
  dirty.value=false;undoStack.value=[];redoStack.value=[];selectedAnnIdx.value=-1
}

function renderAnnotations(){
  if(!canvas||!currentImage.value)return
  canvas.getObjects().filter(o=>(o as any)._ann).forEach(o=>canvas!.remove(o))
  const W=currentImage.value.width,H=currentImage.value.height
  annotations.value.forEach((ann,idx)=>{
    const c=clsColor(ann.class_id)
    const pts=ann.polygon.map(p=>({x:p.x*W,y:p.y*H}))
    const poly=new fabric.Polygon(pts,{fill:c+'55',stroke:c,strokeWidth:1.5,selectable:false,objectCaching:false})
    ;(poly as any)._ann=true;(poly as any)._idx=idx;canvas!.add(poly)
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
  const ci=new fabric.Circle({left:circleStart.x-r,top:circleStart.y-r,radius:r,fill:c+'33',stroke:c,strokeWidth:2,selectable:false,evented:false})
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
  const r=new fabric.Rect({left:x,top:y,width:Math.abs(p.x-boxEraserStart.x),height:Math.abs(p.y-boxEraserStart.y),fill:'rgba(255,0,0,0.15)',stroke:'#F44',strokeWidth:1,strokeDashArray:[4,4],selectable:false,evented:false})
  ;(r as any)._tmp=true;canvas.add(r);canvas.requestRenderAll()
}
function finishBoxEraser(){
  if(!canvas||!boxEraserStart||!currentImage.value){boxEraserStart=null;cleanTmp();return}
  const W=currentImage.value.width,H=currentImage.value.height
  const t=canvas.getObjects().find(o=>(o as any)._tmp&&o.type==='rect') as fabric.Rect
  if(!t){boxEraserStart=null;return}
  const l=(t.left||0)/W,tp=(t.top||0)/H,r=l+(t.width||0)/W,b=tp+(t.height||0)/H
  const rm:number[]=[];annotations.value.forEach((a,i)=>{if(a.polygon.some(p=>p.x>=l&&p.x<=r&&p.y>=tp&&p.y<=b))rm.push(i)})
  if(rm.length>0){pushUndo();for(let i=rm.length-1;i>=0;i--)annotations.value.splice(rm[i],1);dirty.value=true}
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
  pushUndo();annotations.value=[];dirty.value=true;renderAnnotations()
}

// ====== 通用 ======
function addAnn(polygon:Point[]){pushUndo();annotations.value.push({class_id:selectedClassId.value,polygon});dirty.value=true;renderAnnotations()}
function drawDotFixed(x:number,y:number){
  if(!canvas)return;const c=clsColor(selectedClassId.value)
  const d=new fabric.Circle({left:x-4,top:y-4,radius:4,fill:'#FFF',stroke:c,strokeWidth:2,selectable:false,evented:false})
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
  const ln=new fabric.Line([last.x,last.y,p.x,p.y],{stroke:c,strokeWidth:1.5,strokeDashArray:[5,3],selectable:false,evented:false})
  ;(ln as any)._tmp=true;(ln as any)._tl=true;canvas.add(ln);canvas.requestRenderAll()
}
function cancelDrawing(){isDrawing.value=false;drawingPoints=[];isBrushing=false;brushPts=[];isErasing=false;eraserPts=[];circleStart=null;boxEraserStart=null;cleanTmp()}
function cleanTmp(){if(!canvas)return;canvas.getObjects().filter(o=>(o as any)._tmp).forEach(o=>canvas!.remove(o));canvas.requestRenderAll()}
function selectAnn(idx:number){
  selectedAnnIdx.value=idx;if(!canvas)return
  canvas.getObjects().forEach(o=>{if((o as any)._ann)o.set({strokeWidth:(o as any)._idx===idx?3:1.5,opacity:(o as any)._idx===idx?1:0.7})})
  canvas.requestRenderAll()
}
function delAnn(idx:number){pushUndo();annotations.value.splice(idx,1);dirty.value=true;selectedAnnIdx.value=-1;renderAnnotations()}
function pushUndo(){undoStack.value.push(JSON.stringify(annotations.value));redoStack.value=[];if(undoStack.value.length>50)undoStack.value.shift()}
function undo(){if(!canUndo.value)return;redoStack.value.push(JSON.stringify(annotations.value));annotations.value=JSON.parse(undoStack.value.pop()!);dirty.value=true;renderAnnotations()}
function redo(){if(!canRedo.value)return;undoStack.value.push(JSON.stringify(annotations.value));annotations.value=JSON.parse(redoStack.value.pop()!);dirty.value=true;renderAnnotations()}

async function handleSave(){
  saving.value=true
  try{
    await annotationApi.save(currentImageId.value,annotations.value);dirty.value=false;ElMessage.success('保存成功')
    const il=imageList.value.find(i=>i.id===currentImageId.value)
    if(il){
      // 保存时不覆盖 reviewed 状态
      if(currentImage.value?.status!=='reviewed'){
        il.status=annotations.value.length>0?'labeled':'unlabeled'
        if(currentImage.value)currentImage.value.status=il.status
      }
      il.annotation_count=annotations.value.length
    }
  }finally{saving.value=false}
}

async function switchImage(id:number){
  if(dirty.value){try{await ElMessageBox.confirm('未保存，丢弃？','提示',{confirmButtonText:'丢弃',cancelButtonText:'取消',type:'warning'})}catch{return}}
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
  else if(e.ctrlKey&&e.key==='s'){e.preventDefault();handleSave()}
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
</style>
