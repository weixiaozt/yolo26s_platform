<template>
  <div class="infer-page">
    <!-- 顶部参数栏 -->
    <div class="top-bar">
      <div class="top-left">
        <el-button text @click="router.push(`/project/${id}`)"><el-icon><ArrowLeft /></el-icon></el-button>
        <b>在线推断</b>
        <el-radio-group v-model="viewLayout" size="small" style="margin-left:14px">
          <el-radio-button label="list">列表</el-radio-button>
          <el-radio-button label="grid">网格</el-radio-button>
        </el-radio-group>
      </div>
      <div class="top-controls">
        <el-select v-model="selModelIdx" placeholder="选择模型" style="width:240px" size="small">
          <el-option v-for="(m,i) in models" :key="i" :label="m.label" :value="i" />
        </el-select>
        <el-select v-model="device" style="width:140px" size="small">
          <el-option v-for="d in devices" :key="d.id" :label="d.name" :value="d.id" :disabled="!d.available" />
        </el-select>
        <span class="p-label">置信度</span>
        <el-input-number v-model="conf" :min="0.01" :max="0.99" :step="0.05" :precision="2" size="small" style="width:96px" />
        <span class="p-label">IoU</span>
        <el-input-number v-model="iou" :min="0.1" :max="0.95" :step="0.05" :precision="2" size="small" style="width:96px" />
        <span class="p-label">长边缩放</span>
        <el-input-number v-model="resizeSize" :min="0" :max="8192" :step="256" size="small" style="width:96px" />
        <el-tooltip content="0=不缩放，等比缩放长边到指定尺寸" placement="bottom">
          <el-icon style="color:#aaa;cursor:help"><QuestionFilled /></el-icon>
        </el-tooltip>

        <!-- 选图（不自动推理） -->
        <el-upload :auto-upload="false" :show-file-list="false" :on-change="onSelectFile" accept=".bmp,.png,.jpg,.jpeg,.tif,.tiff" multiple>
          <el-button size="small"><el-icon><Plus /></el-icon> 选图</el-button>
        </el-upload>

        <!-- 开始推理 / 清空队列 -->
        <el-button v-if="pending.length>0" type="primary" :loading="inferring" size="small" @click="runPending">
          <el-icon><VideoPlay /></el-icon> 开始推理 ({{ pending.length }})
        </el-button>
        <el-button v-if="pending.length>0" size="small" @click="clearPending">清空队列</el-button>

        <!-- 一键推理训练图 -->
        <el-button type="success" size="small" @click="showProjectImagesDialog=true" :disabled="!selModel">
          <el-icon><DataLine /></el-icon> 推理训练图
        </el-button>

        <!-- 切割小图（仅 seg 项目） -->
        <el-button v-if="projectTaskType==='seg'" type="warning" size="small"
          :disabled="history.length===0 || cropping" :loading="cropping"
          @click="cropDefects">
          <el-icon><Scissor /></el-icon> 切割小图
        </el-button>
      </div>
    </div>

    <!-- 待推理队列条（仅有时显示） -->
    <div v-if="pending.length>0" class="pending-bar">
      <span class="pending-label">待推理 {{ pending.length }} 张：</span>
      <div class="pending-thumbs">
        <div v-for="(p,i) in pending" :key="i" class="pending-item" :title="p.file.name">
          <img :src="p.url" />
          <div class="pending-name">{{ p.file.name }}</div>
          <el-button text size="small" class="pending-del" @click="removePending(i)">
            <el-icon><Close /></el-icon>
          </el-button>
        </div>
      </div>
    </div>

    <div class="main-body">
      <!-- 列表视图：左侧推断历史 + 中间大图 -->
      <template v-if="viewLayout==='list'">
        <div class="history-panel">
          <div class="hp-header">
            <span>推断记录 ({{ history.length }})</span>
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

        <div class="viewer">
          <template v-if="current">
            <div class="view-bar">
              <el-radio-group v-if="!isCls" v-model="viewMode" size="small">
                <el-radio-button label="overlay">检测结果</el-radio-button>
                <el-radio-button label="original">原图</el-radio-button>
                <el-radio-button v-if="!isObb" label="mask">Mask</el-radio-button>
                <el-radio-button v-if="!isObb" label="compare">同时显示</el-radio-button>
              </el-radio-group>
              <el-switch v-if="!isCls && current.overlay_morph_url" v-model="showMorph"
                active-text="形态学视图" inactive-text="原图视图" size="small" style="margin-left:12px" />
              <div v-if="isCls" class="cls-top1">
                <span style="color:#909399;margin-right:4px">Top-1:</span>
                <el-tag :color="clsColorOf(current)" effect="dark" disable-transitions>{{ clsTop1Name(current) }}</el-tag>
                <b :style="{color:'#67C23A',marginLeft:'8px'}">{{ (clsTop1Conf(current)*100).toFixed(2) }}%</b>
                <span v-if="current.source_class_id !== undefined && current.source_class_id !== null"
                      style="margin-left:14px;font-size:12px"
                      :style="{color: gtMatchColor(current)}">
                  GT: <b>{{ gtNameOf(current) }}</b>
                  <span v-if="!gtMatch(current)"> ❌</span>
                  <span v-else> ✓</span>
                </span>
              </div>
              <div class="view-stats">
                <template v-if="isCls">{{ current.inference_time }}s · {{ current.filename }}</template>
                <template v-else>
                  <b :style="{color:current.num_detections>0?'#F56C6C':'#67C23A'}">{{ current.num_detections }}</b>
                  缺陷 · {{ current.inference_time }}s · {{ current.filename }}
                </template>
                <span style="margin-left:12px;color:#aaa">滚轮缩放 · 拖拽移动 · 双击还原</span>
              </div>
            </div>
            <div v-if="viewMode!=='compare'" class="img-container" ref="imgContainer"
                @wheel.prevent="onWheel" @mousedown="onDragStart" @dblclick="resetZoom">
              <img :src="currentSrc" class="zoom-img" :style="imgStyle" draggable="false" />
            </div>
            <div v-else class="compare-container">
              <div class="cmp-cell" v-for="v in ['original','overlay','mask']" :key="v">
                <div class="cmp-label">{{ {original:'原图',overlay:'检测结果',mask:'Mask'}[v] }}</div>
                <div class="cmp-img-wrap" @wheel.prevent="e=>onWheelCmp(e,v)" @mousedown="e=>onDragStartCmp(e,v)" @dblclick="resetZoomCmp(v)">
                  <img :src="(current as any)[v+'_url']" class="zoom-img" :style="cmpStyles[v]" draggable="false" />
                </div>
              </div>
            </div>
            <!-- 检测详情 -->
            <div v-if="!isCls && !isObb && current.detections.length>0" class="detail-bar">
              <el-table :data="current.detections" stripe size="small" max-height="160" style="width:100%">
                <el-table-column type="index" label="#" width="45" />
                <el-table-column label="类别" width="90"><template #default="{row}"><el-tag size="small">{{ row.class_name || ('C' + row.class_id) }}</el-tag></template></el-table-column>
                <el-table-column label="置信度" width="80"><template #default="{row}"><b :style="{color:row.confidence>0.5?'#67C23A':'#E6A23C'}">{{(row.confidence*100).toFixed(1)}}%</b></template></el-table-column>
                <el-table-column label="位置"><template #default="{row}"><span v-if="row.bbox">({{row.bbox.x1}},{{row.bbox.y1}})→({{row.bbox.x2}},{{row.bbox.y2}})</span><span v-else>—</span></template></el-table-column>
                <el-table-column label="尺寸" width="90"><template #default="{row}"><span v-if="row.bbox">{{row.bbox.x2-row.bbox.x1}}×{{row.bbox.y2-row.bbox.y1}}</span><span v-else>—</span></template></el-table-column>
              </el-table>
            </div>
            <div v-else-if="isObb && current.detections.length>0" class="detail-bar">
              <el-table :data="current.detections" stripe size="small" max-height="200" style="width:100%">
                <el-table-column type="index" label="#" width="45" />
                <el-table-column label="类别" width="100"><template #default="{row}"><el-tag size="small">{{ row.class_name || ('C' + row.class_id) }}</el-tag></template></el-table-column>
                <el-table-column label="置信度" width="80"><template #default="{row}"><b :style="{color:row.confidence>0.5?'#67C23A':'#E6A23C'}">{{(row.confidence*100).toFixed(1)}}%</b></template></el-table-column>
                <el-table-column label="中心" width="120"><template #default="{row}">{{ obbCenter(row) }}</template></el-table-column>
                <el-table-column label="尺寸" width="100"><template #default="{row}">{{ obbSize(row) }}</template></el-table-column>
                <el-table-column label="角度" width="80"><template #default="{row}">{{ obbAngle(row) }}°</template></el-table-column>
                <el-table-column label="4 角点">
                  <template #default="{row}"><span v-if="row.polygon" style="font-size:11px;color:#909399">{{ row.polygon.map((p:any)=>`(${Math.round(p.x)},${Math.round(p.y)})`).join(' → ') }}</span></template>
                </el-table-column>
              </el-table>
            </div>
            <div v-else-if="isCls && current.detections.length>0" class="detail-bar">
              <el-table :data="current.detections" stripe size="small" max-height="200" style="width:100%">
                <el-table-column type="index" label="Rank" width="60"><template #default="{$index}">Top-{{ $index + 1 }}</template></el-table-column>
                <el-table-column label="类别" width="120"><template #default="{row}"><el-tag size="small">{{ row.class_name || ('C' + row.class_id) }}</el-tag></template></el-table-column>
                <el-table-column label="置信度" width="100"><template #default="{row}"><b :style="{color:row.confidence>0.5?'#67C23A':'#E6A23C'}">{{(row.confidence*100).toFixed(2)}}%</b></template></el-table-column>
                <el-table-column label="概率分布"><template #default="{row}"><el-progress :percentage="+(row.confidence*100).toFixed(1)" :stroke-width="14" :color="row.confidence>0.5?'#67C23A':'#E6A23C'" :show-text="false" /></template></el-table-column>
              </el-table>
            </div>
          </template>
          <div v-else class="empty-state">
            <el-upload drag :auto-upload="false" :show-file-list="false" :on-change="onSelectFile"
              accept=".bmp,.png,.jpg,.jpeg,.tif,.tiff" multiple style="width:460px">
              <el-icon style="font-size:48px;color:#c0c4cc"><UploadFilled /></el-icon>
              <div style="margin-top:8px;color:#606266">拖拽图片或点击选择</div>
              <div style="font-size:12px;color:#aaa;margin-top:4px">选完图片后点 <b style="color:#409EFF">开始推理</b> 按钮</div>
            </el-upload>
          </div>
        </div>
      </template>

      <!-- 网格视图 -->
      <template v-else>
        <div class="grid-view">
          <div class="grid-toolbar">
            <span>共 {{ history.length }} 张推断结果</span>
            <span style="margin-left:14px">
              <el-radio-group v-model="gridFilter" size="small">
                <el-radio-button label="all">全部</el-radio-button>
                <el-radio-button label="defect">有缺陷/错分</el-radio-button>
                <el-radio-button label="ok">OK/正确</el-radio-button>
              </el-radio-group>
            </span>
            <el-select v-model="gridPageSize" size="small" style="width:100px;margin-left:14px">
              <el-option :value="40" label="40 张/页" />
              <el-option :value="80" label="80 张/页" />
              <el-option :value="120" label="120 张/页" />
            </el-select>
            <el-button text size="small" type="danger" @click="clearHistory" :disabled="history.length===0" style="margin-left:auto">清空</el-button>
          </div>
          <div class="grid-list">
            <div v-for="r in pagedGridItems" :key="r.id" class="grid-cell" :class="{misclassified: isMisclassified(r)}" @click="openLightbox(r)">
              <img :src="gridThumbUrl(r)" class="grid-thumb" loading="lazy" />
              <div v-if="r.task_type==='cls'" class="grid-cls-tag" :style="{background: clsColorOf(r)}">
                {{ clsTop1Name(r) }} {{ (clsTop1Conf(r)*100).toFixed(0) }}%
              </div>
              <div v-else-if="r.num_detections>0" class="grid-det-badge">{{ r.num_detections }}</div>
              <div class="grid-name">{{ r.filename }}</div>
              <el-button text size="small" class="grid-del" @click.stop="delRecord(r.id)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
            <div v-if="pagedGridItems.length===0" class="grid-empty">暂无记录</div>
          </div>
          <div class="grid-pagination">
            <el-pagination
              v-model:current-page="gridPage"
              v-model:page-size="gridPageSize"
              :total="filteredGridItems.length"
              layout="total, prev, pager, next, jumper"
              :page-sizes="[40,80,120]"
            />
          </div>
        </div>
      </template>
    </div>

    <!-- Lightbox -->
    <el-dialog v-model="lightboxOpen" :title="lightboxRec?.filename" width="90vw" top="3vh" :show-close="true" class="lightbox-dialog">
      <div v-if="lightboxRec" class="lightbox-body">
        <div class="lightbox-img-wrap">
          <img :src="lightboxRec.overlay_url || lightboxRec.original_url" class="lightbox-img" />
        </div>
        <div class="lightbox-meta">
          <div v-if="lightboxRec.task_type==='cls'">
            <div>预测：<el-tag :color="clsColorOf(lightboxRec)" effect="dark" disable-transitions>{{ clsTop1Name(lightboxRec) }}</el-tag>
              <b style="color:#67C23A;margin-left:8px">{{(clsTop1Conf(lightboxRec)*100).toFixed(2)}}%</b></div>
            <div v-if="lightboxRec.source_class_id !== undefined && lightboxRec.source_class_id !== null" style="margin-top:6px">
              GT: <b :style="{color: gtMatchColor(lightboxRec)}">{{ gtNameOf(lightboxRec) }}</b>
              <span v-if="!gtMatch(lightboxRec)" style="color:#F56C6C"> ❌ 错分</span>
              <span v-else style="color:#67C23A"> ✓</span>
            </div>
          </div>
          <div v-else>
            检测数：<b :style="{color: lightboxRec.num_detections>0?'#F56C6C':'#67C23A'}">{{ lightboxRec.num_detections }}</b>
          </div>
          <div style="color:#909399;margin-top:6px">耗时 {{ lightboxRec.inference_time }}s · {{ lightboxRec.device }}</div>
        </div>
      </div>
    </el-dialog>

    <!-- 推理训练图 dialog -->
    <el-dialog v-model="showProjectImagesDialog" title="推理训练图（查过拟合）" width="500px">
      <el-form label-width="100px">
        <el-form-item label="范围">
          <el-radio-group v-model="piStatus">
            <el-radio label="labeled">所有已标注</el-radio>
            <el-radio label="reviewed">仅已审核</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="数量上限">
          <el-input-number v-model="piLimit" :min="1" :max="2000" :step="50" style="width:160px" />
          <span style="margin-left:10px;color:#909399;font-size:12px">最多 2000 张</span>
        </el-form-item>
        <el-form-item label="抽样方式">
          <el-radio-group v-model="piSample">
            <el-radio :label="true">随机抽样</el-radio>
            <el-radio :label="false">最新优先</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showProjectImagesDialog=false">取消</el-button>
        <el-button type="primary" @click="runProjectImages">开始推理</el-button>
      </template>
    </el-dialog>

    <!-- Loading -->
    <div v-if="inferring" class="loading-overlay">
      <el-icon class="is-loading" style="font-size:36px;color:#409EFF"><Loading /></el-icon>
      <div style="color:#fff;margin-top:10px">{{ inferMsg }}</div>
      <el-progress v-if="inferTotal>1" :percentage="Math.round(inferDone/inferTotal*100)" :stroke-width="6" style="width:300px;margin-top:14px" />
      <el-button v-if="inferTotal>1" size="small" type="danger" @click="cancelInfer" style="margin-top:14px">取消</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, reactive, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api/index'
import type { UploadFile } from 'element-plus'

const props = defineProps<{ id: string }>()
const router = useRouter()

interface ModelInfo { task_id:number; model_format:string; label:string; model_path:string }
interface Det {
  class_id:number; class_name?:string; confidence:number;
  bbox?:{x1:number;y1:number;x2:number;y2:number};
  polygon?:Array<{x:number;y:number}>
}
interface Rec { id:number; filename:string; num_detections:number; inference_time:number; detections:Det[]; original_url:string; overlay_url:string; overlay_morph_url?:string|null; mask_url:string; device:string; created_at:string|null; task_type?:string; source_image_id?:number; source_class_id?:number|null }

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
const inferTotal = ref(0)
const inferDone = ref(0)
let cancelFlag = false
const viewMode = ref<'original'|'overlay'|'mask'|'compare'>('overlay')
const showMorph = ref(false)
const viewLayout = ref<'list'|'grid'>('list')

const history = ref<Rec[]>([])
const selId = ref<number|null>(null)
const current = computed(() => history.value.find(r => r.id === selId.value) || null)

// 待推理队列：单一数据源，避免两个数组索引耦合
interface PendingItem { file: File; url: string }
const pending = ref<PendingItem[]>([])

// 项目类别（用于 cls GT 对照）+ 项目类型（决定"切割小图"按钮是否显示）
const projectClasses = ref<Array<{class_index:number; name:string; color:string; id:number}>>([])
const projectTaskType = ref<string>('seg')

// 切割小图状态
const cropping = ref(false)

// 推理训练图 dialog
const showProjectImagesDialog = ref(false)
const piStatus = ref<'labeled'|'reviewed'>('labeled')
const piLimit = ref(100)
const piSample = ref(true)

// 网格视图分页
const gridPage = ref(1)
const gridPageSize = ref(40)
const gridFilter = ref<'all'|'defect'|'ok'>('all')

// Lightbox
const lightboxOpen = ref(false)
const lightboxRec = ref<Rec|null>(null)

const isCls = computed(() => {
  const r = current.value
  if (!r) return false
  if (r.task_type === 'cls') return true
  const dets = r.detections || []
  return dets.length > 0 && !dets[0].bbox && !dets[0].polygon
})
const isObb = computed(() => {
  const r = current.value
  if (!r) return false
  if (r.task_type === 'obb') return true
  const dets = r.detections || []
  return dets.length > 0 && Array.isArray(dets[0].polygon) && dets[0].polygon!.length === 4
})

function obbCenter(row: Det): string {
  const p = row.polygon; if (!p || p.length < 4) return '-'
  const cx = (p[0].x + p[1].x + p[2].x + p[3].x) / 4
  const cy = (p[0].y + p[1].y + p[2].y + p[3].y) / 4
  return `(${Math.round(cx)}, ${Math.round(cy)})`
}
function obbSize(row: Det): string {
  const p = row.polygon; if (!p || p.length < 4) return '-'
  const e1 = Math.hypot(p[1].x - p[0].x, p[1].y - p[0].y)
  const e2 = Math.hypot(p[2].x - p[1].x, p[2].y - p[1].y)
  return `${Math.round(Math.max(e1, e2))}×${Math.round(Math.min(e1, e2))}`
}
function obbAngle(row: Det): string {
  const p = row.polygon; if (!p || p.length < 4) return '0'
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
  if (isCls.value) return current.value.original_url
  const mode = viewMode.value === 'compare' ? 'overlay' : viewMode.value
  if (mode === 'overlay' && showMorph.value && current.value.overlay_morph_url) return current.value.overlay_morph_url
  return (current.value as any)[mode + '_url']
})

// ---- cls 工具 ----
function clsTop1(r: Rec | null): Det | null {
  if (!r || !r.detections || r.detections.length === 0) return null
  return r.detections[0]
}
function clsTop1Name(r: Rec | null): string { const d = clsTop1(r); return d ? (d.class_name || ('C' + d.class_id)) : '-' }
function clsTop1Conf(r: Rec | null): number { const d = clsTop1(r); return d ? d.confidence : 0 }
function clsLabelOf(r: Rec): string { const d = clsTop1(r); if (!d) return '-'; return `${d.class_name || ('C' + d.class_id)} ${(d.confidence*100).toFixed(1)}%` }
const _clsColors = ['#F56C6C','#67C23A','#E6A23C','#409EFF','#9254DE','#13C2C2','#FA541C','#A0D911']
function clsColorOf(r: Rec | null): string { const d = clsTop1(r); if (!d) return '#909399'; return _clsColors[(d.class_id ?? 0) % _clsColors.length] }

// ---- GT 对照（推理训练图用） ----
function gtNameOf(r: Rec): string {
  if (r.source_class_id == null) return '-'
  const dc = projectClasses.value.find(c => c.id === r.source_class_id)
  return dc ? dc.name : `class_id=${r.source_class_id}`
}
function gtMatch(r: Rec): boolean {
  if (r.source_class_id == null) return true
  const t = clsTop1(r)
  if (!t) return false
  return (t.class_name || '') === gtNameOf(r)
}
function gtMatchColor(r: Rec): string {
  if (r.source_class_id == null) return '#909399'
  return gtMatch(r) ? '#67C23A' : '#F56C6C'
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
function onWheelCmp(e: WheelEvent, k: string) { const d = e.deltaY > 0 ? 0.9 : 1.1; cmpZoom[k].z = Math.max(0.1, Math.min(20, cmpZoom[k].z * d)) }
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
  try {
    const { data: d } = await api.get('/inference/devices')
    devices.value = d
    const first = d.find((x: DeviceInfo) => x.available)
    if (first) device.value = first.id
  } catch {}
  // 加载项目类别 + task_type
  try {
    const { data: proj } = await api.get(`/projects/${props.id}`)
    projectClasses.value = proj.defect_classes || []
    projectTaskType.value = proj.task_type || 'seg'
  } catch {}
  await loadHistory()
})

onUnmounted(() => {
  pending.value.forEach(p => URL.revokeObjectURL(p.url))
})

async function loadHistory() {
  const { data } = await api.get('/inference/history', { params: { project_id: props.id, page_size: 200 } })
  history.value = data.items
  if (data.items.length > 0 && !selId.value) selId.value = data.items[0].id
}

function selectRecord(r: Rec) {
  selId.value = r.id
  resetZoom()
  for (const k of ['original','overlay','mask']) cmpZoom[k] = {z:1,x:0,y:0}
  const cls = r.task_type === 'cls' || (r.detections && r.detections.length > 0 && !r.detections[0].bbox)
  if (cls && viewMode.value === 'compare') viewMode.value = 'original'
}

// ---- 选图（不自动推理） ----
function onSelectFile(file: UploadFile) {
  if (!file.raw) return
  pending.value.push({ file: file.raw, url: URL.createObjectURL(file.raw) })
}
function removePending(i: number) {
  URL.revokeObjectURL(pending.value[i].url)
  pending.value.splice(i, 1)
}
function clearPending() {
  pending.value.forEach(p => URL.revokeObjectURL(p.url))
  pending.value = []
}

// ---- 推理 ----
function buildInferFD(extras: Record<string, string | number | File>): FormData {
  const fd = new FormData()
  for (const [k, v] of Object.entries(extras)) fd.append(k, v as any)
  fd.append('project_id', props.id)
  fd.append('task_id', String(selModel.value!.task_id))
  fd.append('model_path', selModel.value!.model_path)
  fd.append('conf', String(conf.value))
  fd.append('iou', String(iou.value))
  fd.append('resize_size', String(resizeSize.value))
  fd.append('device', device.value)
  return fd
}
async function runByFile(f: File): Promise<Rec | null> {
  if (!selModel.value) return null
  const { data } = await api.post('/inference/run', buildInferFD({ file: f }),
    { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 300000 })
  return data
}
async function runByImageId(imageId: number): Promise<Rec | null> {
  if (!selModel.value) return null
  const { data } = await api.post('/inference/run-by-image-id', buildInferFD({ image_id: imageId }),
    { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 300000 })
  return data
}

async function runPending() {
  if (!selModel.value) { ElMessage.warning('请先选择模型'); return }
  if (pending.value.length === 0) return
  // 推理过程中不允许新增 → 复制一份
  const queue = pending.value.map(p => p.file)
  await runBatch(
    queue.map(f => ({ label: f.name, run: () => runByFile(f), selectFirst: true })),
  )
  clearPending()
  resetZoom()
}

async function runProjectImages() {
  showProjectImagesDialog.value = false
  if (!selModel.value) { ElMessage.warning('请先选择模型'); return }
  let imgs: any[] = []
  try {
    const { data } = await api.get('/inference/project-images', {
      params: { project_id: props.id, status: piStatus.value, limit: piLimit.value, sample: piSample.value },
    })
    imgs = data.items
    if (imgs.length === 0) { ElMessage.warning('没有可推理的图片'); return }
    ElMessage.info(`将推理 ${imgs.length} 张图`)
  } catch { ElMessage.error('获取图片列表失败'); return }
  await runBatch(imgs.map(img => ({ label: img.filename, run: () => runByImageId(img.id) })))
}

interface BatchTask { label: string; run: () => Promise<Rec | null>; selectFirst?: boolean }

async function runBatch(tasks: BatchTask[]) {
  inferring.value = true
  cancelFlag = false
  inferTotal.value = tasks.length
  inferDone.value = 0
  const failed: string[] = []
  for (let i = 0; i < tasks.length; i++) {
    if (cancelFlag) break
    const t = tasks[i]
    inferMsg.value = `${i+1}/${tasks.length} ${t.label}`
    try {
      const data = await t.run()
      if (data) {
        history.value.unshift(data)
        if (t.selectFirst && i === 0) selId.value = data.id
      }
    } catch { failed.push(t.label) }
    inferDone.value = i + 1
  }
  inferring.value = false
  if (cancelFlag) ElMessage.info(`已取消 (${inferDone.value}/${inferTotal.value})`)
  else if (failed.length > 0) ElMessage.warning(`完成，${failed.length} 张失败`)
  else ElMessage.success(`推理完成 ${tasks.length} 张`)
}

function cancelInfer() { cancelFlag = true }

// ---- 切割小图（seg 项目，给二级分类模型当训练集） ----
async function cropDefects() {
  try {
    await ElMessageBox.confirm(
      '将切割本项目所有推理结果中的缺陷小图，按类别打包成 zip 下载到本地。\n\n' +
      '规则：长边 > 512 缩放到 512×512；长边 < 128 向外膨胀到 128×128；中间档按长边补正方形原样切。\n\n' +
      'zip 解压后：每个类别一个文件夹，可直接作为 yolo-cls 训练集。',
      '切割小图',
      { type: 'info', confirmButtonText: '开始下载', cancelButtonText: '取消' }
    )
  } catch { return }

  cropping.value = true
  try {
    const resp = await api.post('/inference/crop-defects', null, {
      params: { project_id: props.id },
      responseType: 'blob',
      timeout: 600000,
    })
    const blob = resp.data as Blob
    // 错误响应也是 blob，要先看 content-type 判断
    if (!blob.type.includes('zip')) {
      const text = await blob.text()
      let msg = '切割失败'
      try { msg = JSON.parse(text).detail || msg } catch {}
      ElMessage.error(msg)
      return
    }
    // 触发下载
    const disp = (resp.headers['content-disposition'] as string) || ''
    const m = disp.match(/filename="([^"]+)"/)
    const fname = m ? m[1] : `project_${props.id}_crops.zip`
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = fname
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.URL.revokeObjectURL(url)
    const count = resp.headers['x-crop-count']
    ElMessage.success(`已下载 ${fname}${count ? ` (${count} 张)` : ''}`)
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || '切割失败'
    ElMessage.error(typeof msg === 'string' ? msg : '切割失败')
  } finally {
    cropping.value = false
  }
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

// ---- 网格视图 ----
function isMisclassified(r: Rec): boolean {
  // cls 项目：错分
  if (r.task_type === 'cls' && r.source_class_id != null) return !gtMatch(r)
  return false
}
function gridThumbUrl(r: Rec): string {
  // cls 用原图，其他用 overlay
  if (r.task_type === 'cls') return r.original_url
  return r.overlay_url || r.original_url
}
const filteredGridItems = computed(() => {
  const arr = history.value
  if (gridFilter.value === 'all') return arr
  if (gridFilter.value === 'defect') {
    return arr.filter(r => {
      if (r.task_type === 'cls') return r.source_class_id != null && !gtMatch(r)
      return r.num_detections > 0
    })
  }
  // ok
  return arr.filter(r => {
    if (r.task_type === 'cls') return r.source_class_id == null || gtMatch(r)
    return r.num_detections === 0
  })
})
const pagedGridItems = computed(() => {
  const start = (gridPage.value - 1) * gridPageSize.value
  return filteredGridItems.value.slice(start, start + gridPageSize.value)
})
watch(gridFilter, () => { gridPage.value = 1 })
watch(gridPageSize, () => { gridPage.value = 1 })

function openLightbox(r: Rec) { lightboxRec.value = r; lightboxOpen.value = true; selId.value = r.id }
</script>

<style scoped>
.infer-page { display:flex; flex-direction:column; height:100vh; background:#f0f2f5; }
.top-bar { display:flex; justify-content:space-between; align-items:center; padding:6px 14px; background:#fff; border-bottom:1px solid #e4e7ed; flex-shrink:0; }
.top-left { display:flex; align-items:center; gap:6px; }
.top-controls { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.p-label { font-size:12px; color:#909399; }

/* 待推理队列条 */
.pending-bar { display:flex; align-items:center; gap:10px; padding:8px 14px; background:#fffbe6; border-bottom:1px solid #faad14; flex-shrink:0; max-height:108px; overflow:hidden; }
.pending-label { font-size:13px; color:#874d00; font-weight:600; flex-shrink:0; }
.pending-thumbs { display:flex; gap:8px; overflow-x:auto; padding-bottom:4px; }
.pending-item { position:relative; flex-shrink:0; width:80px; }
.pending-item img { width:80px; height:80px; object-fit:cover; border-radius:4px; border:1px solid #faad14; }
.pending-name { font-size:10px; color:#666; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.pending-del { position:absolute; right:0; top:0; padding:2px; background:rgba(255,255,255,.85); border-radius:0 4px 0 4px; }

.main-body { display:flex; flex:1; overflow:hidden; }

/* 列表视图 */
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

.viewer { flex:1; display:flex; flex-direction:column; overflow:hidden; }
.view-bar { display:flex; justify-content:space-between; align-items:center; padding:8px 14px; background:#fff; border-bottom:1px solid #e4e7ed; flex-shrink:0; gap:12px; flex-wrap:wrap; }
.view-stats { font-size:12px; color:#909399; }
.cls-top1 { display:flex; align-items:center; font-size:13px; font-weight:600; color:#303133; }
.img-container { flex:1; overflow:hidden; background:#111; display:flex; justify-content:center; align-items:center; user-select:none; }
.zoom-img { max-width:100%; max-height:100%; object-fit:contain; transform-origin:center center; transition:none; }
.compare-container { flex:1; display:grid; grid-template-columns:1fr 1fr 1fr; gap:4px; background:#111; overflow:hidden; }
.cmp-cell { display:flex; flex-direction:column; min-height:0; overflow:hidden; }
.cmp-label { text-align:center; font-size:11px; color:#888; padding:4px 0; background:#1a1a1a; flex-shrink:0; }
.cmp-img-wrap { flex:1; overflow:hidden; display:flex; justify-content:center; align-items:center; user-select:none; }
.detail-bar { padding:6px 14px; background:#fff; border-top:1px solid #e4e7ed; flex-shrink:0; max-height:180px; overflow-y:auto; }
.empty-state { flex:1; display:flex; justify-content:center; align-items:center; }

/* 网格视图 */
.grid-view { flex:1; display:flex; flex-direction:column; overflow:hidden; background:#fff; }
.grid-toolbar { display:flex; align-items:center; padding:10px 14px; border-bottom:1px solid #e4e7ed; gap:10px; font-size:13px; color:#606266; flex-shrink:0; }
.grid-list { flex:1; overflow-y:auto; padding:12px; display:grid; grid-template-columns:repeat(auto-fill, minmax(180px, 1fr)); gap:10px; }
.grid-cell { position:relative; aspect-ratio:1; background:#f0f2f5; border-radius:6px; overflow:hidden; cursor:pointer; border:2px solid transparent; transition:transform .15s, border-color .15s; }
.grid-cell:hover { transform:scale(1.02); border-color:#409EFF; }
.grid-cell.misclassified { border-color:#F56C6C; box-shadow:0 0 0 2px rgba(245,108,108,.25); }
.grid-thumb { width:100%; height:100%; object-fit:cover; }
.grid-cls-tag { position:absolute; top:4px; left:4px; padding:2px 8px; border-radius:4px; color:#fff; font-size:11px; font-weight:600; }
.grid-det-badge { position:absolute; top:4px; right:4px; min-width:22px; height:22px; padding:0 6px; line-height:22px; text-align:center; background:#F56C6C; color:#fff; border-radius:11px; font-size:12px; font-weight:600; }
.grid-name { position:absolute; bottom:0; left:0; right:0; padding:4px 6px; background:rgba(0,0,0,.55); color:#fff; font-size:11px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.grid-del { position:absolute; right:4px; top:4px; opacity:0; transition:opacity .15s; background:rgba(255,255,255,.85); border-radius:50%; padding:4px; }
.grid-cell:hover .grid-del { opacity:1; }
.grid-empty { grid-column:1/-1; text-align:center; padding:40px 0; color:#c0c4cc; font-size:14px; }
.grid-pagination { padding:10px 14px; border-top:1px solid #e4e7ed; display:flex; justify-content:center; flex-shrink:0; }

/* Lightbox */
.lightbox-dialog :deep(.el-dialog__body) { padding:10px 20px; }
.lightbox-body { display:flex; gap:14px; }
.lightbox-img-wrap { flex:1; background:#111; min-height:60vh; display:flex; justify-content:center; align-items:center; border-radius:6px; overflow:hidden; }
.lightbox-img { max-width:100%; max-height:80vh; object-fit:contain; }
.lightbox-meta { width:240px; padding:10px; background:#fafafa; border-radius:6px; font-size:13px; color:#303133; }

.loading-overlay { position:fixed; top:0; left:0; right:0; bottom:0; z-index:9999; background:rgba(0,0,0,.55); display:flex; flex-direction:column; justify-content:center; align-items:center; }
</style>
