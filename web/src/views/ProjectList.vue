<template>
  <div class="page-container">
    <!-- 页头 -->
    <div class="page-header">
      <h1>项目管理</h1>
      <div class="btn-group">
        <el-button class="hbtn hbtn--blue" @click="showCreateDialog = true">
          <el-icon><Plus /></el-icon>
          新建项目
        </el-button>
        <el-button class="hbtn hbtn--green" @click="router.push('/import')">
          <el-icon><Upload /></el-icon>
          导入项目
        </el-button>
        <el-upload :auto-upload="false" :show-file-list="false" accept=".zip" :on-change="onFullPackageFileChange">
          <el-button class="hbtn hbtn--orange" :loading="importing">
            <el-icon><FolderOpened /></el-icon>
            导入项目包
          </el-button>
        </el-upload>
      </div>
    </div>

    <!-- 项目卡片列表（按任务类型分组：seg → cls → obb → det，组内按创建时间倒序）-->
    <div v-if="projects.length > 0">
      <template v-for="g in groupedProjects" :key="g.type">
        <div class="group-header">
          <span class="group-title">{{ g.label }}</span>
          <span class="group-count">{{ g.items.length }} 个</span>
        </div>
        <div class="project-grid">
          <el-card
            v-for="p in g.items"
            :key="p.id"
            class="project-card"
            shadow="hover"
            @click="router.push(`/project/${p.id}`)"
          >
            <template #header>
              <div class="card-header">
                <span class="project-name">{{ p.name }}</span>
                <el-tag :type="p.status === 'active' ? 'success' : 'info'" size="small">
                  {{ p.status === 'active' ? '活跃' : '归档' }}
                </el-tag>
              </div>
            </template>
            <p class="project-desc">{{ p.description || '暂无描述' }}</p>
            <div class="project-meta">
              <el-tag :type="taskTypeTag(p.task_type)" size="small" effect="plain">
                {{ taskTypeLabel(p.task_type) }}
              </el-tag>
              <span>
                <el-icon><Picture /></el-icon>
                {{ p.resize_h }}×{{ p.resize_w }} → {{ p.crop_size }}
              </span>
              <span>
                <el-icon><Collection /></el-icon>
                {{ p.defect_classes.length }} 个类别
              </span>
            </div>
            <div class="project-classes">
              <el-tag
                v-for="dc in p.defect_classes"
                :key="dc.class_index"
                :color="dc.color"
                effect="dark"
                size="small"
                style="margin-right: 4px; margin-bottom: 4px; border: none;"
              >
                {{ dc.name }}
              </el-tag>
            </div>
            <div class="project-footer">
              <span class="project-time">创建于 {{ formatDate(p.created_at) }}</span>
              <div class="card-actions">
                <el-button
                  class="card-action card-action--blue"
                  size="small"
                  round
                  :loading="exportingKey === `full:${p.id}`"
                  @click.stop="handleExportFullProject(p)"
                >
                  导出项目
                </el-button>
                <el-button
                  class="card-action card-action--sky"
                  size="small"
                  round
                  :loading="exportingKey === `anno:${p.id}`"
                  @click.stop="handleExportAnnotations(p)"
                >
                  导出标注
                </el-button>
                <el-button
                  v-if="isAdmin"
                  class="card-action card-action--red"
                  size="small"
                  round
                  @click.stop="handleDeleteProject(p.id, p.name)"
                >
                  删除项目
                </el-button>
              </div>
              <el-progress
                v-if="exportingKey === `full:${p.id}` || exportingKey === `anno:${p.id}`"
                class="export-progress"
                :percentage="exportProgress"
                :stroke-width="6"
                :show-text="false"
              />
            </div>
          </el-card>
        </div>
      </template>
    </div>

    <!-- 空状态 -->
    <el-empty v-else description="还没有项目，点击上方按钮创建" />

    <!-- 新建项目对话框 -->
    <el-dialog v-model="showCreateDialog" title="新建项目" width="560px" @close="resetForm">
      <el-form :model="form" label-width="100px" label-position="left">
        <el-form-item label="项目名称" required>
          <el-input v-model="form.name" placeholder="如：硅片裂纹检测-批次A" />
        </el-form-item>
        <el-form-item label="任务类型" required>
          <el-radio-group v-model="form.task_type" class="radio-cards">
            <el-radio-button label="seg">实例分割（Seg）</el-radio-button>
            <el-radio-button label="det">目标检测（Det）</el-radio-button>
            <el-radio-button label="obb">旋转检测（OBB）</el-radio-button>
            <el-radio-button label="cls">图像分类（Cls）</el-radio-button>
          </el-radio-group>
          <div class="hint" style="margin-top:4px">
            <span v-if="form.task_type === 'seg'">分割：标注多边形区域，输出像素级 Mask</span>
            <span v-else-if="form.task_type === 'det'">检测：标注矩形框，仅输出水平 bbox（适合小图、规整目标）</span>
            <span v-else-if="form.task_type === 'obb'">旋转检测：标注多边形（≥4 点），输出旋转矩形（适合航拍/遥感/有方向的密集目标）</span>
            <span v-else>分类：图级标签（每张图一个类别），适合小图缺陷分类</span>
          </div>
        </el-form-item>
        <el-form-item label="项目描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>

        <el-divider content-position="left">预处理参数</el-divider>
        <el-row :gutter="16" v-if="form.task_type === 'seg'">
          <el-col :span="12">
            <el-form-item label="Resize 高度">
              <el-input-number v-model="form.resize_h" :min="640" :max="8192" :step="64" style="width:100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="Resize 宽度">
              <el-input-number v-model="form.resize_w" :min="640" :max="8192" :step="64" style="width:100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16" v-if="form.task_type !== 'cls'">
          <el-col :span="12">
            <el-form-item :label="cropSizeLabel">
              <el-input-number
                v-model="form.crop_size"
                :min="320"
                :max="8192" :step="32" style="width:100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12" v-if="form.task_type === 'seg'">
            <el-form-item label="重叠率">
              <el-input-number v-model="form.overlap" :min="0" :max="0.5" :step="0.05" :precision="2" style="width:100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-alert v-else type="info" :closable="false" show-icon
          title="分类项目无需 Resize/切割尺寸"
          description="分类训练统一使用 ImageNet 标准 imgsz=224，原图直接 letterbox 到 224×224，不切大图。"
          style="margin-bottom:18px" />

        <el-divider content-position="left">缺陷类别</el-divider>
        <div class="class-list">
          <div v-for="(cls, idx) in form.class_names" :key="idx" class="class-row">
            <el-input v-model="cls.name" placeholder="类别名" class="class-name-input" />
            <el-color-picker v-model="cls.color" />
            <el-button
              v-if="form.class_names.length > 1"
              class="hbtn hbtn--red class-del" size="small" title="删除该类别"
              @click="form.class_names.splice(idx, 1)"
            >
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
        </div>
        <el-button class="hbtn hbtn--blue" size="small" @click="addClass" style="margin-top: 2px">
          <el-icon><Plus /></el-icon> 添加类别
        </el-button>
      </el-form>

      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button class="hbtn hbtn--blue" :loading="creating" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { projectApi, type Project, type ProjectCreate, type DefectClass } from '../api/project'

function taskTypeLabel(t: string | undefined) {
  return ({ seg: '实例分割', det: '目标检测', cls: '图像分类', obb: '旋转检测' } as any)[t || 'seg'] || '实例分割'
}
function taskTypeTag(t: string | undefined) {
  return ({ seg: 'success', det: 'warning', cls: 'primary', obb: 'danger' } as any)[t || 'seg'] || 'success'
}

// 项目分组顺序：seg → cls → obb → det，组内按 created_at 倒序
const GROUP_ORDER: Array<{ type: string; label: string }> = [
  { type: 'seg', label: '实例分割' },
  { type: 'cls', label: '图像分类' },
  { type: 'obb', label: '旋转检测' },
  { type: 'det', label: '目标检测' },
]

const router = useRouter()
const projects = ref<Project[]>([])
const showCreateDialog = ref(false)
const creating = ref(false)
const exportingKey = ref<string | null>(null)
const exportProgress = ref(0)
const importing = ref(false)
const isAdmin = computed(() => {
  try {
    return JSON.parse(localStorage.getItem('user') || '{}')?.role === 'admin'
  } catch {
    return false
  }
})

const groupedProjects = computed(() => {
  return GROUP_ORDER
    .map(g => ({
      ...g,
      items: projects.value
        .filter(p => (p.task_type || 'seg') === g.type)
        .sort((a, b) => (b.created_at || '').localeCompare(a.created_at || '')),
    }))
    .filter(g => g.items.length > 0)
})

const defaultColors = ['#FF4444', '#44BB44', '#4488FF', '#FFAA00', '#FF44FF', '#44FFFF']

const form = ref<ProjectCreate & { class_names: DefectClass[] }>({
  name: '',
  description: '',
  task_type: 'seg',
  resize_h: 4096,
  resize_w: 4096,
  crop_size: 640,
  overlap: 0.2,
  class_names: [
    { class_index: 0, name: 'defect_1', color: '#FF4444' },
    { class_index: 1, name: 'defect_2', color: '#44BB44' },
    { class_index: 2, name: 'defect_3', color: '#4488FF' },
  ],
})

const cropSizeLabel = computed(() => {
  const t = form.value.task_type
  if (t === 'cls') return '训练图尺寸'
  if (t === 'det') return '训练图尺寸'
  if (t === 'obb') return '训练图尺寸'
  return '切割尺寸'
})

function addClass() {
  const idx = form.value.class_names!.length
  form.value.class_names!.push({
    class_index: idx,
    name: `defect_${idx + 1}`,
    color: defaultColors[idx % defaultColors.length],
  })
}

function resetForm() {
  form.value = {
    name: '', description: '', task_type: 'seg',
    resize_h: 4096, resize_w: 4096, crop_size: 640, overlap: 0.2,
    class_names: [
      { class_index: 0, name: 'defect_1', color: '#FF4444' },
      { class_index: 1, name: 'defect_2', color: '#44BB44' },
      { class_index: 2, name: 'defect_3', color: '#4488FF' },
    ],
  }
}

function downloadBlob(data: any, filename: string) {
  const blob = new Blob([data], { type: 'application/zip' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

async function handleExportAnnotations(p: Project) {
  const key = `anno:${p.id}`
  exportingKey.value = key
  exportProgress.value = 0
  try {
    const resp = await projectApi.exportPackage(p.id, percent => {
      if (exportingKey.value === key) exportProgress.value = percent
    })
    exportProgress.value = 100
    downloadBlob(resp.data as any, `${p.name}_annotations.zip`)
    ElMessage.success('标注包导出完成')
  } catch (e: any) {
    ElMessage.error('导出标注失败: ' + (e?.message || '未知错误'))
  } finally {
    window.setTimeout(() => {
      if (exportingKey.value === key) {
        exportingKey.value = null
        exportProgress.value = 0
      }
    }, 450)
  }
}

async function handleExportFullProject(p: Project) {
  const key = `full:${p.id}`
  exportingKey.value = key
  exportProgress.value = 0
  try {
    const resp = await projectApi.exportFullPackage(p.id, percent => {
      if (exportingKey.value === key) exportProgress.value = percent
    })
    exportProgress.value = 100
    downloadBlob(resp.data as any, `${p.name}_full_project.zip`)
    ElMessage.success('完整项目包导出完成')
  } catch (e: any) {
    if (e?.response?.status === 404) {
      ElMessage.error('导出项目接口 404：后端还没加载新接口，请重启 uvicorn 后再试')
    } else {
      ElMessage.error('导出项目失败: ' + (e?.response?.data?.detail || e?.message || '未知错误'))
    }
  } finally {
    window.setTimeout(() => {
      if (exportingKey.value === key) {
        exportingKey.value = null
        exportProgress.value = 0
      }
    }, 450)
  }
}

async function onFullPackageFileChange(f: any) {
  const file: File = f.raw
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.zip')) {
    ElMessage.warning('请选择 ZIP 文件')
    return
  }
  const lowerName = file.name.toLowerCase()
  if (lowerName.includes('_annotations') || lowerName.includes('annotations.zip')) {
    ElMessage.warning('这是标注包，请进入目标项目详情页，使用“合并标注包”导入')
    return
  }
  try {
    await ElMessageBox.confirm(
      `即将导入完整项目包「${file.name}」(${(file.size / 1024 / 1024).toFixed(1)} MB)，会恢复全部图片、标注、训练任务和权重，是否继续？`,
      '导入确认',
      { confirmButtonText: '确定导入', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  importing.value = true
  try {
    const { data } = await projectApi.importFullPackage(file)
    const msg = data.renamed
      ? `导入成功：项目已重命名为「${data.project_name}」，${data.image_count} 张图片 / ${data.annotation_count} 个标注 / ${data.train_task_count} 个训练任务`
      : `导入成功：${data.image_count} 张图片 / ${data.annotation_count} 个标注 / ${data.train_task_count} 个训练任务`
    ElMessage.success(msg)
    loadProjects()
  } catch (e: any) {
    ElMessage.error('导入失败: ' + (e?.response?.data?.detail || e?.message || '未知错误'))
  } finally {
    importing.value = false
  }
}

async function handleDeleteProject(id: number, name: string) {
  try {
    await ElMessageBox.confirm(`确定删除项目「${name}」？所有图像和标注将被永久删除。`, '删除确认', {
      confirmButtonText: '确定删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await projectApi.delete(id)
    ElMessage.success('已删除')
    loadProjects()
  } catch {}
}

async function loadProjects() {
  const { data } = await projectApi.list()
  projects.value = data
}

async function handleCreate() {
  if (!form.value.name.trim()) {
    ElMessage.warning('请输入项目名称')
    return
  }
  creating.value = true
  try {
    await projectApi.create(form.value)
    ElMessage.success('项目创建成功')
    showCreateDialog.value = false
    loadProjects()
  } catch (e: any) {
    // FastAPI 错误：detail 可能是字符串，也可能是 pydantic 验证错误数组
    let msg = '创建失败'
    const d = e?.response?.data?.detail
    if (typeof d === 'string') {
      msg = d
    } else if (Array.isArray(d) && d.length) {
      msg = d.map((it: any) => `${(it.loc || []).join('.')}: ${it.msg}`).join('；')
    } else if (e?.message) {
      msg = e.message
    }
    // 错误信息显示长一点 + 手动关闭，避免 422 文本一闪而过看不清
    ElMessage({
      type: 'error',
      message: `项目创建失败：${msg}`,
      duration: 0,        // 0 = 不自动关闭
      showClose: true,
    })
    console.error('[handleCreate]', e?.response?.status, e?.response?.data, e)
  } finally {
    creating.value = false
  }
}

function formatDate(s: string) {
  return new Date(s).toLocaleDateString('zh-CN')
}

onMounted(loadProjects)
</script>

<style scoped>
.group-header {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin: 18px 0 10px;
  padding-left: 4px;
  border-left: 4px solid #409EFF;
  padding-left: 12px;
}
.group-header:first-child { margin-top: 0; }
.group-title { font-size: 16px; font-weight: 600; color: #303133; }
.group-count { font-size: 12px; color: #909399; }

.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 390px));
  gap: 22px 26px;
  margin-bottom: 28px;
}
.project-card {
  cursor: pointer;
  transition: transform 0.2s;
  min-height: 255px;
}
.project-card:hover {
  transform: translateY(-3px);
}
:deep(.project-card .el-card__body) {
  display: flex;
  flex-direction: column;
  min-height: 170px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.project-name {
  font-size: 16px;
  font-weight: 600;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.project-desc {
  color: #909399;
  font-size: 13px;
  margin-bottom: 12px;
  min-height: 38px;
  line-height: 1.45;
}
.project-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px 22px;
  font-size: 13px;
  color: #606266;
  margin-bottom: 10px;
}
.project-meta span {
  display: flex;
  align-items: center;
  gap: 4px;
}
.project-classes {
  margin-bottom: 10px;
  min-height: 26px;
}
.project-footer {
  display: grid;
  grid-template-columns: 1fr;
  align-items: stretch;
  gap: 8px;
  margin-top: auto;
  padding-top: 8px;
}
.project-time {
  font-size: 12px;
  color: #c0c4cc;
  width: 100%;
  overflow: visible;
  text-overflow: clip;
  white-space: nowrap;
}
.card-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
}
.card-actions .el-button + .el-button {
  margin-left: 0;
}
.card-action {
  min-width: 72px;
  height: 28px;
  padding: 0 12px;
  border: 1px solid transparent;
  font-weight: 600;
}
.card-action--blue {
  color: #2563eb;
  background: #eff6ff;
  border-color: #bfdbfe;
}
.card-action--sky {
  color: #0284c7;
  background: #f0f9ff;
  border-color: #bae6fd;
}
.card-action--red {
  color: #ef4444;
  background: #fff1f2;
  border-color: #fecdd3;
}
.card-action--blue:hover,
.card-action--blue:focus {
  color: #fff;
  background: #3b82f6;
  border-color: #3b82f6;
}
.card-action--sky:hover,
.card-action--sky:focus {
  color: #fff;
  background: #0ea5e9;
  border-color: #0ea5e9;
}
.card-action--red:hover,
.card-action--red:focus {
  color: #fff;
  background: #ef4444;
  border-color: #ef4444;
}
.export-progress {
  width: 100%;
  margin-top: 2px;
}
@media (max-width: 720px) {
  .project-grid {
    grid-template-columns: 1fr;
  }
  .project-footer {
    grid-template-columns: 1fr;
  }
  .card-actions {
    justify-content: flex-start;
    max-width: none;
  }
}
.class-list {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px 12px;
  margin-bottom: 10px;
}
.class-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 10px;
  background: #f6f8fb;
  border: 1px solid #eceff5;
  border-radius: 8px;
}
.class-name-input { flex: 1; }
.class-del { padding: 0 10px; }
.hint { font-size: 12px; color: #909399; }
</style>
