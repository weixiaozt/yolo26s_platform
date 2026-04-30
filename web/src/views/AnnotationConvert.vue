<template>
  <div class="page-container">
    <div class="page-header">
      <div style="display:flex;align-items:center;gap:12px">
        <h1>标注转换</h1>
        <el-tag size="small" type="info">seg ⇆ det</el-tag>
      </div>
      <el-button @click="loadProjects" :loading="loading">
        <el-icon><Refresh /></el-icon> 刷新
      </el-button>
    </div>

    <el-alert type="info" :closable="false" style="margin-bottom:16px">
      <template #title>
        <b>标注数据共享，无需重新标注</b>
      </template>
      <div style="font-size:13px;line-height:1.7;margin-top:6px">
        平台所有标注统一以多边形（polygon）格式存储。<br>
        - <b>检测 → 分割</b>：检测的 4 点矩形框对分割训练同样合法（mask 是规整矩形），适合目标本身就是规整形状的场景（如光伏板）<br>
        - <b>分割 → 检测</b>：分割的多边形会自动转为外接矩形，损失边界信息但能更快训练
      </div>
    </el-alert>

    <!-- 第 1 步：选择源项目 -->
    <el-card shadow="never" style="margin-bottom:20px">
      <template #header>
        <div style="display:flex;align-items:center;justify-content:space-between">
          <span style="font-weight:600">第 1 步：选择源项目</span>
          <el-radio-group v-model="filterType" size="small">
            <el-radio-button label="all">全部</el-radio-button>
            <el-radio-button label="seg">仅分割</el-radio-button>
            <el-radio-button label="det">仅检测</el-radio-button>
          </el-radio-group>
        </div>
      </template>

      <el-table
        :data="filteredProjects"
        stripe
        size="default"
        v-loading="loading"
        @row-click="(row: any) => selectProject(row)"
        :row-class-name="rowClassName"
        empty-text="暂无项目"
      >
        <el-table-column width="50">
          <template #default="{row}">
            <el-radio v-model="selectedId" :label="row.id" @click.stop>
              <span></span>
            </el-radio>
          </template>
        </el-table-column>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="name" label="项目名称" min-width="200" />
        <el-table-column label="类型" width="100">
          <template #default="{row}">
            <el-tag :type="(row.task_type || 'seg') === 'det' ? 'warning' : 'success'" size="small">
              {{ (row.task_type || 'seg') === 'det' ? '检测' : '分割' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="类别数" width="80">
          <template #default="{row}">{{ row.defect_classes?.length || 0 }}</template>
        </el-table-column>
        <el-table-column label="尺寸" width="160">
          <template #default="{row}">
            <span style="font-size:12px;color:#606266">
              {{ row.resize_h }}×{{ row.resize_w }} → {{ row.crop_size }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="120">
          <template #default="{row}">
            <span style="font-size:12px;color:#909399">{{ formatDate(row.created_at) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 第 2 步：转换配置 -->
    <el-card shadow="never" v-if="selectedProject">
      <template #header>
        <span style="font-weight:600">第 2 步：转换配置</span>
      </template>

      <el-form label-width="120px">
        <el-form-item label="源项目">
          <el-tag size="large">
            #{{ selectedProject.id }} · {{ selectedProject.name }}
            <span style="margin:0 6px">|</span>
            {{ (selectedProject.task_type || 'seg') === 'det' ? '检测' : '分割' }}
          </el-tag>
        </el-form-item>

        <el-form-item label="目标类型">
          <el-radio-group v-model="targetType">
            <el-radio-button label="seg" :disabled="(selectedProject.task_type || 'seg') === 'seg'">
              分割（Seg）
            </el-radio-button>
            <el-radio-button label="det" :disabled="(selectedProject.task_type || 'seg') === 'det'">
              检测（Det）
            </el-radio-button>
          </el-radio-group>
          <div class="hint" style="margin-top:6px">
            源项目类型为 <b>{{ (selectedProject.task_type || 'seg') === 'det' ? '检测' : '分割' }}</b>，
            可转换为 <b>{{ (selectedProject.task_type || 'seg') === 'det' ? '分割' : '检测' }}</b>
          </div>
        </el-form-item>

        <el-form-item label="转换模式">
          <el-radio-group v-model="mode">
            <el-radio label="copy">复制为新项目（推荐，保留原项目）</el-radio>
            <el-radio label="inplace">原地修改（直接改原项目类型）</el-radio>
          </el-radio-group>
          <div class="hint" style="margin-top:6px">
            <span v-if="mode === 'copy'">
              安全：原项目保持不变，新建一个目标类型的项目（图片和标注全部复制）
            </span>
            <span v-else style="color:#E6A23C">
              ⚠ 直接修改原项目的 task_type，原项目的训练历史会保留但与新类型不兼容
            </span>
          </div>
        </el-form-item>

        <el-form-item label="新项目名称" v-if="mode === 'copy'">
          <el-input
            v-model="newName"
            :placeholder="`默认: ${selectedProject.name}_${targetType}`"
            style="max-width:400px"
          />
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            size="large"
            :loading="converting"
            @click="doConvert"
            :disabled="!canConvert"
          >
            <el-icon><MagicStick /></el-icon>
            <span style="margin-left:6px">开始转换</span>
          </el-button>
          <el-button @click="resetSelection">取消</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 转换结果 -->
    <el-dialog v-model="resultVisible" title="转换结果" width="500px">
      <el-result
        v-if="result"
        :icon="result.success ? 'success' : 'error'"
        :title="result.success ? '转换成功' : '转换失败'"
        :sub-title="result.success
          ? `${result.mode === 'copy' ? '已复制为新项目' : '已原地修改'}：#${result.target_project_id} · ${result.target_project_name}`
          : (result.error || '')"
      >
        <template #extra v-if="result.success">
          <div style="text-align:left;font-size:13px;color:#606266;margin-bottom:16px">
            <div>· 任务类型：<b>{{ result.task_type === 'det' ? '检测' : '分割' }}</b></div>
            <div>· 图片数量：<b>{{ result.image_count }}</b> 张</div>
            <div>· 标注数量：<b>{{ result.annotation_count }}</b> 个</div>
          </div>
          <el-button type="primary" @click="goToProject">进入新项目</el-button>
          <el-button @click="resultVisible = false; resetSelection(); loadProjects()">继续转换</el-button>
        </template>
      </el-result>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api/index'
import { projectApi, type Project } from '../api/project'

const router = useRouter()

const projects = ref<Project[]>([])
const loading = ref(false)
const filterType = ref<'all' | 'seg' | 'det'>('all')
const selectedId = ref<number | null>(null)
const targetType = ref<'seg' | 'det'>('seg')
const mode = ref<'copy' | 'inplace'>('copy')
const newName = ref('')
const converting = ref(false)
const resultVisible = ref(false)
const result = ref<any>(null)

const selectedProject = computed<Project | undefined>(() =>
  projects.value.find(p => p.id === selectedId.value)
)

const filteredProjects = computed(() => {
  if (filterType.value === 'all') return projects.value
  return projects.value.filter(p => (p.task_type || 'seg') === filterType.value)
})

const canConvert = computed(() => {
  if (!selectedProject.value) return false
  const srcType = selectedProject.value.task_type || 'seg'
  return srcType !== targetType.value
})

function rowClassName({ row }: any) {
  return row.id === selectedId.value ? 'selected-row' : ''
}

function selectProject(row: Project) {
  selectedId.value = row.id
  // 自动设置目标类型为相反类型
  const srcType = row.task_type || 'seg'
  targetType.value = srcType === 'det' ? 'seg' : 'det'
  newName.value = ''
}

function resetSelection() {
  selectedId.value = null
  newName.value = ''
}

async function loadProjects() {
  loading.value = true
  try {
    const { data } = await projectApi.list()
    projects.value = data
  } catch (e: any) {
    ElMessage.error('加载项目列表失败: ' + (e?.message || ''))
  } finally {
    loading.value = false
  }
}

async function doConvert() {
  if (!selectedProject.value) return
  const srcType = selectedProject.value.task_type || 'seg'
  if (srcType === targetType.value) {
    ElMessage.warning('源类型与目标类型相同')
    return
  }

  converting.value = true
  try {
    const fd = new FormData()
    fd.append('target_type', targetType.value)
    fd.append('mode', mode.value)
    if (mode.value === 'copy' && newName.value.trim()) {
      fd.append('new_name', newName.value.trim())
    }
    const { data } = await api.post(
      `/projects/${selectedProject.value.id}/convert-task-type`,
      fd,
      { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 600000 }
    )
    result.value = { ...data, success: true }
    resultVisible.value = true
  } catch (e: any) {
    result.value = {
      success: false,
      error: e?.response?.data?.detail || e?.message || '未知错误',
    }
    resultVisible.value = true
  } finally {
    converting.value = false
  }
}

function goToProject() {
  if (result.value?.target_project_id) {
    router.push(`/project/${result.value.target_project_id}`)
  }
}

function formatDate(s: string | null | undefined) {
  if (!s) return '-'
  return new Date(s).toLocaleDateString('zh-CN')
}

onMounted(loadProjects)
</script>

<style scoped>
.page-container {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.hint {
  font-size: 12px;
  color: #909399;
}
:deep(.selected-row) {
  background-color: #ecf5ff !important;
}
:deep(.el-table__row) {
  cursor: pointer;
}
</style>
