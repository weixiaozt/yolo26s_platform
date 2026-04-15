<template>
  <div class="page-container" style="max-width:1200px">
    <div class="page-header">
      <div style="display:flex;align-items:center;gap:12px">
        <el-button text @click="router.push(`/project/${id}`)"><el-icon><ArrowLeft /></el-icon> 返回</el-button>
        <h1>模型转换</h1>
      </div>
    </div>

    <!-- 新建导出 -->
    <el-card shadow="never" style="margin-bottom:24px">
      <template #header><span style="font-weight:600">转换模型</span></template>
      <el-form label-width="120px" label-position="left" style="max-width:600px">
        <el-form-item label="训练任务">
          <el-select v-model="selTaskId" placeholder="选择训练任务" style="width:100%" @change="onTaskChange">
            <el-option v-for="t in tasks" :key="t.task_id" :label="t.task_name" :value="t.task_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="模型权重">
          <el-radio-group v-model="sourceType">
            <el-radio label="best">best.pt（最佳）</el-radio>
            <el-radio label="last">last.pt（最终）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="导出格式">
          <el-radio-group v-model="exportFormat" size="default">
            <el-radio-button label="onnx">
              <div style="text-align:center;line-height:1.4">
                <div style="font-weight:600">ONNX</div>
                <div style="font-size:11px;color:#909399">通用格式·跨平台</div>
              </div>
            </el-radio-button>
            <el-radio-button label="openvino">
              <div style="text-align:center;line-height:1.4">
                <div style="font-weight:600">OpenVINO</div>
                <div style="font-size:11px;color:#909399">Intel CPU/核显加速</div>
              </div>
            </el-radio-button>
            <el-radio-button label="tensorrt">
              <div style="text-align:center;line-height:1.4">
                <div style="font-weight:600">TensorRT</div>
                <div style="font-size:11px;color:#909399">NVIDIA GPU 极速</div>
              </div>
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="输入尺寸">
          <el-input-number v-model="imgsz" :min="320" :max="1280" :step="32" />
          <span style="font-size:12px;color:#909399;margin-left:8px">与训练时一致（通常 640）</span>
        </el-form-item>
        <el-form-item label="精度">
          <el-radio-group v-model="precision">
            <el-radio label="fp32">FP32（默认）</el-radio>
            <el-radio label="fp16">FP16（模型减半，GPU 推理更快）</el-radio>
            <el-radio label="int8" :disabled="exportFormat !== 'openvino'">
              INT8（CPU 最快，仅 OpenVINO，需 nncf）
            </el-radio>
          </el-radio-group>
        </el-form-item>
        <el-alert v-if="precision==='int8'" type="warning" :closable="false" style="margin-bottom:12px">
          <div style="font-size:12px">
            INT8 量化需要校准数据集，会自动使用训练时的 dataset 目录。<br>
            需安装 nncf: <code>pip install nncf</code>，导出时间较长（2~5 分钟）。
          </div>
        </el-alert>
        <el-form-item>
          <el-button type="primary" :loading="exporting" @click="startExport" :disabled="!selTaskId">
            <el-icon><Upload /></el-icon> 开始转换
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 原始模型下载 -->
    <el-card shadow="never" style="margin-bottom:24px">
      <template #header><span style="font-weight:600">原始模型 (.pt)</span></template>
      <el-table :data="ptModels" stripe style="width:100%" empty-text="暂无训练模型">
        <el-table-column label="训练任务" min-width="180">
          <template #default="{row}">{{ row.task_name }}</template>
        </el-table-column>
        <el-table-column label="模型" width="100">
          <template #default="{row}"><el-tag size="small">{{ row.type }}.pt</el-tag></template>
        </el-table-column>
        <el-table-column label="路径" min-width="250">
          <template #default="{row}"><span style="font-size:11px;color:#606266;word-break:break-all">{{ row.path }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{row}">
            <a :href="`/api/export/download/pt/${row.task_id}/${row.type}`" target="_blank" style="color:#409EFF;font-size:13px;text-decoration:none">下载</a>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 导出记录 -->
    <el-card shadow="never">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span style="font-weight:600">转换记录</span>
          <el-button text size="small" @click="loadExports"><el-icon><Refresh /></el-icon> 刷新</el-button>
        </div>
      </template>
      <el-table :data="exports" stripe style="width:100%" empty-text="暂无转换记录">
        <el-table-column prop="id" label="ID" width="55" />
        <el-table-column label="来源" width="140">
          <template #default="{row}">
            任务 {{ row.task_id }} / {{ row.source_type }}.pt
          </template>
        </el-table-column>
        <el-table-column label="格式" width="110">
          <template #default="{row}">
            <el-tag :type="fmtTagType(row.export_format)" size="small">{{ row.export_format.toUpperCase() }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{row}">
            <el-tag :type="statusType(row.status)" size="small">
              <el-icon v-if="row.status==='exporting'" class="is-loading"><Loading /></el-icon>
              {{ statusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="90">
          <template #default="{row}">
            {{ row.file_size_mb ? row.file_size_mb.toFixed(1) + ' MB' : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="尺寸" width="70">
          <template #default="{row}">{{ row.imgsz }}</template>
        </el-table-column>
        <el-table-column label="精度" width="70">
          <template #default="{row}">{{ row.precision || 'FP32' }}</template>
        </el-table-column>
        <el-table-column label="导出路径" min-width="200">
          <template #default="{row}">
            <span v-if="row.export_path" style="font-size:11px;color:#606266;word-break:break-all">{{ row.export_path }}</span>
            <span v-else-if="row.error_message" style="font-size:11px;color:#F56C6C">{{ row.error_message }}</span>
            <span v-else style="color:#aaa">-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{row}">
            <a v-if="row.status==='completed'" :href="`/api/export/download/exported/${row.id}`" target="_blank" style="color:#409EFF;font-size:13px;text-decoration:none;margin-right:12px">下载</a>
            <el-button v-if="row.status!=='exporting'" type="danger" text size="small" @click="deleteExport(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 说明 -->
    <el-alert type="info" :closable="false" style="margin-top:20px">
      <template #title>格式说明</template>
      <div style="font-size:13px;line-height:1.8">
        <b>ONNX</b>：通用中间格式，可在任意平台运行，适合跨环境部署<br>
        <b>OpenVINO</b>：Intel 优化格式，在 Intel CPU 和核显上推理速度比 PyTorch 快 2~5 倍，需安装 openvino<br>
        <b>TensorRT</b>：NVIDIA 极致优化，推理最快，但需要 GPU 环境和 tensorrt 库，且绑定 GPU 型号
      </div>
    </el-alert>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api/index'

const props = defineProps<{ id: string }>()
const router = useRouter()

interface TaskInfo { task_id:number; task_name:string; models:{type:string;path:string}[] }
interface ExportInfo { id:number; task_id:number; source_type:string; export_format:string; export_path:string|null; file_size_mb:number; imgsz:number; half:boolean; status:string; error_message:string|null; created_at:string|null }

const tasks = ref<TaskInfo[]>([])
const exports = ref<ExportInfo[]>([])
const selTaskId = ref<number|null>(null)
const sourceType = ref('best')
const exportFormat = ref('onnx')
const imgsz = ref(640)
const precision = ref('fp32')
const exporting = ref(false)
let pollTimer: any = null

// 展平 tasks 的 models 列表，用于原始模型表格
const ptModels = computed(() => {
  const list: {task_id:number; task_name:string; type:string; path:string}[] = []
  for (const t of tasks.value) {
    for (const m of t.models) {
      list.push({ task_id: t.task_id, task_name: t.task_name, type: m.type, path: m.path })
    }
  }
  return list
})

onMounted(async () => {
  await loadTasks()
  await loadExports()
})

async function loadTasks() {
  const { data } = await api.get('/export/tasks', { params: { project_id: props.id } })
  tasks.value = data
  if (data.length > 0 && !selTaskId.value) selTaskId.value = data[0].task_id
}

async function loadExports() {
  const { data } = await api.get('/export/list', { params: { project_id: props.id } })
  exports.value = data
  // 如果有正在导出的，开启轮询
  const hasExporting = data.some((e: ExportInfo) => e.status === 'exporting')
  if (hasExporting && !pollTimer) {
    pollTimer = setInterval(async () => {
      await loadExports()
      if (!exports.value.some(e => e.status === 'exporting')) {
        clearInterval(pollTimer); pollTimer = null
      }
    }, 3000)
  }
}

function onTaskChange() { sourceType.value = 'best' }

async function startExport() {
  if (!selTaskId.value) return
  exporting.value = true
  try {
    await api.post('/export/run', {
      task_id: selTaskId.value,
      source_type: sourceType.value,
      export_format: exportFormat.value,
      imgsz: imgsz.value,
      half: precision.value === 'fp16',
      int8: precision.value === 'int8',
    })
    ElMessage.success('转换任务已启动！')
    await loadExports()
  } catch {} finally { exporting.value = false }
}

async function deleteExport(id: number) {
  await api.delete(`/export/${id}`)
  exports.value = exports.value.filter(e => e.id !== id)
}

function fmtTagType(fmt: string) { return ({ onnx:'', openvino:'success', tensorrt:'warning' } as any)[fmt] || 'info' }
function statusType(s: string) { return ({ exporting:'warning', completed:'success', failed:'danger' } as any)[s] || 'info' }
function statusText(s: string) { return ({ exporting:'转换中', completed:'完成', failed:'失败' } as any)[s] || s }

function downloadPt(taskId: number, modelType: string) {
  window.open(`/api/export/download/pt/${taskId}/${modelType}`, '_blank')
}
function downloadExported(exportId: number) {
  window.open(`/api/export/download/exported/${exportId}`, '_blank')
}
</script>
