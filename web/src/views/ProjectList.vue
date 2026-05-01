<template>
  <div class="page-container">
    <!-- 页头 -->
    <div class="page-header">
      <h1>项目管理</h1>
      <div style="display:flex;gap:10px">
        <el-button type="primary" @click="showCreateDialog = true">
          <el-icon><Plus /></el-icon>
          新建项目
        </el-button>
        <el-button @click="router.push('/import')">
          <el-icon><Upload /></el-icon>
          导入项目
        </el-button>
        <el-upload :auto-upload="false" :show-file-list="false" accept=".zip" :on-change="onPackageFileChange">
          <el-button :loading="importing">
            <el-icon><FolderOpened /></el-icon>
            导入项目包
          </el-button>
        </el-upload>
      </div>
    </div>

    <!-- 项目卡片列表 -->
    <div v-if="projects.length > 0" class="project-grid">
      <el-card
        v-for="p in projects"
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
        <div class="project-time">
          创建于 {{ formatDate(p.created_at) }}
          <el-button
            type="danger" text size="small"
            style="float: right"
            @click.stop="handleDeleteProject(p.id, p.name)"
          >
            删除项目
          </el-button>
          <el-button
            type="primary" text size="small"
            style="float: right; margin-right: 8px"
            :loading="exportingId === p.id"
            @click.stop="handleExport(p)"
          >
            导出
          </el-button>
        </div>
      </el-card>
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
          <el-radio-group v-model="form.task_type">
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
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item :label="cropSizeLabel">
              <el-input-number
                v-model="form.crop_size"
                :min="form.task_type === 'cls' ? 32 : 320"
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

        <el-divider content-position="left">缺陷类别</el-divider>
        <div v-for="(cls, idx) in form.class_names" :key="idx" class="class-row">
          <el-input v-model="cls.name" placeholder="类别名" style="width: 160px" />
          <el-color-picker v-model="cls.color" size="small" />
          <el-button
            v-if="form.class_names.length > 1"
            type="danger" text size="small"
            @click="form.class_names.splice(idx, 1)"
          >
            删除
          </el-button>
        </div>
        <el-button type="primary" text @click="addClass" style="margin-top: 8px">
          + 添加类别
        </el-button>
      </el-form>

      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="handleCreate">创建</el-button>
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

const router = useRouter()
const projects = ref<Project[]>([])
const showCreateDialog = ref(false)
const creating = ref(false)
const exportingId = ref<number | null>(null)
const importing = ref(false)

const defaultColors = ['#FF4444', '#44BB44', '#4488FF', '#FFAA00', '#FF44FF', '#44FFFF']

const form = ref<ProjectCreate>({
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

async function handleExport(p: Project) {
  exportingId.value = p.id
  try {
    const resp = await projectApi.exportPackage(p.id)
    const blob = new Blob([resp.data as any], { type: 'application/zip' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${p.name}_export.zip`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    ElMessage.success('导出完成')
  } catch (e: any) {
    ElMessage.error('导出失败: ' + (e?.message || '未知错误'))
  } finally {
    exportingId.value = null
  }
}

async function onPackageFileChange(f: any) {
  const file: File = f.raw
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.zip')) {
    ElMessage.warning('请选择 ZIP 文件')
    return
  }
  try {
    await ElMessageBox.confirm(
      `即将导入项目包「${file.name}」(${(file.size / 1024 / 1024).toFixed(1)} MB)，是否继续？`,
      '导入确认',
      { confirmButtonText: '确定导入', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  importing.value = true
  try {
    const { data } = await projectApi.importPackage(file)
    const msg = data.renamed
      ? `导入成功：项目已重命名为「${data.project_name}」，${data.image_count} 张图片 / ${data.annotation_count} 个标注`
      : `导入成功：${data.image_count} 张图片 / ${data.annotation_count} 个标注`
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
.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
}
.project-card {
  cursor: pointer;
  transition: transform 0.2s;
}
.project-card:hover {
  transform: translateY(-3px);
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.project-name {
  font-size: 16px;
  font-weight: 600;
}
.project-desc {
  color: #909399;
  font-size: 13px;
  margin-bottom: 12px;
  min-height: 20px;
}
.project-meta {
  display: flex;
  gap: 20px;
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
}
.project-time {
  font-size: 12px;
  color: #c0c4cc;
}
.class-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.hint { font-size: 12px; color: #909399; }
</style>
