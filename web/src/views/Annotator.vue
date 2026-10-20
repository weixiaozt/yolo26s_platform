<template>
  <div class="annotator" tabindex="0" ref="rootRef">
    <div class="toolbar" role="region" aria-label="编辑操作区">
      <div class="toolbar-left">
        <el-button text @click="goBack"><el-icon><ArrowLeft /></el-icon> 返回</el-button>
        <el-divider direction="vertical" />
        <span class="filename" :title="currentImage?.filename">{{ currentImage?.filename }}</span>
        <el-tag :type="statusTagType" size="small" style="margin-left:8px">{{ statusLabel }}</el-tag>
      </div>
      <div class="toolbar-center">
        <el-radio-group v-model="currentTool" size="small" @change="onToolChange">
          <el-radio-button label="select" title="选择（快捷键 V）">选择</el-radio-button>
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
          <el-slider v-model="brushSize" :min="1" :max="500" :step="1" style="width:100px" />
          <el-input-number v-model="brushSize" :min="1" :max="500" :step="1" :controls="false" size="small" style="width:64px" />
          <span class="ctrl-value">px</span>
        </div>
        <el-divider direction="vertical" />
        <el-button size="small" :disabled="!canUndo" @click="undo">撤销</el-button>
        <el-button size="small" :disabled="!canRedo" @click="redo">重做</el-button>
        <el-button size="small" @click="zoomFit">适应窗口</el-button>
        <el-button size="small" title="向左旋转90°（仅旋转视图，保存坐标自动换算回原图）" @click="rotateView(-90)"><el-icon><RefreshLeft /></el-icon></el-button>
        <el-button size="small" title="向右旋转90°（快捷键 R）" @click="rotateView(90)"><el-icon><RefreshRight /></el-icon></el-button>
        <el-button size="small" type="danger" :disabled="annotations.length===0" @click="clearAll">清空</el-button>
      </div>
      <div class="toolbar-status">
        <span class="save-indicator" :class="saveState">{{ saveStateText }}</span>
        <el-button v-if="currentImage?.status!=='reviewed'" @click="markAsOk" size="small" type="success">标记OK</el-button>
        <el-button v-else @click="unmarkOk" size="small" type="warning">取消OK</el-button>
      </div>
    </div>
    <div class="inference-toolbar" role="region" aria-label="推理标注功能区">
        <span class="toolbar-section-label">推理模型</span>
        <el-select
          :model-value="inferModels.length ? inferModelIdx : undefined"
          @update:model-value="inferModelIdx=$event"
          size="small"
          class="infer-model-select"
          :disabled="inferModels.length===0"
          :placeholder="inferModels.length ? '选择推理模型' : '暂无可用模型'"
        >
          <el-option v-for="(m,i) in inferModels" :key="i" :label="m.label" :value="i" />
        </el-select>
        <label class="infer-confidence">
          置信度
          <el-input-number v-model="inferConfidence" :min="0" :max="1" :step="0.05"
            :precision="2" :controls="false" size="small" aria-label="推理置信度"
            :disabled="inferLoading" style="width:70px" />
        </label>
        <el-button
          size="small"
          type="primary"
          :loading="inferLoading"
          :disabled="inferModels.length===0 || !currentImage"
          @click="runInferCurrent"
        >
          推理标注
        </el-button>
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
        <div class="panel-section class-section">
          <div class="panel-title">当前类别</div>
          <div class="class-list">
            <div v-for="dc in defectClasses" :key="dc.id" :class="['class-item',{active:selectedClassId===dc.id}]" @click="selectedClassId=dc.id!">
              <span class="class-dot" :style="{background:dc.color}"></span>
              <span class="class-name">{{ dc.name }}</span>
              <span class="class-count">{{ cntCls(dc.id!) }}</span>
            </div>
          </div>
        </div>
        <div class="panel-section annotations-section">
          <div class="panel-title">标注列表 ({{ annotations.length }})</div>
          <div v-if="selectedAnnotation" class="selected-summary" aria-live="polite">
            <span>{{ selectedAnnIndices.size>1 ? `已选 ${selectedAnnIndices.size} 个 · 当前` : '已选' }}</span>
            #{{ selectedAnnIdx+1 }} {{ clsName(selectedAnnotation.class_id) }}
            <span v-if="showConfidence && selectedAnnotation.confidence != null">
              · 推理 {{ formatConfidence(selectedAnnotation.confidence) }}
            </span>
          </div>
          <div class="ann-list" ref="annListRef" role="listbox" aria-label="标注对象" aria-multiselectable="true">
          <div v-if="annotations.length===0" class="empty-hint">暂无标注</div>
          <div v-for="(ann,idx) in annotations" :key="idx" :data-ann-index="idx"
            role="option" :aria-selected="selectedAnnIndices.has(idx)"
            :class="['ann-item',{selected:selectedAnnIndices.has(idx)}]" @click="selectAnn(idx,$event.shiftKey)">
            <span class="class-dot" :style="{background:clsColor(ann.class_id)}"></span>
            <span class="ann-label">
              <span class="ann-name" :title="`#${idx+1} ${clsName(ann.class_id)}`">#{{ idx+1 }} {{ clsName(ann.class_id) }}</span>
              <small v-if="showConfidence && ann.confidence != null" class="ann-confidence">
                推理 {{ formatConfidence(ann.confidence) }}
              </small>
            </span>
            <span class="ann-points">{{ ann.polygon.length }}点</span>
            <el-button type="danger" text size="small" :aria-label="`删除标注 #${idx+1}`" @click.stop="delAnn(idx)"><el-icon><Delete /></el-icon></el-button>
          </div>
          </div>
        </div>
        <div class="panel-section display-options">
          <el-checkbox v-model="showClassNames" title="在图片上显示标注编号和类别名">显示信息</el-checkbox>
          <el-checkbox v-model="showConfidence">显示置信度</el-checkbox>
          <el-checkbox v-model="showAnnotationLayer">显示标注</el-checkbox>
        </div>
      </div>
    </div>
    <div class="statusbar">
      <span v-if="currentImage">{{ currentImage.width }}×{{ currentImage.height }}</span>
      <span>标注:{{ annotations.length }}</span>
      <span>缩放:{{ Math.round(zoomLevel*100) }}%</span>
      <span v-if="viewRot!==0" style="color:#E6A23C">视图旋转:{{ viewRot }}°</span>
      <span v-if="currentImageIdx>=0">{{ currentImageIdx+1 }}/{{ imageList.length }}</span>
      <span class="status-shortcuts">V 选择 · 空格+拖拽平移 · 滚轮缩放 · Ctrl+Z 撤销</span>
      <div v-if="isSegTask" class="seg-view-controls">
        <el-radio-group v-model="imageChannel" size="small" class="channel-radio">
          <el-radio-button label="O">O</el-radio-button>
          <el-radio-button label="R">R</el-radio-button>
          <el-radio-button label="G">G</el-radio-button>
          <el-radio-button label="B">B</el-radio-button>
        </el-radio-group>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// @ts-nocheck — fabric 画布文件动态类型多（fabric 无 .d.ts），跳过严格类型检查，不影响运行
import { ref, onMounted, onBeforeUnmount, computed, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fabric } from 'fabric'
import { projectApi, type DefectClass } from '../api/project'
import { imageApi, type ImageInfo } from '../api/image'
import { annotationApi, type AnnotationData, type Point, type InferenceModelInfo } from '../api/annotation'
import { useAnnotationPreferences } from '../composables/useAnnotationPreferences'
import { pointInPolygon, polygonIntersectsRect, clampGroupDelta } from '../utils/annotationGeometry'

const props = defineProps<{ projectId: string; imageId: string }>()
const router = useRouter()
const rootRef = ref<HTMLElement>()
const currentImageId = ref(parseInt(props.imageId))
const currentImage = ref<ImageInfo|null>(null)
const imageList = ref<ImageInfo[]>([])
const defectClasses = ref<DefectClass[]>([])
const annotations = ref<AnnotationData[]>([])
const projectTaskType = ref<'seg'|'det'|'cls'|'obb'>('seg')
const selectedClassId = ref<number>(0)
const selectedAnnIdx = ref(-1)
const selectedAnnIndices = ref(new Set<number>())
const selectedAnnotation = computed(() => annotations.value[selectedAnnIdx.value])
const annListRef = ref<HTMLElement>()
const currentTool = ref('select')
const brushSize = ref(2)
const { showAnnotations: showAnnotationLayer, showClassNames, showConfidence, inferConfidence } = useAnnotationPreferences()
const imageChannel = ref<'O'|'R'|'G'|'B'>('O')
const inferModels = ref<InferenceModelInfo[]>([])
const inferModelIdx = ref(0)
const inferLoading = ref(false)
const selectedInferModel = computed(() => inferModels.value[inferModelIdx.value] || null)
// 切工具 / 切类别 / 切图 时重置 Shift 追加锚点——避免追加到不相关的旧标注
watch(currentTool,()=>{lastBrushAnnIdx=-1;lastBrushPts=[]})
watch(selectedClassId,()=>{lastBrushAnnIdx=-1;lastBrushPts=[]})
watch(showAnnotationLayer,(visible)=>{
  if(suppressViewControlWatch)return
  if(!visible){
    finishCanvasGesture()
    clearSelection()
    removeVertexHandles()
    cancelDrawing()
    canvas?.discardActiveObject()
  }
  renderAnnotations()
})
watch([showClassNames,showConfidence],()=>canvas?.requestRenderAll())
watch(showConfidence,()=>centerSelectedAnnotation(),{flush:'post'})
watch(selectedAnnIdx,()=>centerSelectedAnnotation(),{flush:'post'})
watch(imageChannel,()=>{
  if(suppressViewControlWatch)return
  if(!isSegTask.value||!currentImage.value)return
  loadCanvasBackground(currentImageId.value,false)
})
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
const isSegTask = computed(()=>projectTaskType.value==='seg')
const showBrushSize = computed(()=>['brush','circle','polyline','eraser'].includes(currentTool.value))
const toolHint = computed(()=>{
  if(!showAnnotationLayer.value)return '标注已隐藏，勾选“显示标注”后可编辑'
  if(spaceDown.value) return '按住空格拖拽移动画布'
  return({
    polygon:isDrawing.value?'点击加顶点·双击/回车完成·Esc取消':'点击开始画多边形',
    rect:'点击拖拽画矩形',
    brush:'按住涂抹·松开生成标注·按住 Shift 涂抹追加到上一段（大缺陷分多笔涂）',circle:'点击拖拽画圆',
    polyline:isDrawing.value?'点击加折点·双击/回车完成':'点击开始画折线',
    eraser:'按住涂抹擦除标注区域',boxEraser:'拖拽框选删除',select:'左拖平移/顶点编辑 · Shift 点选/框选 · Ctrl 拖对象/绿点 · 双击适应窗口',
  })[currentTool.value]||''
})
const canvasAreaRef = ref<HTMLElement>()
let canvas:fabric.Canvas|null=null
let drawingPoints:{x:number;y:number}[]=[]
let brushPts:{x:number;y:number}[]=[]
let isBrushing=false
// Shift 追加：分多笔涂同一个缺陷时，按住 Shift 涂的笔迹会自动合并到上一段
// 而非新建独立 annotation。lastBrushAnnIdx 跟踪上次 brush 落到 annotations
// 数组的位置，lastBrushPts 累积笔迹点序列重新 rasterContour 拟合。
let lastBrushAnnIdx=-1
let lastBrushPts:{x:number;y:number}[]=[]
let isErasing=false
let eraserPts:{x:number;y:number}[]=[]
let circleStart:{x:number;y:number}|null=null
let rectStart:{x:number;y:number}|null=null
let boxEraserStart:{x:number;y:number}|null=null
let editHandles:fabric.Object[]=[]
let clipboard:AnnotationData|null=null   // 始终存原图坐标系（不随视图旋转失效）
let autoSaveTimer:any=null
type CanvasGesture = {
  kind:'pan'|'marquee'|'move'|'vertex'|'rotate'
  start:Point; end:Point; clientStart:Point; viewport:number[]
  hit:number; selectOnClick:boolean; toggle:boolean; moved:boolean
  original:Map<number,Point[]>; snapshot?:string
  pointIndex?:number; center?:Point; angle?:number
}
let canvasGesture:CanvasGesture|null=null
let selectionMarquee:fabric.Rect|null=null
const DRAG_THRESHOLD=4
let bgLoadSeq=0
let suppressViewControlWatch=false

// ================================================================
// 视图旋转：只旋转显示与编辑坐标系，图片文件和 DB 里的标注始终是原图坐标。
// 内存中 annotations 在"显示坐标系"下工作（这样所有绘图工具零改动），
// 加载时 原图→显示，保存时 显示→原图。仅支持 90° 整数倍，换算无损。
// ================================================================
const viewRot=ref(0)                      // 0|90|180|270，顺时针
const rotMap=new Map<number,number>()     // 本次会话内记住每张图的旋转角

function rotPoint(p:Point,rot:number):Point{
  switch(((rot%360)+360)%360){
    case 90:return{x:1-p.y,y:p.x}
    case 180:return{x:1-p.x,y:1-p.y}
    case 270:return{x:p.y,y:1-p.x}
    default:return{x:p.x,y:p.y}
  }
}
const origToDisp=(p:Point)=>rotPoint(p,viewRot.value)
const dispToOrig=(p:Point)=>rotPoint(p,(360-viewRot.value)%360)
function transformAnns(anns:AnnotationData[],fn:(p:Point)=>Point):AnnotationData[]{
  return anns.map(a=>({...a,polygon:a.polygon.map(fn)}))
}
// 显示坐标系下的图像尺寸（旋转 90/270 时宽高互换）
function dispW():number{if(!currentImage.value)return 1;return viewRot.value%180===0?currentImage.value.width:currentImage.value.height}
function dispH():number{if(!currentImage.value)return 1;return viewRot.value%180===0?currentImage.value.height:currentImage.value.width}

// fabric 以对象左上角为原点旋转；旋转后平移，使图像 bbox 左上角回到场景 (0,0)
function placeBgImage(img:fabric.Image){
  const iw=img.width||1,ih=img.height||1
  let left=0,top=0
  if(viewRot.value===90)left=ih
  else if(viewRot.value===180){left=iw;top=ih}
  else if(viewRot.value===270)top=iw
  img.set({angle:viewRot.value,left,top})
  img.setCoords()
}

function makeChannelElement(src:HTMLImageElement,mode:'R'|'G'|'B',done:(el:HTMLImageElement)=>void){
  const w=src.naturalWidth||src.width
  const h=src.naturalHeight||src.height
  const cv=document.createElement('canvas')
  cv.width=w;cv.height=h
  const ctx=cv.getContext('2d')
  if(!ctx){done(src);return}
  try{
    ctx.drawImage(src,0,0,w,h)
    const imgData=ctx.getImageData(0,0,w,h)
    const offset=mode==='R'?0:mode==='G'?1:2
    for(let i=0;i<imgData.data.length;i+=4){
      const v=imgData.data[i+offset]
      imgData.data[i]=v
      imgData.data[i+1]=v
      imgData.data[i+2]=v
    }
    ctx.putImageData(imgData,0,0)
    const out=new Image()
    out.onload=()=>done(out)
    out.src=cv.toDataURL('image/png')
  }catch{
    done(src)
  }
}

function loadCanvasBackground(imageId:number,fit=true){
  if(!canvas)return
  const reqSeq=++bgLoadSeq
  const reqImageId=imageId
  const mode=imageChannel.value
  const url=imageApi.getFileUrl(reqImageId,false)
  const src=new Image()
  src.crossOrigin='anonymous'
  src.onload=()=>{
    if(!canvas||reqSeq!==bgLoadSeq||reqImageId!==currentImageId.value)return
    const addImage=(el:HTMLImageElement)=>{
      if(!canvas||reqSeq!==bgLoadSeq||reqImageId!==currentImageId.value)return
      canvas.getObjects().filter(o=>(o as any)._bg).forEach(o=>canvas!.remove(o))
      const img=new fabric.Image(el,{selectable:false,evented:false,originX:'left',originY:'top'})
      ;(img as any)._bg=true
      placeBgImage(img)
      canvas.add(img)
      canvas.sendToBack(img)
      if(fit)zoomFit()
      else canvas.requestRenderAll()
    }
    if(mode==='O')addImage(src)
    else makeChannelElement(src,mode,addImage)
  }
  src.src=url
}

function rotateView(delta:number){
  if(!canvas||!currentImage.value)return
  finishCanvasGesture()
  cancelDrawing()
  removeVertexHandles()
  const oldRot=viewRot.value
  const newRot=(((oldRot+delta)%360)+360)%360
  // 标注：旧显示坐标系 → 原图坐标系 → 新显示坐标系
  const remap=(p:Point)=>rotPoint(rotPoint(p,(360-oldRot)%360),newRot)
  annotations.value=transformAnns(annotations.value,remap)
  // undo/redo 栈同步换算，避免旋转后撤销跳回旧坐标系
  undoStack.value=undoStack.value.map(s=>JSON.stringify(transformAnns(JSON.parse(s),remap)))
  redoStack.value=redoStack.value.map(s=>JSON.stringify(transformAnns(JSON.parse(s),remap)))
  viewRot.value=newRot
  rotMap.set(currentImageId.value,newRot)
  const bg=canvas.getObjects().find((o:any)=>o._bg) as fabric.Image|undefined
  if(bg)placeBgImage(bg)
  renderAnnotations()
  if(currentTool.value==='select'&&selectedAnnIdx.value>=0)showSelectionHandles()
  zoomFit()
}

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
  // Moore-Neighbor 边界追踪：沿真实轮廓 8 邻接行走，正确处理 U/S/L/C 形涂抹
  // 旧扫描线算法假设每行白像素连续，会把 S 形等的内凹"水平凸包化"，产生填实 bug
  const img=ctx.getImageData(0,0,cw,ch).data
  const m=new Uint8Array(cw*ch)
  for(let i=0;i<cw*ch;i++)if(img[i*4]>128)m[i]=1
  // 起点：row-major 第一个白点（其 N/NW/NE/W 方向必为黑，可直接从 NE 开始顺时针扫）
  let sx=-1,sy=-1
  for(let y=0;y<ch&&sx<0;y++)for(let x=0;x<cw;x++)if(m[y*cw+x]){sx=x;sy=y;break}
  if(sx<0)return[]
  // 方向编号：0:E 1:SE 2:S 3:SW 4:W 5:NW 6:N 7:NE
  const dxs=[1,1,0,-1,-1,-1,0,1],dys=[0,1,1,1,0,-1,-1,-1]
  const path:{x:number;y:number}[]=[{x:sx,y:sy}]
  let cx=sx,cy=sy,prev=6  // 起点 N 邻居为黑（row-major 第一个白点），从 prev+1=NE 开始查
  const maxIter=cw*ch*4
  for(let it=0;it<maxIter;it++){
    let nd=-1
    for(let i=1;i<=8;i++){
      const d_=(prev+i)%8
      const nx=cx+dxs[d_],ny=cy+dys[d_]
      if(nx<0||nx>=cw||ny<0||ny>=ch)continue
      if(m[ny*cw+nx]){nd=d_;cx=nx;cy=ny;break}
    }
    if(nd<0)break  // 孤立像素
    if(cx===sx&&cy===sy)break  // 回到起点
    path.push({x:cx,y:cy})
    prev=(nd+4)%8  // 新的"上一个黑邻居"位于来时方向的反方向
  }
  if(path.length<3)return[]
  // 等距抽稀到 ≤120 点（一像素一点会爆）
  let pts=path
  if(path.length>120){
    const stp=path.length/120
    pts=[]
    for(let i=0;i<120;i++)pts.push(path[Math.floor(i*stp)])
  }
  return pts.map(p=>({x:(p.x+ox)/W,y:(p.y+oy)/H}))
}

// ================================================================
// 像素级擦除：栅格化标注→减去擦除笔画→重新提取轮廓
// ================================================================
function subtractEraserFromAnnotations(eraserPath:{x:number;y:number}[],eraserWidth:number){
  if(!currentImage.value||eraserPath.length<2)return
  const W=dispW(),H=dispH()
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
      newAnns.push({...ann,polygon:newPoly})
    }
    // 如果 newPoly 为空，说明标注被完全擦掉了，不加入 newAnns
    changed=true
  }

  if(changed){
    pushUndo()
    annotations.value=newAnns
    dirty.value=true
    clearSelection()
    renderAnnotations()
    scheduleAutoSave()
  }
}

// ================================================================
// 初始化
// ================================================================
let resizeDebounce:any=null
function onWindowResize(){
  clearTimeout(resizeDebounce)
  resizeDebounce=setTimeout(()=>{
    if(canvas&&canvasAreaRef.value){
      canvas.setWidth(canvasAreaRef.value.clientWidth)
      canvas.setHeight(canvasAreaRef.value.clientHeight)
      zoomFit()
    }
  },200)
}

onMounted(async()=>{
  await loadProject();await loadInferModels();await loadImageList();initCanvas();await loadImageAndAnnotations()
  document.fonts.load('12px "ChillRoundF"')
    .then(()=>canvas?.requestRenderAll())
    .catch(error=>console.warn('标注圆体字体加载失败，使用系统字体',error))
  window.addEventListener('keydown',onKD);window.addEventListener('keyup',onKU)
  window.addEventListener('beforeunload',onBeforeUnload)
  window.addEventListener('resize',onWindowResize)
  window.addEventListener('blur',onWindowBlur)
  rootRef.value?.focus()
})
onBeforeUnmount(async ()=>{
  finishCanvasGesture()
  // 组件卸载前 flush 未保存改动
  if(dirty.value){try{await handleSave({silent:true,immediate:true})}catch{}}
  if(autoSaveTimer)clearTimeout(autoSaveTimer)
  if(resizeDebounce)clearTimeout(resizeDebounce)
  window.removeEventListener('keydown',onKD);window.removeEventListener('keyup',onKU)
  window.removeEventListener('beforeunload',onBeforeUnload)
  window.removeEventListener('resize',onWindowResize)
  window.removeEventListener('blur',onWindowBlur)
  if(canvas)canvas.dispose()
})

function onBeforeUnload(e:BeforeUnloadEvent){
  finishCanvasGesture()
  if(dirty.value){
    e.preventDefault()
    e.returnValue=''
    // 同步发起保存（async 不会等，但浏览器 beacon 可以）
    try{
      const url=`/api/images/${currentImageId.value}/annotations`
      // beacon 同样要换算回原图坐标系
      const blob=new Blob([JSON.stringify({annotations:transformAnns(annotations.value,dispToOrig)})],{type:'application/json'})
      navigator.sendBeacon&&navigator.sendBeacon(url,blob)
    }catch{}
  }
}

async function loadProject(){
  const{data}=await projectApi.get(parseInt(props.projectId))
  projectTaskType.value=(data.task_type||'seg') as 'seg'|'det'|'cls'|'obb'
  defectClasses.value=data.defect_classes
  if(data.defect_classes.length>0)selectedClassId.value=data.defect_classes[0].id!
}
async function loadImageList(){
  const{data}=await imageApi.list(parseInt(props.projectId),{page:1,page_size:999})
  imageList.value=data.items
}

async function loadInferModels(){
  try{
    const{data}=await annotationApi.listInferenceModels(parseInt(props.projectId))
    inferModels.value=data.filter(m=>m.model_format==='pytorch'&&m.model_path?.endsWith('.pt'))
    inferModelIdx.value=0
  }catch{
    inferModels.value=[]
  }
}

async function runInferCurrent(){
  if(inferLoading.value)return
  if(!currentImage.value)return
  if(!Number.isFinite(inferConfidence.value)||inferConfidence.value<0||inferConfidence.value>1){
    ElMessage.warning('请输入 0～1 之间的推理置信度')
    return
  }
  if(!selectedInferModel.value){
    ElMessage.warning('当前项目没有可用的 best.pt 模型')
    return
  }
  inferLoading.value=true
  const requestImageId=currentImageId.value
  try{
    const m=selectedInferModel.value
    const{data}=await annotationApi.inferCurrent({
      image_id:currentImageId.value,
      project_id:parseInt(props.projectId),
      task_id:m.task_id,
      model_path:m.model_path,
      conf:inferConfidence.value,
    })
    if(requestImageId!==currentImageId.value){
      ElMessage.info('已切换图片，未写入上一张图片的推理结果')
      return
    }
    if(!data.annotations.length){
      ElMessage.info(data.skipped?`没有可用结果，跳过 ${data.skipped} 个未匹配类别`:'未检出缺陷')
      return
    }
    const inferred=data.annotations.map(a=>({
      class_id:a.class_id,
      polygon:sanitizePolygon(a.polygon).map(origToDisp),
      bbox:a.bbox,
      area:a.area,
      confidence:a.confidence,
    }))
    if(!(await ensureCanAddDefect()))return

    let mode:'replace'|'append'=annotations.value.length>0?'append':'replace'
    if(annotations.value.length>0){
      try{
        await ElMessageBox.confirm(
          `推理得到 ${inferred.length} 个标注。请选择写入方式。`,
          '推理标注',
          {
            confirmButtonText:'替换当前标注',
            cancelButtonText:'追加到当前标注',
            distinguishCancelAndClose:true,
            type:'warning',
          },
        )
        mode='replace'
      }catch(action:any){
        if(action==='cancel')mode='append'
        else return
      }
    }

    if(requestImageId!==currentImageId.value)return
    pushUndo()
    annotations.value=mode==='replace'?inferred:[...annotations.value,...inferred]
    setLocalImageStatus('labeled',annotations.value.length)
    dirty.value=true
    clearSelection()
    removeVertexHandles()
    renderAnnotations()
    scheduleAutoSave()
    ElMessage.success(`已生成 ${inferred.length} 个推理标注${data.skipped?`，跳过 ${data.skipped} 个`:''}`)
  }catch(e:any){
    ElMessage.error(e?.response?.data?.detail||'推理标注失败')
  }finally{
    inferLoading.value=false
  }
}

function initCanvas(){
  if(!canvasAreaRef.value)return
  const w=canvasAreaRef.value.clientWidth,h=canvasAreaRef.value.clientHeight
  canvas=new fabric.Canvas('annotationCanvas',{width:w,height:h,backgroundColor:'#2a2a2a',selection:false,fireRightClick:true,fireMiddleClick:true})
  canvas.on('after:render',drawAnnotationLabels)

  canvas.on('mouse:wheel',(opt)=>{
    if(canvasGesture){opt.e.preventDefault();return}
    let z=canvas!.getZoom()*(opt.e.deltaY>0?0.92:1.08)
    z=Math.max(0.05,Math.min(30,z))
    canvas!.zoomToPoint({x:opt.e.offsetX,y:opt.e.offsetY} as fabric.Point,z)
    zoomLevel.value=z;opt.e.preventDefault();opt.e.stopPropagation()
  })

  canvas.on('mouse:down',(opt)=>{
    rootRef.value?.focus({preventScroll:true})
    if(spaceDown.value||opt.e.button===2||opt.e.button===1){
      beginCanvasGesture(opt,true);return
    }
    if(opt.e.button!==0)return
    const p=canvas!.getPointer(opt.e),tool=currentTool.value
    if(tool==='select'){
      beginCanvasGesture(opt);return
    }
    if(!showAnnotationLayer.value)return
    if(tool==='polygon')onPolyClick(p)
    else if(tool==='polyline')onPolylineClick(p)
    else if(tool==='brush'){isBrushing=true;brushPts=[{x:p.x,y:p.y}]}
    else if(tool==='eraser'){isErasing=true;eraserPts=[{x:p.x,y:p.y}]}
    else if(tool==='circle')circleStart={x:p.x,y:p.y}
    else if(tool==='rect')rectStart={x:p.x,y:p.y}
    else if(tool==='boxEraser')boxEraserStart={x:p.x,y:p.y}
  })

  canvas.on('mouse:move',(opt)=>{
    if(canvasGesture){moveCanvasGesture(opt.e);return}
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
    if(canvasGesture){moveCanvasGesture(opt.e);finishCanvasGesture();return}
    const p=canvas!.getPointer(opt.e)
    if(currentTool.value==='brush'&&isBrushing)finishBrush(!!(opt.e as any).shiftKey)
    else if(currentTool.value==='eraser'&&isErasing)finishEraser()
    else if(currentTool.value==='circle'&&circleStart)finishCircle(p)
    else if(currentTool.value==='rect'&&rectStart)finishRect(p)
    else if(currentTool.value==='boxEraser'&&boxEraserStart)finishBoxEraser()
  })

  canvas.on('mouse:dblclick',()=>{
    if(currentTool.value==='select')zoomFit()
    else if(currentTool.value==='polygon'&&isDrawing.value)finishPolygon()
    else if(currentTool.value==='polyline'&&isDrawing.value)finishPolyline()
  })
  canvasAreaRef.value.addEventListener('contextmenu',e=>e.preventDefault())
}

function hitAnnotation(p:Point, selectedOnly=false){
  if(!showAnnotationLayer.value)return -1
  const normalized={x:p.x/dispW(),y:p.y/dispH()}
  for(let i=annotations.value.length-1;i>=0;i--){
    if(selectedOnly&&!selectedAnnIndices.value.has(i))continue
    if(pointInPolygon(normalized,annotations.value[i].polygon))return i
  }
  return -1
}

function hitSelectionHandle(p:Point,target:any){
  if(!showAnnotationLayer.value||!canvas)return null
  if(target?._rotHandle)return target
  // 小顶点保留 1 个屏幕像素的点击余量，密集处取最近点，避免命中后绘制的邻点。
  let nearest:any=null,best=Infinity
  for(let i=editHandles.length-1;i>=0;i--){
    const handle=editHandles[i] as any
    if(handle._ptIdx===undefined)continue
    const point=annotations.value[handle._annIdx]?.polygon[handle._ptIdx]
    if(!point)continue
    const distance=Math.hypot(p.x-point.x*dispW(),p.y-point.y*dispH())*canvas.getZoom()
    const radius=(handle.radius+handle.strokeWidth/2)*canvas.getZoom()+1
    if(distance<=radius&&distance<best){nearest=handle;best=distance}
  }
  return nearest
}

function beginCanvasGesture(opt:any,forcePan=false){
  if(!canvas||!currentImage.value||canvasGesture)return
  const e=opt.e,p=canvas.getPointer(e),target=opt.target
  const handle=hitSelectionHandle(p,target)
  const hit=handle?handle._annIdx:hitAnnotation(p)
  const selectedHit=handle&&!handle._rotHandle?handle._annIdx:hitAnnotation(p,true)
  let kind:CanvasGesture['kind']='pan'
  // 固定本次手势：Shift 框选；Ctrl 拖顶点也只移动整组；普通左拖顶点才修点。
  if(!forcePan&&showAnnotationLayer.value){
    if(e.shiftKey)kind='marquee'
    else if(e.ctrlKey&&handle?._rotHandle)kind='rotate'
    else if(e.ctrlKey&&selectedHit>=0)kind='move'
    else if(!e.ctrlKey&&handle&&!handle._rotHandle)kind='vertex'
  }
  const g:CanvasGesture={
    kind,start:p,end:p,clientStart:{x:e.clientX,y:e.clientY},viewport:[...canvas.viewportTransform!],
    hit,selectOnClick:!forcePan&&showAnnotationLayer.value,toggle:!!e.shiftKey,moved:false,original:new Map(),
  }
  if(['move','vertex','rotate'].includes(kind)){
    g.snapshot=JSON.stringify(annotations.value)
    const indices=kind==='move'?[...selectedAnnIndices.value]:[handle._annIdx]
    indices.forEach(idx=>g.original.set(idx,annotations.value[idx].polygon.map(p=>({...p}))))
    if(kind==='move')selectedAnnIdx.value=selectedHit
    if(kind!=='move'){
      selectedAnnIdx.value=handle._annIdx
      g.hit=handle._annIdx
      g.pointIndex=handle._ptIdx
      const points=g.original.get(g.hit)!
      g.center={x:points.reduce((s,p)=>s+p.x,0)/points.length*dispW(),y:points.reduce((s,p)=>s+p.y,0)/points.length*dispH()}
      g.angle=Math.atan2(p.y-g.center.y,p.x-g.center.x)
    }
    // 不能在拖动半途自动保存；松开后统一提交，并只生成一个撤销记录。
    if(autoSaveTimer){clearTimeout(autoSaveTimer);autoSaveTimer=null}
  }
  canvasGesture=g
}

function moveCanvasGesture(e:MouseEvent){
  const g=canvasGesture
  if(!canvas||!g)return
  const dx=e.clientX-g.clientStart.x,dy=e.clientY-g.clientStart.y
  if(!g.moved&&Math.hypot(dx,dy)<DRAG_THRESHOLD)return
  g.moved=true
  if(g.kind==='pan'){
    const vpt=[...g.viewport]
    vpt[4]+=dx;vpt[5]+=dy
    canvas.setViewportTransform(vpt)
    canvas.setCursor('grabbing')
    canvas.requestRenderAll()
    return
  }
  // 视口在非平移手势中固定，使用起始像素差，避免 Fabric 缓存指针带来的偏差。
  const p={x:g.start.x+dx/g.viewport[0],y:g.start.y+dy/g.viewport[3]}
  g.end=p
  if(g.kind==='marquee'){
    if(!selectionMarquee){
      selectionMarquee=new fabric.Rect({fill:'rgba(64,158,255,.12)',stroke:'#409eff',selectable:false,evented:false})
      canvas.add(selectionMarquee)
    }
    selectionMarquee.set({
      left:Math.min(g.start.x,p.x),top:Math.min(g.start.y,p.y),
      width:Math.abs(p.x-g.start.x),height:Math.abs(p.y-g.start.y),
      strokeWidth:1/canvas.getZoom(),strokeDashArray:[5/canvas.getZoom(),3/canvas.getZoom()],
    })
    canvas.setCursor('crosshair');canvas.requestRenderAll()
    return
  }
  const W=dispW(),H=dispH()
  if(g.kind==='move'){
    const delta=clampGroupDelta([...g.original.values()],{x:(p.x-g.start.x)/W,y:(p.y-g.start.y)/H})
    g.original.forEach((polygon,idx)=>{
      annotations.value[idx].polygon=polygon.map(pt=>({x:pt.x+delta.x,y:pt.y+delta.y}))
    })
  }else if(g.kind==='vertex'){
    const polygon=g.original.get(g.hit)!.map(pt=>({...pt}))
    const original=polygon[g.pointIndex!]
    polygon[g.pointIndex!]={x:Math.max(0,Math.min(1,original.x+(p.x-g.start.x)/W)),y:Math.max(0,Math.min(1,original.y+(p.y-g.start.y)/H))}
    annotations.value[g.hit].polygon=polygon
  }else if(g.kind==='rotate'){
    const center=g.center!,angle=Math.atan2(p.y-center.y,p.x-center.x)-g.angle!
    const cos=Math.cos(angle),sin=Math.sin(angle)
    annotations.value[g.hit].polygon=g.original.get(g.hit)!.map(pt=>{
      const x=pt.x*W-center.x,y=pt.y*H-center.y
      return {x:Math.max(0,Math.min(1,(center.x+x*cos-y*sin)/W)),y:Math.max(0,Math.min(1,(center.y+x*sin+y*cos)/H))}
    })
  }
  // 按当前坐标重建轮廓和手柄，保证 pathOffset、边界与命中区域始终一致。
  renderAnnotations()
  showSelectionHandles()
  canvas.setCursor(g.kind==='rotate'?'crosshair':'move')
}

function finishCanvasGesture(cancel=false){
  const g=canvasGesture
  if(!g||!canvas)return
  canvasGesture=null
  if(selectionMarquee){canvas.remove(selectionMarquee);selectionMarquee=null}
  canvas.setCursor('default')
  if(g.snapshot){
    if(cancel){
      g.original.forEach((polygon,idx)=>{annotations.value[idx].polygon=polygon})
    }else if(g.snapshot!==JSON.stringify(annotations.value)){
      pushUndo(g.snapshot)
      dirty.value=true
    }
    renderAnnotations();showSelectionHandles()
    if(dirty.value)scheduleAutoSave()
  }else if(!cancel&&g.selectOnClick){
    if(g.moved&&g.kind==='marquee'){
      const start={x:g.start.x/dispW(),y:g.start.y/dispH()},end={x:g.end.x/dispW(),y:g.end.y/dispH()}
      const hits=annotations.value.flatMap((ann,idx)=>polygonIntersectsRect(ann.polygon,start,end)?[idx]:[])
      if(hits.length)applySelection(new Set([...selectedAnnIndices.value,...hits]),hits[hits.length-1])
    }else if(!g.moved){
      if(g.hit>=0)selectAnn(g.hit,g.toggle)
      else if(!g.toggle)clearSelection()
    }
  }
}

function onWindowBlur(){
  spaceDown.value=false
  finishCanvasGesture()
}

function onToolChange(){
  finishCanvasGesture()
  cancelDrawing()
  // 手势由选择工具统一管理，其他绘制工具保持原来的绘制逻辑。
  renderAnnotations()
  // 仅在 select 工具下显示顶点 handle，其他工具关掉避免事件冲突
  if(currentTool.value==='select'){
    if(selectedAnnIdx.value>=0) showSelectionHandles()
  }else{
    removeVertexHandles()
  }
}

async function loadImageAndAnnotations(){
  if(!canvas)return
  currentImage.value=imageList.value.find(i=>i.id===currentImageId.value)||null
  viewRot.value=rotMap.get(currentImageId.value)??0
  suppressViewControlWatch=true
  imageChannel.value='O'
  suppressViewControlWatch=false
  removeVertexHandles()
  canvas.clear();canvas.backgroundColor='#2a2a2a'
  // 锁定本次请求对应的 imageId；如果用户在 await 期间切了图，丢弃这次返回，
  // 否则旧请求的标注会把新图覆盖（实际表现：切到新图却显示前一张的标注）
  const reqImageId=currentImageId.value
  loadCanvasBackground(reqImageId,true)
  try{
    const{data}=await annotationApi.get(reqImageId)
    if(reqImageId!==currentImageId.value)return  // 切图了，本次响应作废
    annotations.value=data.map(a=>({
      class_id:a.class_id,
      confidence:a.confidence,
      // 加载时也 clamp，避免历史 VOC 导入的越界数据被原样回写造成 422；
      // 再从原图坐标系换算到当前显示坐标系（viewRot=0 时为恒等）
      polygon:sanitizePolygon((a.polygon as any[]).map(p => Array.isArray(p) ? {x:p[0],y:p[1]} : {x:p.x,y:p.y})).map(origToDisp)
    })).filter(a=>a.polygon.length>=3)
    await nextTick()
    if(reqImageId!==currentImageId.value)return  // nextTick 后还得再确认一次
    renderAnnotations()
  }catch{
    if(reqImageId===currentImageId.value) annotations.value=[]
  }
  if(reqImageId!==currentImageId.value)return
  dirty.value=false;undoStack.value=[];redoStack.value=[];clearSelection()
}

function renderAnnotations(){
  if(!canvas||!currentImage.value)return
  canvas.getObjects().filter(o=>(o as any)._ann).forEach(o=>canvas!.remove(o))
  if(!showAnnotationLayer.value){
    removeVertexHandles()
    canvas.requestRenderAll()
    return
  }
  const W=dispW(),H=dispH()
  // 禁用 Fabric 原生拖动，避免和画布平移、Ctrl 编辑手势同时生效。
  const isSelectTool=currentTool.value==='select'
  annotations.value.forEach((ann,idx)=>{
    const c=clsColor(ann.class_id)
    const pts=ann.polygon.map(p=>({x:p.x*W,y:p.y*H}))
    const poly=new fabric.Polygon(pts,{
      fill:c+'55',stroke:c,strokeWidth:0.375,
      selectable:false,
      hasControls:false,hasBorders:false,
      lockRotation:true,lockScalingX:true,lockScalingY:true,
      hoverCursor:isSelectTool?'grab':'default',
      objectCaching:false,
    })
    ;(poly as any)._ann=true
    ;(poly as any)._idx=idx
    canvas!.add(poly)
  })
  highlightSelected()
}

// ====== 多边形 ======
function onPolyClick(p:{x:number;y:number}){
  if(!isDrawing.value){isDrawing.value=true;drawingPoints=[{x:p.x,y:p.y}]}
  else drawingPoints.push({x:p.x,y:p.y})
  drawDotFixed(p.x,p.y)
}
async function finishPolygon(){
  if(!currentImage.value||drawingPoints.length<3){cancelDrawing();return}
  if(!(await ensureCanAddDefect())){cancelDrawing();return}
  const W=dispW(),H=dispH()
  addAnn(drawingPoints.map(p=>({x:p.x/W,y:p.y/H})));cancelDrawing()
}

// ====== 涂抹 ======
async function finishBrush(append:boolean=false){
  isBrushing=false;cleanTmp()
  if(!currentImage.value||brushPts.length<2)return
  if(!(await ensureCanAddDefect())){brushPts=[];return}
  const W=dispW(),H=dispH()
  // Shift 追加：拼接上次笔迹 + 本次笔迹，重新 rasterContour 拟合（rasterContour
  // 会在两笔末尾与下一笔开头之间画连线，自动桥接两段）。仅当上次 brush
  // annotation 仍在且同类时生效。
  if(append&&lastBrushAnnIdx>=0&&lastBrushAnnIdx<annotations.value.length
     &&annotations.value[lastBrushAnnIdx].class_id===selectedClassId.value
     &&lastBrushPts.length>0){
    const combined=[...lastBrushPts,...brushPts]
    const poly=rasterContour(combined,brushSize.value,W,H)
    if(poly.length>=3){
      pushUndo()
      annotations.value[lastBrushAnnIdx]={class_id:selectedClassId.value,polygon:sanitizePolygon(poly)}
      lastBrushPts=combined
      dirty.value=true
      renderAnnotations()
      scheduleAutoSave()
      brushPts=[]
      return
    }
  }
  const poly=rasterContour(brushPts,brushSize.value,W,H)
  if(poly.length>=3){
    addAnn(poly)
    lastBrushAnnIdx=annotations.value.length-1
    lastBrushPts=[...brushPts]
  }
  brushPts=[]
}

// ====== 折线 ======
function onPolylineClick(p:{x:number;y:number}){
  if(!isDrawing.value){isDrawing.value=true;drawingPoints=[{x:p.x,y:p.y}]}
  else drawingPoints.push({x:p.x,y:p.y})
  drawDotFixed(p.x,p.y)
}
async function finishPolyline(){
  if(!currentImage.value||drawingPoints.length<2){cancelDrawing();return}
  if(!(await ensureCanAddDefect())){cancelDrawing();return}
  const W=dispW(),H=dispH()
  const poly=rasterContour(drawingPoints,brushSize.value,W,H)
  if(poly.length>=3)addAnn(poly);cancelDrawing()
}

// ====== 圆形 ======
function drawCirclePrev(p:{x:number;y:number}){
  if(!canvas||!circleStart)return;cleanTmp()
  const c=clsColor(selectedClassId.value)
  const r=Math.sqrt((p.x-circleStart.x)**2+(p.y-circleStart.y)**2)
  const ci=new fabric.Circle({left:circleStart.x-r,top:circleStart.y-r,radius:r,fill:c+'33',stroke:c,strokeWidth:0.5,selectable:false,evented:false})
  ;(ci as any)._tmp=true;canvas.add(ci);canvas.requestRenderAll()
}
async function finishCircle(p:{x:number;y:number}){
  if(!currentImage.value||!circleStart){circleStart=null;cleanTmp();return}
  const r=Math.sqrt((p.x-circleStart.x)**2+(p.y-circleStart.y)**2)
  if(r<2){circleStart=null;cleanTmp();return}
  if(!(await ensureCanAddDefect())){circleStart=null;cleanTmp();return}
  const W=dispW(),H=dispH()
  const poly:Point[]=[];for(let i=0;i<32;i++){const a=2*Math.PI*i/32;poly.push({x:Math.max(0,Math.min(1,(circleStart.x+r*Math.cos(a))/W)),y:Math.max(0,Math.min(1,(circleStart.y+r*Math.sin(a))/H))})}
  addAnn(poly);circleStart=null;cleanTmp()
}

// ====== 矩形 ======
function drawRectPrev(p:{x:number;y:number}){
  if(!canvas||!rectStart)return;cleanTmp()
  const c=clsColor(selectedClassId.value)
  const x=Math.min(rectStart.x,p.x),y=Math.min(rectStart.y,p.y)
  const w=Math.abs(p.x-rectStart.x),h=Math.abs(p.y-rectStart.y)
  const r=new fabric.Rect({left:x,top:y,width:w,height:h,fill:c+'33',stroke:c,strokeWidth:0.5,selectable:false,evented:false})
  ;(r as any)._tmp=true;canvas.add(r);canvas.requestRenderAll()
}
async function finishRect(p:{x:number;y:number}){
  if(!currentImage.value||!rectStart){rectStart=null;cleanTmp();return}
  const W=dispW(),H=dispH()
  const x1=Math.min(rectStart.x,p.x),y1=Math.min(rectStart.y,p.y)
  const x2=Math.max(rectStart.x,p.x),y2=Math.max(rectStart.y,p.y)
  if(x2-x1<3||y2-y1<3){rectStart=null;cleanTmp();return} // 太小忽略
  // 4 点多边形：左上 → 右上 → 右下 → 左下
  if(!(await ensureCanAddDefect())){rectStart=null;cleanTmp();return}
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
  const W=dispW(),H=dispH()
  const t=canvas.getObjects().find(o=>(o as any)._tmp&&o.type==='rect') as fabric.Rect
  if(!t){boxEraserStart=null;return}
  const l=(t.left||0)/W,tp=(t.top||0)/H,r=l+(t.width||0)/W,b=tp+(t.height||0)/H
  const rm:number[]=[];annotations.value.forEach((a,i)=>{if(a.polygon.some(p=>p.x>=l&&p.x<=r&&p.y>=tp&&p.y<=b))rm.push(i)})
  if(rm.length>0){pushUndo();for(let i=rm.length-1;i>=0;i--)annotations.value.splice(rm[i],1);dirty.value=true;clearSelection();removeVertexHandles();scheduleAutoSave()}
  boxEraserStart=null;cleanTmp();renderAnnotations()
}

// ====== 标记OK / 取消OK ======
function setLocalImageStatus(status:ImageInfo['status'], annotationCount=annotations.value.length){
  if(currentImage.value){
    currentImage.value.status=status
    currentImage.value.annotation_count=annotationCount
  }
  const il=imageList.value.find(i=>i.id===currentImageId.value)
  if(il){
    il.status=status
    il.annotation_count=annotationCount
  }
}

async function ensureCanAddDefect(){
  if(currentImage.value?.status!=='reviewed')return true
  try{
    await ElMessageBox.confirm(
      '当前图片已标记为 OK，添加缺陷会取消 OK 状态，并按缺陷样本参与训练。是否继续？',
      '取消 OK 标记',
      {confirmButtonText:'继续标注缺陷',cancelButtonText:'取消',type:'warning'},
    )
    setLocalImageStatus(annotations.value.length>0?'labeled':'unlabeled')
    return true
  }catch{
    return false
  }
}

async function markAsOk(){
  if(!currentImage.value)return
  if(annotations.value.length>0){
    try{
      await ElMessageBox.confirm(
        `当前已有 ${annotations.value.length} 个缺陷标注。标记 OK 会清空这些标注，并按 OK 负样本参与训练。是否继续？`,
        '标记 OK',
        {confirmButtonText:'清空并标记 OK',cancelButtonText:'取消',type:'warning'},
      )
    }catch{return}
  }
  // 清空标注并保存到数据库（OK=无缺陷的负样本）
  pushUndo(); annotations.value=[]; dirty.value=false;clearSelection()
  await annotationApi.save(currentImageId.value,[])
  await imageApi.updateStatus(currentImageId.value,'reviewed')
  setLocalImageStatus('reviewed',0)
  renderAnnotations(); ElMessage.success('已标记为OK（负样本）')
}
async function unmarkOk(){
  if(!currentImage.value)return
  const newStatus=annotations.value.length>0?'labeled':'unlabeled'
  await imageApi.updateStatus(currentImageId.value,newStatus)
  setLocalImageStatus(newStatus)
  ElMessage.info('已取消OK标记')
}
async function clearAll(){
  try{await ElMessageBox.confirm('确定清空所有标注？','清空',{confirmButtonText:'清空',cancelButtonText:'取消',type:'warning'})}catch{return}
  pushUndo();annotations.value=[];dirty.value=true;clearSelection();removeVertexHandles();renderAnnotations();scheduleAutoSave()
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
  setLocalImageStatus('labeled',annotations.value.length)
  dirty.value=true
  renderAnnotations()
  scheduleAutoSave()
}
function drawDotFixed(x:number,y:number){
  if(!canvas)return;const c=clsColor(selectedClassId.value)
  const d=new fabric.Circle({left:x-0.4,top:y-0.4,radius:0.4,fill:'#FFF',stroke:c,strokeWidth:0.2,selectable:false,evented:false})
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
  const ln=new fabric.Line([last.x,last.y,p.x,p.y],{stroke:c,strokeWidth:0.375,strokeDashArray:[5,3],selectable:false,evented:false})
  ;(ln as any)._tmp=true;(ln as any)._tl=true;canvas.add(ln);canvas.requestRenderAll()
}
function cancelDrawing(){isDrawing.value=false;drawingPoints=[];isBrushing=false;brushPts=[];isErasing=false;eraserPts=[];circleStart=null;rectStart=null;boxEraserStart=null;lastBrushAnnIdx=-1;lastBrushPts=[];cleanTmp()}
function cleanTmp(){if(!canvas)return;canvas.getObjects().filter(o=>(o as any)._tmp).forEach(o=>canvas!.remove(o));canvas.requestRenderAll()}
function clearSelection(){
  selectedAnnIndices.value=new Set()
  selectedAnnIdx.value=-1
  removeVertexHandles()
  highlightSelected()
}

function applySelection(indices:Set<number>,primary:number){
  selectedAnnIndices.value=indices
  selectedAnnIdx.value=indices.has(primary)?primary:([...indices].pop()??-1)
  highlightSelected()
  showSelectionHandles()
  nextTick(centerSelectedAnnotation)
}

async function selectAnn(idx:number,toggle=false){
  if(!annotations.value[idx])return
  if(!showAnnotationLayer.value){
    showAnnotationLayer.value=true
    await nextTick()
  }
  const indices=toggle?new Set(selectedAnnIndices.value):new Set<number>()
  if(toggle&&indices.has(idx))indices.delete(idx)
  else indices.add(idx)
  applySelection(indices,indices.has(idx)?idx:selectedAnnIdx.value)
}

function centerSelectedAnnotation(){
  const list=annListRef.value
  const row=list?.querySelector<HTMLElement>(`[data-ann-index="${selectedAnnIdx.value}"]`)
  if(!list||!row)return
  const offset=row.getBoundingClientRect().top-list.getBoundingClientRect().top
  list.scrollTop+=offset-(list.clientHeight-row.offsetHeight)/2
}

function formatConfidence(conf:number){return `${(conf*100).toFixed(1)}%`}

// 在上一版 6px 基础上再缩小三分之二，适应窗口时为 2px，随后同比缩放。
let annotationLabelReferenceZoom=1
function drawAnnotationLabels(){
  if(!canvas||!showAnnotationLayer.value||(!showClassNames.value&&!showConfidence.value))return
  const ctx=canvas.getContext()
  const ratio=canvas.getRetinaScaling()
  const scale=canvas.getZoom()/annotationLabelReferenceZoom/6
  const labelHeight=21*scale
  ctx.save()
  ctx.setTransform(ratio,0,0,ratio,0,0)
  ctx.font=`${12*scale}px "ChillRoundF", "Microsoft YaHei", sans-serif`
  ctx.textBaseline='middle'
  // 选中对象最后绘制，密集标注时优先看清它的完整名称与置信度。
  const objects=canvas.getObjects().filter(o=>(o as any)._ann)
  objects.sort((a,b)=>Number((a as any)._idx===selectedAnnIdx.value)-Number((b as any)._idx===selectedAnnIdx.value))
  for(const object of objects){
    const idx=(object as any)._idx
    const ann=annotations.value[idx]
    if(!ann)continue
    const parts=[]
    if(showClassNames.value)parts.push(`#${idx+1} ${clsName(ann.class_id)}`)
    if(showConfidence.value&&ann.confidence!=null)parts.push(formatConfidence(ann.confidence))
    if(!parts.length)continue
    const bounds=object.getBoundingRect(false,true)
    if(bounds.left+bounds.width<0||bounds.top+bounds.height<0||bounds.left>canvas.width!||bounds.top>canvas.height!)continue
    const label=parts.join(' · ')
    const width=ctx.measureText(label).width+12*scale
    const left=Math.max(0,Math.min(bounds.left,canvas.width!-width))
    const top=Math.max(0,Math.min(bounds.top-labelHeight-2*scale,canvas.height!-labelHeight))
    ctx.fillStyle=selectedAnnIndices.value.has(idx)?'rgba(15,65,110,.95)':'rgba(20,20,20,.82)'
    ctx.fillRect(left,top,width,labelHeight)
    ctx.fillStyle=clsColor(ann.class_id)
    ctx.fillRect(left,top,3*scale,labelHeight)
    ctx.fillStyle='#fff'
    ctx.fillText(label,left+7*scale,top+labelHeight/2)
  }
  ctx.restore()
}

function highlightSelected(){
  if(!canvas)return
  canvas.getObjects().forEach(o=>{
    if((o as any)._ann){
      const selected=selectedAnnIndices.value.has((o as any)._idx)
      o.set({strokeWidth:selected?0.75:0.375,opacity:selectedAnnIndices.value.size===0||selected?1:0.7})
    }
  })
  canvas.requestRenderAll()
}

// ====== 所有选中对象的顶点与旋转手柄；左拖顶点，Ctrl 拖对象或绿点 ======
function showSelectionHandles(){
  removeVertexHandles()
  if(!canvas||!currentImage.value||!showAnnotationLayer.value||currentTool.value!=='select')return
  const W=dispW(),H=dispH()
  // 当前对象最后绘制，重叠手柄时优先响应最近选择的对象。
  const indices=[...selectedAnnIndices.value].sort((a,b)=>Number(a===selectedAnnIdx.value)-Number(b===selectedAnnIdx.value))
  for(const idx of indices){
    const ann=annotations.value[idx]
    if(!ann)continue
    const points=ann.polygon.map(p=>({x:p.x*W,y:p.y*H}))
    const cx=points.reduce((s,p)=>s+p.x,0)/points.length,cy=points.reduce((s,p)=>s+p.y,0)/points.length
    const rotating=canvasGesture?.kind==='rotate'&&canvasGesture.hit===idx&&canvasGesture.moved
    const rotPoint=rotating?canvasGesture!.end:{x:cx,y:Math.max(8,Math.min(...points.map(p=>p.y))-22)}
    const stem=new fabric.Line([cx,cy,rotPoint.x,rotPoint.y],{
      stroke:'#52C41A',strokeWidth:1,strokeDashArray:[3,3],selectable:false,evented:false,
    })
    ;(stem as any)._handle=true
    canvas.add(stem);editHandles.push(stem)
    const addHandle=(p:Point,radius:number,pointIndex?:number)=>{
      const rotation=pointIndex===undefined
      const handle=new fabric.Circle({
        left:p.x-radius,top:p.y-radius,radius,
        fill:rotation?'#52C41A':'#fff',stroke:rotation?'#fff':'#409EFF',strokeWidth:rotation?1.5:0.2,
        hasControls:false,hasBorders:false,selectable:false,evented:true,hoverCursor:rotation?'grab':'move',
        originX:'left',originY:'top',
      })
      Object.assign(handle,{_handle:true,_annIdx:idx,_ptIdx:pointIndex,_rotHandle:rotation})
      canvas!.add(handle);editHandles.push(handle)
    }
    addHandle(rotPoint,5)
    points.forEach((p,i)=>addHandle(p,0.6,i))
  }
  canvas.requestRenderAll()
}

function removeVertexHandles(){
  if(!canvas)return
  editHandles.forEach(handle=>canvas!.remove(handle))
  editHandles=[]
}

// ====== 复制粘贴 ======
function copyAnn(){
  if(selectedAnnIdx.value<0)return
  const ann=annotations.value[selectedAnnIdx.value]
  if(!ann)return
  // 剪贴板统一存原图坐标系，粘贴时再转当前显示坐标系（旋转前后复制粘贴不错位）
  clipboard={class_id:ann.class_id,polygon:ann.polygon.map(dispToOrig)}
  ElMessage.info('已复制')
}
async function pasteAnn(){
  if(!showAnnotationLayer.value)return
  if(!clipboard||!currentImage.value)return
  if(!(await ensureCanAddDefect()))return
  const W=dispW(),H=dispH()
  // 像素偏移 20px，转归一化
  const dx=20/W,dy=20/H
  const newPoly=clipboard.polygon.map(origToDisp).map(p=>({
    x:Math.max(0,Math.min(1,p.x+dx)),
    y:Math.max(0,Math.min(1,p.y+dy)),
  }))
  pushUndo()
  annotations.value.push({class_id:clipboard.class_id,polygon:newPoly})
  setLocalImageStatus('labeled',annotations.value.length)
  dirty.value=true
  renderAnnotations()
  applySelection(new Set([annotations.value.length-1]),annotations.value.length-1)
  scheduleAutoSave()
  ElMessage.success('已粘贴')
}
function delAnn(idx:number){pushUndo();annotations.value.splice(idx,1);dirty.value=true;clearSelection();removeVertexHandles();renderAnnotations();scheduleAutoSave()}
function pushUndo(snapshot=JSON.stringify(annotations.value)){undoStack.value.push(snapshot);redoStack.value=[];if(undoStack.value.length>50)undoStack.value.shift()}
function undo(){finishCanvasGesture();if(!canUndo.value)return;redoStack.value.push(JSON.stringify(annotations.value));annotations.value=JSON.parse(undoStack.value.pop()!);dirty.value=true;clearSelection();renderAnnotations();scheduleAutoSave()}
function redo(){finishCanvasGesture();if(!canRedo.value)return;undoStack.value.push(JSON.stringify(annotations.value));annotations.value=JSON.parse(redoStack.value.pop()!);dirty.value=true;clearSelection();renderAnnotations();scheduleAutoSave()}

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
  if(canvasGesture?.snapshot){scheduleAutoSave();return}
  if(autoSaveTimer){clearTimeout(autoSaveTimer);autoSaveTimer=null}
  if(saving.value) return // 上一次保存还在进行
  if(!dirty.value && !opt.immediate) return
  const imgId=currentImageId.value
  saving.value=true; saveState.value='saving'
  // 提交前：显示坐标系 → 原图坐标系（viewRot=0 时为恒等），
  // 再做兜底 sanitize：兼容历史 VOC 导入数据中的越界顶点
  // (后端 PointSchema 强制 [0,1]，越界值会 422)
  const safeAnns=annotations.value.map(a=>({
    ...a,
    polygon:sanitizePolygon(a.polygon.map(dispToOrig)),
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
      il.status=safeAnns.length>0?'labeled':'unlabeled'
      if(cur?.id===imgId){
        cur.status=il.status
      }
      il.annotation_count=safeAnns.length
    }
    if(!opt.silent) ElMessage.success('保存成功')
  }catch(e:any){
    saveState.value='error'
    if(!opt.silent) ElMessage.error('保存失败：'+(e?.response?.data?.detail||e?.message||''))
  }finally{saving.value=false}
}

async function switchImage(id:number){
  finishCanvasGesture()
  // 切图前 flush 自动保存（避免丢失最近改动）
  if(dirty.value){
    try{await handleSave({silent:true,immediate:true})}
    catch{
      try{await ElMessageBox.confirm('保存失败，仍要切换吗？','提示',{confirmButtonText:'丢弃切换',cancelButtonText:'留下',type:'warning'})}
      catch{return}
    }
  }
  removeVertexHandles();clearSelection()
  lastBrushAnnIdx=-1;lastBrushPts=[]
  currentImageId.value=id;await loadImageAndAnnotations()
}
function prevImage(){if(hasPrev.value)switchImage(imageList.value[currentImageIdx.value-1].id)}
function nextImage(){if(hasNext.value)switchImage(imageList.value[currentImageIdx.value+1].id)}
function goBack(){router.push(`/project/${props.projectId}`)}
function zoomFit(){
  if(!canvas||!canvasAreaRef.value)return
  finishCanvasGesture()
  const bg=canvas.getObjects().find(o=>(o as any)._bg);if(!bg)return
  // 用显示坐标系尺寸（旋转 90/270 时宽高互换），不能直接用 fabric 对象的 width/height
  const cw=canvasAreaRef.value.clientWidth,ch=canvasAreaRef.value.clientHeight
  const iw=dispW(),ih=dispH()
  const z=Math.min(cw/iw,ch/ih)*0.95
  annotationLabelReferenceZoom=z
  // 一次更新视口及命中坐标，避免适应窗口后多边形仍使用旧的点击范围。
  canvas.setViewportTransform([z,0,0,z,(cw-iw*z)/2,(ch-ih*z)/2])
  canvas.requestRenderAll();zoomLevel.value=z
}
function onKD(e:KeyboardEvent){
  if((e.target as HTMLElement)?.closest('input:not([type="radio"]):not([type="checkbox"]):not([type="button"]):not([type="submit"]),textarea,select,[contenteditable="true"],[role="spinbutton"]'))return
  if(e.code==='Space'){e.preventDefault();spaceDown.value=true}
  else if(!e.ctrlKey&&!e.metaKey&&!e.altKey&&(e.key==='v'||e.key==='V')){
    e.preventDefault()
    if(currentTool.value!=='select'){currentTool.value='select';onToolChange()}
  }
  else if(e.key==='Escape'){finishCanvasGesture(true);cancelDrawing()}
  else if(e.key==='Enter'&&isDrawing.value){if(currentTool.value==='polygon')finishPolygon();else if(currentTool.value==='polyline')finishPolyline()}
  else if(e.ctrlKey&&e.key==='z'){e.preventDefault();undo()}
  else if(e.ctrlKey&&e.key==='y'){e.preventDefault();redo()}
  else if(e.ctrlKey&&e.key==='s'){e.preventDefault();handleSave({immediate:true})}
  else if(e.ctrlKey&&(e.key==='c'||e.key==='C')){e.preventDefault();copyAnn()}
  else if(e.ctrlKey&&(e.key==='v'||e.key==='V')){e.preventDefault();pasteAnn()}
  else if(!e.ctrlKey&&(e.key==='a'||e.key==='ArrowLeft'))prevImage()
  else if(!e.ctrlKey&&(e.key==='d'||e.key==='ArrowRight'))nextImage()
  else if(!e.ctrlKey&&(e.key==='r'||e.key==='R'))rotateView(90)
}
function onKU(e:KeyboardEvent){if(e.code==='Space')spaceDown.value=false}
function getThumbUrl(id:number){return imageApi.getFileUrl(id,true)}
function clsColor(cid:number){return defectClasses.value.find(c=>c.id===cid)?.color||'#FF0000'}
function clsName(cid:number){return defectClasses.value.find(c=>c.id===cid)?.name||'未知'}
function cntCls(cid:number){return annotations.value.filter(a=>a.class_id===cid).length}
function stText(s:string){return({unlabeled:'未标注',labeling:'标注中',labeled:'已标注',reviewed:'OK'})[s]||s}
function imgSC(img:ImageInfo){return{'sc-u':img.status==='unlabeled','sc-l':img.status==='labeled','sc-r':img.status==='reviewed'}}
// resize 监听器在 onMounted / onBeforeUnmount 里配对管理（见上方），避免每次进入标注页都泄漏一个监听器
</script>

<style scoped>
@font-face{font-family:ChillRoundF;src:url('/fonts/ChillRoundF.ttf') format('truetype');font-style:normal;font-weight:400;font-display:swap}
.annotator{display:flex;flex-direction:column;height:100vh;background:#1a1a1a;color:#ddd;outline:none}
.toolbar{display:grid;grid-template-columns:minmax(160px,1fr) minmax(0,max-content) minmax(160px,1fr);align-items:center;padding:6px 12px;background:#2d2d2d;border-bottom:1px solid #444;height:48px;box-sizing:border-box;gap:12px;flex-shrink:0}
.toolbar-left,.toolbar-center,.toolbar-status{display:flex;align-items:center;gap:6px}
.toolbar-left{width:100%;max-width:300px;min-width:0}
.toolbar-left .el-button,.toolbar-left .el-divider,.toolbar-left .el-tag{flex-shrink:0}
.toolbar-center{min-width:0;overflow-x:auto;white-space:nowrap}
.toolbar-center>*{flex-shrink:0}
.toolbar-center :deep(.el-radio-group){display:inline-flex;flex-wrap:nowrap}
.toolbar-status{justify-self:end;flex-shrink:0}
.inference-toolbar{display:flex;align-items:center;gap:10px;padding:6px 12px;background:#252525;border-bottom:1px solid #444;min-height:44px;box-sizing:border-box;flex-shrink:0;overflow-x:auto;white-space:nowrap}
.inference-toolbar>*{flex-shrink:0}
.inference-toolbar>:first-child{margin-left:auto}
.toolbar-section-label{font-size:12px;color:#aaa}
.infer-model-select{width:220px}
.infer-confidence{display:flex;align-items:center;gap:6px;font-size:12px;white-space:nowrap}
.filename{font-weight:500;font-size:14px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.brush-size-ctrl{display:flex;align-items:center;gap:6px}
.ctrl-label{font-size:12px;color:#aaa}.ctrl-value{font-size:12px;color:#aaa;min-width:36px}
.seg-view-controls{display:flex;align-items:center;gap:8px;margin-left:8px}
.channel-radio{white-space:nowrap}
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
.side-panel{--ann-row-height:36px;width:270px;flex-shrink:0;min-height:0;background:#252525;border-left:1px solid #444;display:flex;flex-direction:column}
.class-section{flex:1;min-height:120px;overflow:hidden;display:flex;flex-direction:column}
.class-section .class-list{flex:1;min-height:0;overflow-y:auto}
.annotations-section{flex:0 1 auto;min-height:0;display:flex;flex-direction:column}
.ann-list{height:calc(var(--ann-row-height) * 10);flex:0 1 auto;min-height:0;overflow-y:auto;position:relative}
.display-options{display:flex;flex-wrap:nowrap;align-items:center;justify-content:space-between;gap:6px;padding:5px 8px;flex-shrink:0}
.display-options :deep(.el-checkbox){color:#ddd;margin-right:0;height:22px}
.display-options :deep(.el-checkbox__label){font-size:11px;padding-left:4px;line-height:18px}
.selected-summary{padding:6px 12px;background:#15354e;font-size:12px;color:#d2eaff;overflow-wrap:anywhere;flex-shrink:0}
.ann-confidence{display:block;color:#93caff;font-size:11px;line-height:14px}
.panel-section{border-bottom:1px solid #333}.panel-title{padding:10px 12px;font-size:13px;font-weight:600;color:#aaa;flex-shrink:0}
.class-list{padding:0 8px 10px}
.class-item{display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:6px;cursor:pointer;transition:background .15s}
.class-item:hover{background:#333}.class-item.active{background:#1a3a5c}
.class-dot{width:14px;height:14px;border-radius:3px;flex-shrink:0}.class-name{flex:1;font-size:13px}.class-count{font-size:12px;color:#888}
.empty-hint{padding:20px;text-align:center;color:#666;font-size:13px}
.ann-item{display:flex;align-items:center;gap:6px;height:var(--ann-row-height);box-sizing:border-box;padding:4px 9px;border-left:3px solid transparent;cursor:pointer;transition:background .15s}
.ann-item:hover{background:#333}.ann-item.selected{background:#1a3a5c;border-left-color:#409eff}
.ann-label{flex:1;min-width:0;font-size:12px;line-height:14px}.ann-name{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ann-points{font-size:11px;color:#888;flex-shrink:0}
.statusbar{display:flex;align-items:center;gap:24px;padding:4px 16px;background:#2d2d2d;border-top:1px solid #444;font-size:12px;color:#888}
.status-shortcuts{margin-left:auto;color:#666}
.save-indicator{font-size:12px;min-width:80px;text-align:right;transition:color .2s}
.save-indicator.idle{color:transparent}
.save-indicator.pending{color:#E6A23C}
.save-indicator.saving{color:#909399}
.save-indicator.saved{color:#67C23A}
.save-indicator.error{color:#F56C6C;font-weight:600}
</style>
