<template>
  <div class="cls-annotator" tabindex="0" ref="rootRef" @keydown="onKD">
    <!-- 顶部 toolbar -->
    <div class="toolbar">
      <div class="toolbar-left">
        <el-button text @click="goBack"><el-icon><ArrowLeft /></el-icon> 返回项目</el-button>
        <el-divider direction="vertical" />
        <span class="title">分类标注 — {{ project?.name }}</span>
      </div>
      <div class="toolbar-center">
        <el-radio-group v-model="filter" size="small" @change="reload">
          <el-radio-button label="all">全部 ({{ stats.total }})</el-radio-button>
          <el-radio-button label="unlabeled">未标注 ({{ stats.unlabeled }})</el-radio-button>
          <el-radio-button label="labeled">已标注 ({{ stats.labeled }})</el-radio-button>
        </el-radio-group>
        <el-divider direction="vertical" />
        <span class="hint">
          点击选中（{{ selected.size }} / {{ items.length }}）·
          Ctrl/Shift 多选 ·
          <b>1-9</b> 数字键打标 ·
          <b>0</b> 清空标签 ·
          <b>Ctrl+A</b> 全选
        </span>
      </div>
      <div class="toolbar-right">
        <span class="save-indicator" :class="saveState">{{ saveStateText }}</span>
        <el-button size="small" @click="selectAll" :disabled="items.length === 0">全选</el-button>
        <el-button size="small" @click="clearSelection" :disabled="selected.size === 0">取消选中</el-button>
      </div>
    </div>

    <div class="main">
      <!-- 缩略图网格 6×6 -->
      <div class="grid-container" ref="gridRef" @scroll="onScroll">
        <div v-if="items.length === 0 && !loading" class="empty">
          <el-empty :description="filter === 'all' ? '该项目暂无图片' : '此筛选下无图片'" />
        </div>
        <div class="grid">
          <div
            v-for="img in items"
            :key="img.id"
            :class="['cell', { selected: selected.has(img.id) }]"
            :style="{ borderColor: cellBorderColor(img) }"
            @click="onCellClick(img, $event)"
          >
            <img :src="thumbUrl(img.id)" loading="lazy" />
            <div class="cell-tag" v-if="img.class_id" :style="{ background: classColor(img.class_id) }">
              {{ classShortName(img.class_id) }}
            </div>
            <div class="cell-id">#{{ img.id }}</div>
          </div>
        </div>
        <div v-if="loading" class="loading-row">加载中...</div>
        <div v-else-if="!hasMore && items.length > 0" class="loading-row">— 已加载全部 —</div>
      </div>

      <!-- 右侧类别面板 -->
      <div class="side">
        <div class="side-title">类别（按数字键快速打标）</div>
        <div class="class-list">
          <div
            v-for="(dc, idx) in defectClasses"
            :key="dc.id"
            :class="['class-row', { active: hoveredClass === dc.id }]"
            @click="applyClass(dc.id!)"
            @mouseenter="hoveredClass = dc.id || null"
          >
            <span class="key-badge">{{ idx + 1 }}</span>
            <span class="cls-dot" :style="{ background: dc.color }"></span>
            <span class="cls-name">{{ dc.name }}</span>
            <span class="cls-count">{{ classCounts.get(dc.id!) || 0 }}</span>
          </div>
          <div class="class-row clear-row" @click="applyClass(null)">
            <span class="key-badge">0</span>
            <span class="cls-dot" style="background:#666"></span>
            <span class="cls-name">清空标签</span>
          </div>
        </div>

        <div class="stats">
          <div class="stat-row"><span>总计</span><b>{{ stats.total }}</b></div>
          <div class="stat-row"><span>已标注</span><b style="color:#67C23A">{{ stats.labeled }}</b></div>
          <div class="stat-row"><span>未标注</span><b style="color:#909399">{{ stats.unlabeled }}</b></div>
          <div class="stat-row"><span>进度</span><b>{{ progressPct }}%</b></div>
          <el-progress :percentage="progressPct" :stroke-width="6" :show-text="false" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { projectApi, type DefectClass, type ProjectStats } from '../api/project'
import { imageApi, type ImageInfo } from '../api/image'

const props = defineProps<{ projectId: string }>()
const router = useRouter()
const rootRef = ref<HTMLElement>()
const gridRef = ref<HTMLElement>()

const project = ref<ProjectStats | null>(null)
const defectClasses = ref<DefectClass[]>([])
const items = ref<ImageInfo[]>([])
const selected = ref<Set<number>>(new Set())
const lastClickedId = ref<number | null>(null)
const filter = ref<'all' | 'unlabeled' | 'labeled'>('all')
const loading = ref(false)
const page = ref(1)
const pageSize = 60
const hasMore = ref(true)
const hoveredClass = ref<number | null>(null)

const saveState = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
const saveStateText = computed(() => ({ idle: '', saving: '保存中…', saved: '已保存', error: '保存失败' }[saveState.value]))

const stats = computed(() => {
  const total = project.value?.total_images || 0
  const labeled = project.value?.labeled_count || 0
  return { total, labeled, unlabeled: total - labeled }
})
const progressPct = computed(() => stats.value.total ? Math.round(stats.value.labeled * 100 / stats.value.total) : 0)

const classCounts = computed(() => {
  const m = new Map<number, number>()
  for (const img of items.value) {
    if (img.class_id) m.set(img.class_id, (m.get(img.class_id) || 0) + 1)
  }
  return m
})

function classColor(cid: number) {
  return defectClasses.value.find(c => c.id === cid)?.color || '#999'
}
function classShortName(cid: number) {
  const n = defectClasses.value.find(c => c.id === cid)?.name || ''
  return n.length > 6 ? n.slice(0, 6) : n
}
function cellBorderColor(img: ImageInfo) {
  if (selected.value.has(img.id)) return '#409EFF'
  if (img.class_id) return classColor(img.class_id)
  return 'transparent'
}
function thumbUrl(id: number) { return imageApi.getFileUrl(id, true) }

async function loadProject() {
  const { data } = await projectApi.get(parseInt(props.projectId))
  project.value = data
  defectClasses.value = data.defect_classes
  if (data.task_type !== 'cls') {
    ElMessage.warning('此页面仅适用分类项目')
    router.push(`/project/${props.projectId}`)
  }
}

async function loadPage(append = false) {
  if (loading.value) return
  loading.value = true
  try {
    const params: any = { page: page.value, page_size: pageSize }
    if (filter.value !== 'all') params.status = filter.value
    const { data } = await imageApi.list(parseInt(props.projectId), params)
    if (append) items.value.push(...data.items)
    else items.value = data.items
    hasMore.value = data.items.length === pageSize
  } finally {
    loading.value = false
  }
}

async function reload() {
  page.value = 1
  hasMore.value = true
  selected.value.clear()
  await loadPage(false)
  // 重新读项目统计
  await loadProject()
}

async function loadMore() {
  if (!hasMore.value || loading.value) return
  page.value += 1
  await loadPage(true)
}

function onScroll() {
  if (!gridRef.value) return
  const el = gridRef.value
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 200) {
    loadMore()
  }
}

function onCellClick(img: ImageInfo, e: MouseEvent) {
  if (e.shiftKey && lastClickedId.value !== null) {
    // 范围选
    const startIdx = items.value.findIndex(i => i.id === lastClickedId.value)
    const endIdx = items.value.findIndex(i => i.id === img.id)
    if (startIdx >= 0 && endIdx >= 0) {
      const [from, to] = startIdx < endIdx ? [startIdx, endIdx] : [endIdx, startIdx]
      for (let i = from; i <= to; i++) selected.value.add(items.value[i].id)
    }
  } else if (e.ctrlKey || e.metaKey) {
    // 多选切换
    if (selected.value.has(img.id)) selected.value.delete(img.id)
    else selected.value.add(img.id)
  } else {
    // 单选切换
    if (selected.value.has(img.id) && selected.value.size === 1) {
      selected.value.clear()
    } else {
      selected.value.clear()
      selected.value.add(img.id)
    }
  }
  lastClickedId.value = img.id
  // 触发 reactivity
  selected.value = new Set(selected.value)
}

function selectAll() {
  for (const img of items.value) selected.value.add(img.id)
  selected.value = new Set(selected.value)
}
function clearSelection() {
  selected.value.clear()
  selected.value = new Set()
}

async function applyClass(classId: number | null) {
  if (selected.value.size === 0) {
    ElMessage.info('请先选择图片')
    return
  }
  saveState.value = 'saving'
  const ids = Array.from(selected.value)
  try {
    await imageApi.batchSetClass(parseInt(props.projectId), ids, classId)
    // 更新本地状态
    for (const img of items.value) {
      if (selected.value.has(img.id)) {
        img.class_id = classId
        if (img.status !== 'reviewed') {
          img.status = classId ? 'labeled' : 'unlabeled'
        }
      }
    }
    saveState.value = 'saved'
    setTimeout(() => { if (saveState.value === 'saved') saveState.value = 'idle' }, 1500)
    // 刷项目统计（标注计数变化）
    await loadProject()
  } catch (e: any) {
    saveState.value = 'error'
    ElMessage.error('打标失败：' + (e?.response?.data?.detail || e?.message || ''))
  }
}

function onKD(e: KeyboardEvent) {
  if (e.ctrlKey && (e.key === 'a' || e.key === 'A')) {
    e.preventDefault()
    selectAll()
    return
  }
  if (e.key === 'Escape') {
    clearSelection()
    return
  }
  if (e.key >= '0' && e.key <= '9') {
    e.preventDefault()
    const idx = parseInt(e.key)
    if (idx === 0) {
      applyClass(null)
    } else if (idx >= 1 && idx <= defectClasses.value.length) {
      applyClass(defectClasses.value[idx - 1].id!)
    }
  }
}

function goBack() { router.push(`/project/${props.projectId}`) }

onMounted(async () => {
  await loadProject()
  if (project.value?.task_type === 'cls') {
    await loadPage(false)
  }
  rootRef.value?.focus()
})
onBeforeUnmount(() => {})
</script>

<style scoped>
.cls-annotator { display: flex; flex-direction: column; height: 100vh; background: #1a1a1a; color: #ddd; outline: none; }
.toolbar { display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: #2d2d2d; border-bottom: 1px solid #444; flex-wrap: wrap; gap: 8px; }
.toolbar-left, .toolbar-center, .toolbar-right { display: flex; align-items: center; gap: 8px; }
.title { font-weight: 600; font-size: 14px; }
.hint { font-size: 12px; color: #aaa; }
.save-indicator { font-size: 12px; min-width: 60px; text-align: right; }
.save-indicator.saving { color: #909399; }
.save-indicator.saved { color: #67C23A; }
.save-indicator.error { color: #F56C6C; }

.main { display: flex; flex: 1; overflow: hidden; }

.grid-container { flex: 1; overflow-y: auto; padding: 12px; }
.empty { padding: 60px 0; }
.grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 8px;
}
.cell {
  position: relative;
  aspect-ratio: 1 / 1;
  background: #2a2a2a;
  border: 3px solid transparent;
  border-radius: 6px;
  overflow: hidden;
  cursor: pointer;
  transition: transform .1s, border-color .15s;
}
.cell:hover { transform: scale(1.02); }
.cell.selected {
  box-shadow: 0 0 0 2px #409EFF;
}
.cell img { width: 100%; height: 100%; object-fit: cover; display: block; }
.cell-tag {
  position: absolute;
  top: 4px; left: 4px;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 10px;
  color: #fff;
  font-weight: 600;
  text-shadow: 0 1px 2px rgba(0,0,0,.6);
  max-width: calc(100% - 8px);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.cell-id { position: absolute; bottom: 2px; right: 4px; font-size: 9px; color: rgba(255,255,255,.7); text-shadow: 0 1px 1px rgba(0,0,0,.5); }
.loading-row { text-align: center; color: #888; font-size: 12px; padding: 20px; }

.side { width: 260px; background: #252525; border-left: 1px solid #444; display: flex; flex-direction: column; padding: 12px; }
.side-title { font-weight: 600; font-size: 13px; color: #aaa; margin-bottom: 12px; }
.class-list { display: flex; flex-direction: column; gap: 4px; flex: 1; overflow-y: auto; }
.class-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: background .12s;
  user-select: none;
}
.class-row:hover { background: #333; }
.class-row.active { background: #1a3a5c; }
.class-row.clear-row { margin-top: 6px; border-top: 1px dashed #555; padding-top: 12px; color: #888; }
.key-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px; height: 22px;
  border-radius: 4px;
  background: #555;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  border: 1px solid #777;
}
.cls-dot { width: 14px; height: 14px; border-radius: 3px; flex-shrink: 0; }
.cls-name { flex: 1; font-size: 13px; }
.cls-count { font-size: 12px; color: #888; min-width: 24px; text-align: right; }

.stats { margin-top: 16px; padding-top: 12px; border-top: 1px solid #333; }
.stat-row { display: flex; justify-content: space-between; font-size: 12px; padding: 3px 0; color: #aaa; }
.stat-row b { color: #ddd; }
</style>
