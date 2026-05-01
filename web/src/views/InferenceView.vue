<template>
  <div class="infer-page">
    <!-- 顶部参数栏 -->
    <div class="top-bar">
      <div class="top-left">
        <el-button text @click="router.push(`/project/${id}`)"><el-icon><ArrowLeft /></el-icon></el-button>
        <b>在线推断</b>
      </div>
      <div class="top-controls">
        <el-select v-model="selModelIdx" placeholder="选择模型" style="width:260px" size="small">
          <el-option v-for="(m,i) in models" :key="i" :label="m.label" :value="i" />
        </el-select>
        <el-select v-model="device" style="width:180px" size="small">
          <el-option v-for="d in devices" :key="d.id" :label="d.name" :value="d.id" :disabled="!d.available" />
        </el-select>
        <span class="p-label">置信度</span>
        <el-input-number v-model="conf" :min="0.01" :max="0.99" :step="0.05" :precision="2" size="small" style="width:100px" />
        <span class="p-label">IoU</span>
        <el-input-number v-model="iou" :min="0.1" :max="0.95" :step="0.05" :precision="2" size="small" style="width:100px" />
        <span class="p-label">长边缩放</span>
        <el-input-number v-model="resizeSize" :min="0" :max="8192" :step="256" size="small" style="width:110px" />
        <el-tooltip content="0=不缩放，等比缩放长边到指定尺寸（如4096×2048设1024→1024×512）" placement="bottom">
          <el-icon style="color:#aaa;cursor:help"><QuestionFilled /></el-icon>
        </el-tooltip>
        <el-upload :auto-upload="false" :show-file-list="false" :on-change="onUpload" accept=".bmp,.png,.jpg,.jpeg,.tif,.tiff" multiple>
          <el-button type="primary" :loading="inferring" size="small"><el-icon><Upload /></el-icon> 推断</el-button>
        </el-upload>
      </div>
    </div>

    <div class="main-body">
      <!-- 左侧：推断历史 -->
      <div class="history-panel">
        <div class="hp-header">
          <span>推断记录</span>
          <el-button text size="small" type="danger" @click="clearHistory" :disabled="history.length===0">清空</el-button>
        </div>
        <div class="hp-list">
          <div v-for="r in history" :key="r.id" :class="['hp-item',{active:selId===r.id}]" @click="selectRecord(r)">
            <img :src="r.overlay_url || r.original_url" class="hp-thumb" loading="lazy" />
            <div class="hp-info">
              <div class="hp-name">{{ r.filename }}</div>
              <div v-if="r.task_type==='cls'" class="hp-status defect" :style="{color: clsColorOf(r)}">
                {{ clsLabelOf(r) }}
              </div>
              <div v-else :class="['hp-status', r.num_detections>0?'defect':'ok']">
                {{ r.num_detections>0 ? r.num_detections+' 缺陷' : '✓ OK' }}
              </div>
              <div class="hp-meta">{{ r.inference_time }}s · {{ r.device }}</div>
            </div>
            <el-button text size="small" class="hp-del" @click.stop="delRecord(r.id)"><el-icon><Delete /></el-icon></el-button>
          </div>
          <div v-if="history.length===0" class="hp-empty">暂无记录</div>
        </div>
      </div>

      <!-- 中间：大图查看器 -->
      <div class="viewer">
        <template v-if="current">
          <!-- 视图切换（cls 不需要；obb 没有 mask） -->
          <div class="view-bar">
            <el-radio-group v-if="!isCls" v-model="viewMode" size="small">
              <el-radio-button label="overlay">检测结果</el-radio-button>
              <el-radio-button label="original">原图</el-radio-button>
              <el-radio-button v-if="!isObb" label="mask">Mask</el-radio-button>
              <el-radio-button v-if="!isObb" label="compare">同时显示</el-radio-button>
            </el-radio-group>
            <el-switch
              v-if="!isCls && current.overlay_morph_url"
              v-model="showMorph"
              active-text="形态学视图"
              inactive-text="原图视图"
              size="small"
              style="margin-left:12px"
            />
            <div v-if="isCls" class="cls-top1">
              <span style="color:#909399;margin-right:4px">Top-1:</span>
              <el-tag :color="clsColorOf(current)" effect="dark" disable-transitions>{{ clsTop1Name(current) }}</el-tag>
              <b :style="{color:'#67C23A',marginLeft:'8px'}">{{ (clsTop1Conf(current)*100).toFixed(2) }}%</b>
            </div>
            <div class="view-stats">
              <template v-if="isCls">{{ current.inference_time }}s · {{ current.filename }}</template>
              <template v-else>
                <b :style="{color:current.num_detections>0?'#F56C6C':'#67C23A'}">{{ current.num_detections }}</b> 缺陷
                · {{ current.inference_time }}s
                · {{ current.filename }}
              </template>
              <span style="margin-left:12px;color:#aaa">滚轮缩放 · 拖拽移动 · 双击还原</span>
            </div>
          </div>

          <!-- 单图模式 -->
          <div v-if="viewMode!=='compare'" class="img-container" ref="imgContainer"
            @wheel.prevent="onWheel" @mousedown="onDragStart" @dblclick="resetZoom">
            <img :src="currentSrc" class="zoom-img" :style="imgStyle" draggable="false" />
          </div>

          <!-- 对比模式 -->
          <div v-else class="compare-container">
            <div class="cmp-cell" v-for="v in ['original','overlay','mask']" :key="v">
              <div class="cmp-label">{{ {original:'原图',overlay:'检测结果',mask:'Mask'}[v] }}</div>
              <div class="cmp-img-wrap" @wheel.prevent="e=>onWheelCmp(e,v)" @mousedown="e=>onDragStartCmp(e,v)" @dblclick="resetZoomCmp(v)">
                <img :src="(current as any)[v+'_url']" class="zoom-img" :style="cmpStyles[v]" draggable="false" />
              </div>
            </div>
          </div>

          <!-- 检测详情（seg / det） -->
          <div v-if="!isCls && !isObb && current.detections.length>0" class="detail-bar">
            <el-table :data="current.detections" stripe size="small" max-height="160" style="width:100%">
              <el-table-column type="index" label="#" width="45" />
              <el-table-column label="类别" width="90"><template #default="{row}"><el-tag size="small">{{ row.class_name || ('C' + row.class_id) }}</el-tag></template></el-table-column>
              <el-table-column label="置信度" width="80"><template #default="{row}"><b :style="{color:row.confidence>0.5?'#67C23A':'#E6A23C'}">{{(row.confidence*100).toFixed(1)}}%</b></template></el-table-column>
              <el-table-column label="位置"><template #default="{row}"><span v-if="row.bbox">({{row.bbox.x1}},{{row.bbox.y1}})→({{row.bbox.x2}},{{row.bbox.y2}})</span><span v-else>—</span></template></el-table-column>
              <el-table-column label="尺寸" width="90"><template #default="{row}"><span v-if="row.bbox">{{row.bbox.x2-row.bbox.x1}}×{{row.bbox.y2-row.bbox.y1}}</span><span v-else>—</span></template></el-table-column>
            </el-table>
          </div>

          <!-- 旋转目标检测 OBB -->
          <div v-else-if="isObb && current.detections.length>0" class="detail-bar">
            <el-table :data="current.detections" stripe size="small" max-height="200" style="width:100%">
              <el-table-column type="index" label="#" width="45" />
              <el-table-column label="类别" width="100"><template #default="{row}"><el-tag size="small">{{ row.class_name || ('C' + row.class_id) }}</el-tag></template></el-table-column>
              <el-table-column label="置信度" width="80"><template #default="{row}"><b :style="{color:row.confidence>0.5?'#67C23A':'#E6A23C'}">{{(row.confidence*100).toFixed(1)}}%</b></template></el-table-column>
              <el-table-column label="中心" width="120"><template #default="{row}">{{ obbCenter(row) }}</template></el-table-column>
              <el-table-column label="尺寸" width="100"><template #default="{row}">{{ obbSize(row) }}</template></el-table-column>
              <el-table-column label="角度" width="80"><template #default="{row}">{{ obbAngle(row) }}°</template></el-table-column>
              <el-table-column label="4 角点">
                <template #default="{row}">
                  <span v-if="row.polygon" style="font-size:11px;color:#909399">
                    {{ row.polygon.map((p:any)=>`(${Math.round(p.x)},${Math.round(p.y)})`).join(' → ') }}
                  </span>
                </template>
              </el-table-column>
            </el-table>
          </div>

          <!-- 分类 Top-5 -->
          <div v-else-if="isCls && current.detections.length>0" class="detail-bar">
            <el-table :data="current.detections" stripe size="small" max-height="200" style="width:100%">
              <el-table-column type="index" label="Rank" width="60">
                <template #default="{$index}">Top-{{ $index + 1 }}</template>
              </el-table-column>
              <el-table-column label="类别" width="120"><template #default="{row}"><el-tag size="small">{{ row.class_name || ('C' + row.class_id) }}</el-tag></template></el-table-column>
              <el-table-column label="置信度" width="100"><template #default="{row}"><b :style="{color:row.confidence>0.5?'#67C23A':'#E6A23C'}">{{(row.confidence*100).toFixed(2)}}%</b></template></el-table-column>
              <el-table-column label="概率分布">
                <template #default="{row}">
                  <el-progress :percentage="+(row.confidence*100).toFixed(1)" :stroke-width="14"
                    :color="row.confidence>0.5?'#67C23A':'#E6A23C'" :show-text="false" />
                </template>
              </el-table-column>
            </el-table>
          </div>
        </template>

        <!-- 空状态 -->
        <div v-else class="empty-state">
          <el-upload drag :auto-upload="false" :show-file-list="false" :on-change="onUpload"
            accept=".bmp,.png,.jpg,.jpeg,.tif,.tiff" multiple style="width:460px">
            <el-icon style="font-size:48px;color:#c0c4cc"><UploadFilled /></el-icon>
            <div style="margin-top:8px;color:#606266">拖拽图片或点击选择</div>
            <div style="font-size:12px;color:#aaa;margin-top:4px">支持多选 · BMP/PNG/JPG/TIFF</div>
          </el-upload>
        </div>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="inferring" class="loading-overlay">
      <el-icon class="is-loading" style="font-size:36px;color:#409EFF"><Loading /></el-icon>
      <div style="color:#fff;margin-top:10px">{{ inferMsg }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api/index'
import type { UploadFile } from 'element-plus'

const props = defineProps<{ id: string }>()
const router = useRouter()
// URLs already include /api prefix

interface ModelInfo { task_id:number; model_format:string; label:string; model_path:string }
interface Det {
  class_id:number; class_name?:string; confidence:number;
  bbox?:{x1:number;y1:number;x2:number;y2:number};
  polygon?:Array<{x:number;y:number}>
}
interface Rec { id:number; filename:string; num_detections:number; inference_time:number; detections:Det[]; original_url:string; overlay_url:string; overlay_morph_url?:string|null; mask_url:string; device:string; created_at:string|null; task_type?:string }

interface DeviceInfo { id:string; name:string; available:boolean }

const models = ref<ModelInfo[]>([])
const devices = ref<DeviceInfo[]>([{id:'cpu',name:'CPU',available:true}])
const selModelIdx = ref<number|null>(null)
const device = ref('cpu')
const conf = ref(0.15)
const iou = ref(0.5)
const resizeSize = ref(0)
const inferring = ref(false)
const inferMsg = ref('')
const viewMode = ref<'original'|'overlay'|'mask'|'compare'>('overlay')
const showMorph = ref(false)

const history = ref<Rec[]>([])
const selId = ref<number|null>(null)
const current = computed(() => history.value.find(r => r.id === selId.value) || null)

// 是否分类任务（兜底：detections 没 bbox 也判为 cls）
const isCls = computed(() => {
  const r = current.value
  if (!r) return false
  if (r.task_type === 'cls') return true
  const dets = r.detections || []
  // cls 既没有 bbox 也没有 polygon
  return dets.length > 0 && !dets[0].bbox && !dets[0].polygon
})

// 是否旋转目标检测（OBB）
const isObb = computed(() => {
  const r = current.value
  if (!r) return false
  if (r.task_type === 'obb') return true
  const dets = r.detections || []
  return dets.length > 0 && Array.isArray(dets[0].polygon) && dets[0].polygon!.length === 4
})

// ---- OBB 工具函数（基于 4 点 polygon） ----
function obbCenter(row: Det): string {
  const p = row.polygon
  if (!p || p.length < 4) return '-'
  const cx = (p[0].x + p[1].x + p[2].x + p[3].x) / 4
  const cy = (p[0].y + p[1].y + p[2].y + p[3].y) / 4
  return `(${Math.round(cx)}, ${Math.round(cy)})`
}
function obbSize(row: Det): string {
  const p = row.polygon
  if (!p || p.length < 4) return '-'
  const e1 = Math.hypot(p[1].x - p[0].x, p[1].y - p[0].y)
  const e2 = Math.hypot(p[2].x - p[1].x, p[2].y - p[1].y)
  return `${Math.round(Math.max(e1, e2))}×${Math.round(Math.min(e1, e2))}`
}
function obbAngle(row: Det): string {
  const p = row.polygon
  if (!p || p.length < 4) return '0'
  // 取长边方向作为角度（0~180°）
  const e1 = Math.hypot(p[1].x - p[0].x, p[1].y - p[0].y)
  const e2 = Math.hypot(p[2].x - p[1].x, p[2].y - p[1].y)
  const longEdge = e1 >= e2 ? [p[0], p[1]] : [p[1], p[2]]
  let deg = Math.atan2(longEdge[1].y - longEdge[0].y, longEdge[1].x - longEdge[0].x) * 180 / Math.PI
  if (deg < 0) deg += 180
  if (deg >= 180) deg -= 180
  return deg.toFixed(1)
}

const currentSrc = computed(() => {
  if (!current.value) return ''
  // cls 只有原图
  if (isCls.value) return current.value.original_url
  const mode = viewMode.value === 'compare' ? 'overlay' : viewMode.value
  // 检测结果模式：如果打开形态学开关且有形态学图，显示形态学版本
  if (mode === 'overlay' && showMorph.value && current.value.overlay_morph_url) {
    return current.value.overlay_morph_url
  }
  return (current.value as any)[mode + '_url']
})

// ---- cls 工具函数 ----
function clsTop1(r: Rec | null): Det | null {
  if (!r || !r.detections || r.detections.length === 0) return null
  return r.detections[0]
}
function clsTop1Name(r: Rec | null): string {
  const d = clsTop1(r); if (!d) return '-'
  return d.class_name || ('C' + d.class_id)
}
function clsTop1Conf(r: Rec | null): number {
  const d = clsTop1(r); return d ? d.confidence : 0
}
function clsLabelOf(r: Rec): string {
  const d = clsTop1(r); if (!d) return '-'
  return `${d.class_name || ('C' + d.class_id)} ${(d.confidence*100).toFixed(1)}%`
}
// 简单按 class_id 哈希取色
const _clsColors = ['#F56C6C','#67C23A','#E6A23C','#409EFF','#9254DE','#13C2C2','#FA541C','#A0D911']
function clsColorOf(r: Rec | null): string {
  const d = clsTop1(r); if (!d) return '#909399'
  return _clsColors[(d.class_id ?? 0) % _clsColors.length]
}

const selModel = computed(() => selModelIdx.value !== null ? models.value[selModelIdx.value] : null)

// ---- 缩放状态 ----
const imgContainer = ref<HTMLElement>()
const zoom = ref(1)
const panX = ref(0)
const panY = ref(0)
let dragging = false, dragStartX = 0, dragStartY = 0, startPanX = 0, startPanY = 0

const imgStyle = computed(() => ({
  transform: `translate(${panX.value}px, ${panY.value}px) scale(${zoom.value})`,
  cursor: dragging ? 'grabbing' : 'grab',
}))

function onWheel(e: WheelEvent) {
  const d = e.deltaY > 0 ? 0.9 : 1.1
  zoom.value = Math.max(0.1, Math.min(20, zoom.value * d))
}
function onDragStart(e: MouseEvent) {
  dragging = true; dragStartX = e.clientX; dragStartY = e.clientY; startPanX = panX.value; startPanY = panY.value
  const onMove = (ev: MouseEvent) => { panX.value = startPanX + ev.clientX - dragStartX; panY.value = startPanY + ev.clientY - dragStartY }
  const onUp = () => { dragging = false; window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp) }
  window.addEventListener('mousemove', onMove); window.addEventListener('mouseup', onUp)
}
function resetZoom() { zoom.value = 1; panX.value = 0; panY.value = 0 }

// ---- 对比模式缩放（3个独立） ----
const cmpZoom = reactive<Record<string,{z:number;x:number;y:number}>>({
  original:{z:1,x:0,y:0}, overlay:{z:1,x:0,y:0}, mask:{z:1,x:0,y:0}
})
const cmpStyles = computed(() => {
  const r: Record<string,any> = {}
  for (const k of ['original','overlay','mask']) {
    const s = cmpZoom[k]
    r[k] = { transform: `translate(${s.x}px,${s.y}px) scale(${s.z})`, cursor: 'grab' }
  }
  return r
})
function onWheelCmp(e: WheelEvent, k: string) {
  const d = e.deltaY > 0 ? 0.9 : 1.1
  cmpZoom[k].z = Math.max(0.1, Math.min(20, cmpZoom[k].z * d))
}
function onDragStartCmp(e: MouseEvent, k: string) {
  const sx = e.clientX, sy = e.clientY, ox = cmpZoom[k].x, oy = cmpZoom[k].y
  const mv = (ev: MouseEvent) => { cmpZoom[k].x = ox + ev.clientX - sx; cmpZoom[k].y = oy + ev.clientY - sy }
  const up = () => { window.removeEventListener('mousemove', mv); window.removeEventListener('mouseup', up) }
  window.addEventListener('mousemove', mv); window.addEventListener('mouseup', up)
}
function resetZoomCmp(k: string) { cmpZoom[k] = {z:1,x:0,y:0} }

// ---- 数据加载 ----
onMounted(async () => {
  const { data: m } = await api.get('/inference/models', { params: { project_id: props.id } })
  models.value = m
  if (m.length > 0) selModelIdx.value = 0
  // 加载可用设备
  try {
    const { data: d } = await api.get('/inference/devices')
    devices.value = d
    // 默认选第一个可用的
    const first = d.find((x: DeviceInfo) => x.available)
    if (first) device.value = first.id
  } catch {}
  await loadHistory()
})

async function loadHistory() {
  const { data } = await api.get('/inference/history', { params: { project_id: props.id, page_size: 100 } })
  history.value = data.items
  if (data.items.length > 0 && !selId.value) selId.value = data.items[0].id
}

function selectRecord(r: Rec) {
  selId.value = r.id
  resetZoom()
  for (const k of ['original','overlay','mask']) cmpZoom[k] = {z:1,x:0,y:0}
  // cls 强制单图模式（即使 viewMode 是别的，currentSrc 也回退到 original_url）
  const cls = r.task_type === 'cls' || (r.detections && r.detections.length > 0 && !r.detections[0].bbox)
  if (cls && viewMode.value === 'compare') viewMode.value = 'original'
}

// ---- 推断 ----
async function onUpload(file: UploadFile) {
  if (!file.raw) return
  if (!selModel.value) { ElMessage.warning('请先选择模型'); return }
  await runInfer([file.raw])
}

async function runInfer(files: File[]) {
  if (!selModel.value) return
  inferring.value = true
  for (let i = 0; i < files.length; i++) {
    const f = files[i]
    inferMsg.value = files.length > 1 ? `${i+1}/${files.length} ${f.name}` : f.name
    try {
      const fd = new FormData()
      fd.append('file', f)
      fd.append('project_id', props.id)
      fd.append('task_id', String(selModel.value.task_id))
      fd.append('model_path', selModel.value.model_path)
      fd.append('conf', String(conf.value))
      fd.append('iou', String(iou.value))
      fd.append('resize_size', String(resizeSize.value))
      fd.append('device', device.value)
      const { data } = await api.post('/inference/run', fd, {
        headers: { 'Content-Type': 'multipart/form-data' }, timeout: 300000,
      })
      history.value.unshift(data)
      selId.value = data.id
    } catch { ElMessage.error(`${f.name} 推断失败`) }
  }
  inferring.value = false
  resetZoom()
}

async function delRecord(rid: number) {
  await api.delete(`/inference/history/${rid}`)
  history.value = history.value.filter(r => r.id !== rid)
  if (selId.value === rid) selId.value = history.value.length > 0 ? history.value[0].id : null
}

async function clearHistory() {
  try { await ElMessageBox.confirm('确定清空所有推断记录？','清空',{type:'warning'}) } catch { return }
  await api.delete('/inference/history', { params: { project_id: props.id } })
  history.value = []; selId.value = null
}
</script>

<style scoped>
.infer-page { display:flex; flex-direction:column; height:100vh; background:#f0f2f5; }

.top-bar { display:flex; justify-content:space-between; align-items:center; padding:6px 14px; background:#fff; border-bottom:1px solid #e4e7ed; flex-shrink:0; }
.top-left { display:flex; align-items:center; gap:6px; }
.top-controls { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.p-label { font-size:12px; color:#909399; }

.main-body { display:flex; flex:1; overflow:hidden; }

/* 左侧历史 */
.history-panel { width:220px; background:#fff; border-right:1px solid #e4e7ed; display:flex; flex-direction:column; flex-shrink:0; }
.hp-header { display:flex; justify-content:space-between; align-items:center; padding:10px 12px; font-size:13px; font-weight:600; color:#303133; border-bottom:1px solid #eee; }
.hp-list { flex:1; overflow-y:auto; }
.hp-item { display:flex; gap:6px; padding:6px 8px; cursor:pointer; border-bottom:1px solid #f5f5f5; align-items:center; transition:background .15s; position:relative; }
.hp-item:hover { background:#f5f7fa; }
.hp-item.active { background:#ecf5ff; border-left:3px solid #409EFF; }
.hp-thumb { width:44px; height:44px; object-fit:cover; border-radius:4px; background:#eee; flex-shrink:0; }
.hp-info { flex:1; min-width:0; }
.hp-name { font-size:10px; color:#606266; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.hp-status { font-size:11px; font-weight:600; }
.hp-status.defect { color:#F56C6C; }
.hp-status.ok { color:#67C23A; }
.hp-meta { font-size:10px; color:#c0c4cc; }
.hp-del { position:absolute; right:4px; top:4px; opacity:0; transition:opacity .15s; }
.hp-item:hover .hp-del { opacity:1; }
.hp-empty { text-align:center; color:#c0c4cc; padding:40px 0; font-size:13px; }

/* 查看器 */
.viewer { flex:1; display:flex; flex-direction:column; overflow:hidden; }
.view-bar { display:flex; justify-content:space-between; align-items:center; padding:8px 14px; background:#fff; border-bottom:1px solid #e4e7ed; flex-shrink:0; gap:12px; flex-wrap:wrap; }
.view-stats { font-size:12px; color:#909399; }
.cls-top1 { display:flex; align-items:center; font-size:13px; font-weight:600; color:#303133; }

/* 单图缩放容器 */
.img-container { flex:1; overflow:hidden; background:#111; display:flex; justify-content:center; align-items:center; user-select:none; }
.zoom-img { max-width:100%; max-height:100%; object-fit:contain; transform-origin:center center; transition:none; }

/* 对比模式 */
.compare-container { flex:1; display:grid; grid-template-columns:1fr 1fr 1fr; gap:4px; background:#111; overflow:hidden; }
.cmp-cell { display:flex; flex-direction:column; min-height:0; overflow:hidden; }
.cmp-label { text-align:center; font-size:11px; color:#888; padding:4px 0; background:#1a1a1a; flex-shrink:0; }
.cmp-img-wrap { flex:1; overflow:hidden; display:flex; justify-content:center; align-items:center; user-select:none; }

/* 检测详情 */
.detail-bar { padding:6px 14px; background:#fff; border-top:1px solid #e4e7ed; flex-shrink:0; max-height:180px; overflow-y:auto; }

.empty-state { flex:1; display:flex; justify-content:center; align-items:center; }

.loading-overlay { position:fixed; top:0; left:0; right:0; bottom:0; z-index:9999; background:rgba(0,0,0,.55); display:flex; flex-direction:column; justify-content:center; align-items:center; }
</style>
