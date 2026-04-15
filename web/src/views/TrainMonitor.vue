<template>
  <div class="page-container" style="max-width:1600px">
    <div class="page-header">
      <div style="display:flex;align-items:center;gap:12px">
        <el-button text @click="router.push(`/project/${id}`)"><el-icon><ArrowLeft /></el-icon> 返回项目</el-button>
        <h1>训练监控</h1>
      </div>
      <el-button type="primary" @click="router.push(`/project/${id}/train`)">
        <el-icon><Plus /></el-icon> 新建训练
      </el-button>
    </div>

    <!-- 任务列表 -->
    <el-card shadow="never" style="margin-bottom:20px">
      <template #header><span style="font-weight:600">训练任务</span></template>
      <el-table :data="tasks" stripe @row-click="selectTask" highlight-current-row style="width:100%">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="task_name" label="任务名称" min-width="160" />
        <el-table-column label="状态" width="120">
          <template #default="{row}">
            <el-tag :type="statusType(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="200">
          <template #default="{row}">
            <el-progress :percentage="row.epochs>0?Math.round(row.current_epoch/row.epochs*100):0" :status="row.status==='completed'?'success':row.status==='failed'?'exception':''" :stroke-width="14" :text-inside="true">
            </el-progress>
            <span style="font-size:11px;color:#999">{{ row.current_epoch }}/{{ row.epochs }}</span>
          </template>
        </el-table-column>
        <el-table-column label="最佳 mAP50" width="120">
          <template #default="{row}">
            <span v-if="row.best_map50" style="font-weight:600;color:#67C23A">{{ (row.best_map50*100).toFixed(1) }}%</span>
            <span v-else style="color:#999">-</span>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="120">
          <template #default="{row}">
            <span v-if="row.started_at && row.finished_at">{{ duration(row.started_at, row.finished_at) }}</span>
            <span v-else-if="row.started_at">运行中...</span>
            <span v-else style="color:#999">-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{row}">
            <el-button v-if="row.status==='training'||row.status==='preparing'" type="warning" text size="small" @click.stop="cancelTask(row.id)">取消</el-button>
            <el-button v-if="row.status==='completed'||row.status==='failed'||row.status==='cancelled'" type="danger" text size="small" @click.stop="deleteTask(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 训练曲线 -->
    <template v-if="selectedTaskId">
      <!-- 错误信息 -->
      <el-alert v-if="selectedTask?.error_message" type="error" :closable="false" style="margin-bottom:16px">
        <template #title>训练失败</template>
        <pre style="white-space:pre-wrap;font-size:12px;max-height:200px;overflow:auto">{{ selectedTask.error_message }}</pre>
      </el-alert>

      <!-- Loss 曲线 -->
      <el-card shadow="never" style="margin-bottom:20px">
        <template #header>
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span style="font-weight:600">Loss 曲线 — {{ selectedTask?.task_name }}</span>
            <span style="font-size:12px;color:#999">Epoch {{ epochs.length }} | 蓝=Train 红=Val</span>
          </div>
        </template>
        <div class="charts-grid">
          <div class="chart-box">
            <div ref="chartBoxLoss" style="width:100%;height:280px"></div>
          </div>
          <div class="chart-box">
            <div ref="chartSegLoss" style="width:100%;height:280px"></div>
          </div>
          <div class="chart-box">
            <div ref="chartClsLoss" style="width:100%;height:280px"></div>
          </div>
          <div class="chart-box">
            <div ref="chartDflLoss" style="width:100%;height:280px"></div>
          </div>
        </div>
      </el-card>

      <!-- 验证指标曲线 -->
      <el-card shadow="never" style="margin-bottom:20px">
        <template #header><span style="font-weight:600">验证指标</span></template>
        <div class="charts-grid">
          <div class="chart-box">
            <div ref="chartPrecision" style="width:100%;height:280px"></div>
          </div>
          <div class="chart-box">
            <div ref="chartRecall" style="width:100%;height:280px"></div>
          </div>
          <div class="chart-box">
            <div ref="chartMap50" style="width:100%;height:280px"></div>
          </div>
          <div class="chart-box">
            <div ref="chartMap5095" style="width:100%;height:280px"></div>
          </div>
        </div>
      </el-card>

      <!-- 学习率曲线 -->
      <el-card shadow="never" style="margin-bottom:20px">
        <template #header><span style="font-weight:600">学习率</span></template>
        <div ref="chartLr" style="width:100%;height:250px"></div>
      </el-card>
    </template>

    <el-empty v-else-if="tasks.length===0" description="暂无训练任务" />
    <el-empty v-else description="点击上方任务查看训练曲线" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch, nextTick, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as echarts from 'echarts'
import { trainApi, type TrainTask, type EpochLog } from '../api/train'

const props = defineProps<{ id: string }>()
const router = useRouter()
const projectId = parseInt(props.id)

const tasks = ref<TrainTask[]>([])
const selectedTaskId = ref<number|null>(null)
const epochs = ref<EpochLog[]>([])
let pollTimer: any = null

const selectedTask = computed(() => tasks.value.find(t => t.id === selectedTaskId.value))

// Chart refs
const chartBoxLoss = ref<HTMLElement>()
const chartSegLoss = ref<HTMLElement>()
const chartClsLoss = ref<HTMLElement>()
const chartDflLoss = ref<HTMLElement>()
const chartPrecision = ref<HTMLElement>()
const chartRecall = ref<HTMLElement>()
const chartMap50 = ref<HTMLElement>()
const chartMap5095 = ref<HTMLElement>()
const chartLr = ref<HTMLElement>()

let charts: echarts.ECharts[] = []

onMounted(async () => {
  await loadTasks()
  // 自动选中最新任务
  if (tasks.value.length > 0) {
    selectTask(tasks.value[0])
  }
  // 轮询刷新（训练中时每 5 秒刷新）
  pollTimer = setInterval(async () => {
    const running = tasks.value.some(t => t.status === 'training' || t.status === 'preparing' || t.status === 'pending')
    if (running) {
      await loadTasks()
      if (selectedTaskId.value) await loadEpochs()
    }
  }, 5000)
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
  charts.forEach(c => c.dispose())
})

async function loadTasks() {
  const { data } = await trainApi.listTasks(projectId)
  tasks.value = data
}

async function selectTask(row: TrainTask) {
  selectedTaskId.value = row.id
  await loadEpochs()
}

async function loadEpochs() {
  if (!selectedTaskId.value) return
  const { data } = await trainApi.getEpochLogs(selectedTaskId.value)
  epochs.value = data
  await nextTick()
  renderCharts()
}

async function cancelTask(taskId: number) {
  try {
    await trainApi.cancelTask(taskId)
    ElMessage.success('已取消')
    loadTasks()
  } catch {}
}

async function deleteTask(taskId: number) {
  try {
    await ElMessageBox.confirm('确定删除此训练任务？', '确认', { type: 'warning' })
    await trainApi.deleteTask(taskId)
    ElMessage.success('已删除')
    if (selectedTaskId.value === taskId) selectedTaskId.value = null
    loadTasks()
  } catch {}
}

// ====== ECharts ======
function makeChart(el: HTMLElement | undefined): echarts.ECharts | null {
  if (!el) return null
  let c = echarts.getInstanceByDom(el)
  if (!c) {
    c = echarts.init(el)
    charts.push(c)
  }
  return c
}

function renderCharts() {
  const ep = epochs.value
  const x = ep.map(e => e.epoch + 1)

  // Loss charts
  renderLossChart(chartBoxLoss.value, 'Box Loss', x,
    ep.map(e => e.train_box_loss), ep.map(e => e.val_box_loss))
  renderLossChart(chartSegLoss.value, 'Seg Loss', x,
    ep.map(e => e.train_seg_loss), ep.map(e => e.val_seg_loss))
  renderLossChart(chartClsLoss.value, 'Cls Loss', x,
    ep.map(e => e.train_cls_loss), ep.map(e => e.val_cls_loss))
  renderLossChart(chartDflLoss.value, 'DFL Loss', x,
    ep.map(e => e.train_dfl_loss), ep.map(e => e.val_dfl_loss))

  // Metric charts
  renderMetricChart(chartPrecision.value, 'Precision', x, ep.map(e => e.precision_b), '#409EFF')
  renderMetricChart(chartRecall.value, 'Recall', x, ep.map(e => e.recall_b), '#E6A23C')
  renderMetricChart(chartMap50.value, 'mAP@0.5 (Box)', x, ep.map(e => e.map50_b), '#67C23A')
  renderMetricChart(chartMap5095.value, 'mAP@0.5:0.95 (Box)', x, ep.map(e => e.map50_95_b), '#F56C6C')

  // LR chart
  renderMetricChart(chartLr.value, 'Learning Rate', x, ep.map(e => e.lr), '#909399')
}

function renderLossChart(el: HTMLElement | undefined, title: string, x: number[], train: (number|null)[], val: (number|null)[]) {
  const chart = makeChart(el)
  if (!chart) return
  chart.setOption({
    title: { text: title, left: 'center', top: 0, textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend: { data: ['Train', 'Val'], bottom: 0 },
    grid: { left: 50, right: 20, top: 40, bottom: 40 },
    xAxis: { type: 'category', data: x, name: 'Epoch' },
    yAxis: { type: 'value', name: 'Loss' },
    series: [
      { name: 'Train', type: 'line', data: train, smooth: true, lineStyle: { width: 2 }, itemStyle: { color: '#409EFF' }, symbol: 'none' },
      { name: 'Val', type: 'line', data: val, smooth: true, lineStyle: { width: 2, type: 'dashed' }, itemStyle: { color: '#F56C6C' }, symbol: 'none' },
    ],
  }, true)
}

function renderMetricChart(el: HTMLElement | undefined, title: string, x: number[], data: (number|null)[], color: string) {
  const chart = makeChart(el)
  if (!chart) return

  // 找最大值
  const valid = data.filter(v => v !== null && v !== 0) as number[]
  const maxVal = valid.length > 0 ? Math.max(...valid) : 0
  const maxIdx = data.indexOf(maxVal)

  chart.setOption({
    title: { text: title, left: 'center', top: 0, textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis', formatter: (p: any) => {
      const v = p[0]
      return `Epoch ${v.name}<br/>${v.seriesName}: <b>${v.value !== null ? Number(v.value).toFixed(5) : '-'}</b>`
    }},
    grid: { left: 60, right: 20, top: 40, bottom: 24 },
    xAxis: { type: 'category', data: x, name: 'Epoch' },
    yAxis: { type: 'value' },
    series: [{
      name: title, type: 'line', data, smooth: true,
      lineStyle: { width: 2, color },
      itemStyle: { color },
      symbol: 'none',
      areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
        { offset: 0, color: color + '33' },
        { offset: 1, color: color + '05' },
      ])},
      markPoint: maxVal > 0 ? {
        data: [{ type: 'max', name: 'Best' }],
        label: { formatter: (p: any) => Number(p.value).toFixed(4) },
        symbolSize: 40,
      } : undefined,
    }],
  }, true)
}

// Utils
function statusType(s: string) {
  return ({ pending: 'info', preparing: 'warning', training: '', completed: 'success', failed: 'danger', cancelled: 'info' } as any)[s] || 'info'
}
function statusText(s: string) {
  return ({ pending: '排队中', preparing: '准备数据', training: '训练中', completed: '已完成', failed: '失败', cancelled: '已取消' } as any)[s] || s
}
function duration(start: string, end: string) {
  const s = new Date(start).getTime(), e = new Date(end).getTime()
  const sec = Math.round((e - s) / 1000)
  if (sec < 60) return `${sec}秒`
  if (sec < 3600) return `${Math.floor(sec/60)}分${sec%60}秒`
  return `${Math.floor(sec/3600)}时${Math.floor((sec%3600)/60)}分`
}

// 窗口 resize 时重新调整图表大小
window.addEventListener('resize', () => { charts.forEach(c => c.resize()) })
</script>

<style scoped>
.charts-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.chart-box {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 8px;
}
pre {
  margin: 0;
  font-family: Consolas, monospace;
}
</style>
