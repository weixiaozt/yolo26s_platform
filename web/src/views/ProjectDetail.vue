<template>
  <div class="page-container">
    <!-- 页头 -->
    <div class="page-header">
      <div class="header-left">
        <el-button text @click="router.push('/')">
          <el-icon><ArrowLeft /></el-icon>
          返回
        </el-button>
        <h1>{{ project?.name }}</h1>
        <el-button text type="primary" @click="openEditDialog" style="font-size:13px">编辑项目</el-button>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="showUpload = true">
          <el-icon><Upload /></el-icon>
          上传图像
        </el-button>
        <el-button
          type="success"
          :disabled="!project || project.labeled_count + project.reviewed_count === 0"
          @click="router.push(`/project/${id}/train`)"
        >
          <el-icon><VideoPlay /></el-icon>
          训练模型
        </el-button>
        <el-button
          @click="router.push(`/project/${id}/train/monitor`)"
        >
          训练监控
        </el-button>
        <el-button
          type="warning"
          @click="router.push(`/project/${id}/inference`)"
        >
          在线推断
        </el-button>
        <el-button
          @click="router.push(`/project/${id}/export`)"
        >
          模型转换
        </el-button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div v-if="project" class="stat-cards">
      <el-card class="stat-card" shadow="never">
        <div class="stat-number">{{ project.total_images }}</div>
        <div class="stat-label">总图像数</div>
      </el-card>
      <el-card class="stat-card" shadow="never" @click="filterStatus = 'unlabeled'">
        <div class="stat-number" style="color: #909399">{{ project.unlabeled_count }}</div>
        <div class="stat-label">未标注</div>
      </el-card>
      <el-card class="stat-card" shadow="never" @click="filterStatus = 'labeled'">
        <div class="stat-number" style="color: #E6A23C">{{ project.labeled_count }}</div>
        <div class="stat-label">有缺陷标注</div>
      </el-card>
      <el-card class="stat-card" shadow="never" @click="filterStatus = 'reviewed'">
        <div class="stat-number" style="color: #67C23A">{{ project.reviewed_count }}</div>
        <div class="stat-label">OK(负样本)</div>
      </el-card>
      <el-card class="stat-card" shadow="never">
        <div class="stat-number" style="color: #409EFF">{{ project.labeled_count + project.reviewed_count }}</div>
        <div class="stat-label">已完成</div>
      </el-card>
      <el-card class="stat-card" shadow="never">
        <div class="stat-number" style="color: #F56C6C">{{ project.total_annotations }}</div>
        <div class="stat-label">缺陷多边形数</div>
      </el-card>
    </div>

    <!-- 工具栏 -->
    <div class="toolbar">
      <el-radio-group v-model="filterStatus" @change="loadImages(1)">
        <el-radio-button label="">全部</el-radio-button>
        <el-radio-button label="unlabeled">未标注</el-radio-button>
        <el-radio-button label="labeling">标注中</el-radio-button>
        <el-radio-button label="labeled">有缺陷</el-radio-button>
        <el-radio-button label="reviewed">OK</el-radio-button>
      </el-radio-group>
      <span class="total-hint">共 {{ imageTotal }} 张</span>
    </div>

    <!-- 图像网格 -->
    <div v-if="images.length > 0" class="image-grid">
      <el-card
        v-for="img in images"
        :key="img.id"
        class="image-card"
        shadow="hover"
        :body-style="{ padding: 0 }"
        @click="goAnnotate(img.id)"
      >
        <img
          :src="getThumbUrl(img.id)"
          class="thumb"
          loading="lazy"
          :alt="img.filename"
        />
        <div class="info">
          <div class="filename">{{ img.filename }}</div>
          <div class="meta-row">
            <el-tag
              :type="statusTagType(img.status)"
              size="small"
              effect="plain"
            >
              {{ statusLabel(img.status) }}
            </el-tag>
            <span v-if="img.annotation_count > 0" class="ann-count">
              {{ img.annotation_count }} 个标注
            </span>
            <el-button
              type="danger" text size="small"
              @click.stop="handleDeleteImage(img.id, img.filename)"
              style="margin-left: auto;"
            >
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
        </div>
      </el-card>
    </div>
    <el-empty v-else-if="!loading" description="暂无图像，点击上方上传" />

    <!-- 分页 -->
    <div v-if="imageTotal > pageSize" class="pagination">
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="imageTotal"
        layout="prev, pager, next"
        @current-change="loadImages"
      />
    </div>

    <!-- 上传对话框 -->
    <el-dialog v-model="showUpload" title="上传图像" width="500px">
      <el-upload
        ref="uploadRef"
        drag
        multiple
        :auto-upload="false"
        :file-list="uploadFileList"
        :on-change="onFileChange"
        :on-remove="onFileRemove"
        accept=".bmp,.png,.jpg,.jpeg,.tif,.tiff"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">
          拖拽文件到这里，或<em>点击选择</em>
        </div>
        <template #tip>
          <div class="el-upload__tip">支持 BMP / PNG / JPG / TIFF 格式</div>
        </template>
      </el-upload>

      <template #footer>
        <el-button @click="showUpload = false">取消</el-button>
        <el-button
          type="primary"
          :loading="uploading"
          :disabled="uploadFiles.length === 0"
          @click="handleUpload"
        >
          上传 {{ uploadFiles.length }} 个文件
          <span v-if="uploadProgress > 0">({{ uploadProgress }}%)</span>
        </el-button>
      </template>
    </el-dialog>

    <!-- 编辑项目对话框 -->
    <el-dialog v-model="showEdit" title="编辑项目" width="640px" destroy-on-close>
      <el-form label-width="100px" label-position="left">
        <el-form-item label="项目名称">
          <el-input v-model="editForm.name" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="editForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="Resize 高">
              <el-input-number v-model="editForm.resize_h" :min="640" :step="256" style="width:100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="Resize 宽">
              <el-input-number v-model="editForm.resize_w" :min="640" :step="256" style="width:100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="切割尺寸">
              <el-input-number v-model="editForm.crop_size" :min="320" :max="1280" :step="32" style="width:100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="重叠率">
              <el-input-number v-model="editForm.overlap" :min="0" :max="0.5" :step="0.05" :precision="2" style="width:100%" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>

      <!-- 类别管理 -->
      <div style="margin-top:8px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
          <b>缺陷类别</b>
          <el-button type="primary" size="small" @click="addClassRow">+ 新增类别</el-button>
        </div>
        <el-table :data="editClasses" stripe size="small" style="width:100%">
          <el-table-column label="编号" width="70">
            <template #default="{row}"><el-tag size="small">C{{ row.class_index }}</el-tag></template>
          </el-table-column>
          <el-table-column label="名称" min-width="140">
            <template #default="{row}"><el-input v-model="row.name" size="small" /></template>
          </el-table-column>
          <el-table-column label="颜色" width="100">
            <template #default="{row}"><el-color-picker v-model="row.color" size="small" /></template>
          </el-table-column>
          <el-table-column label="操作" width="70">
            <template #default="{row,$index}">
              <el-button type="danger" text size="small" @click="removeClassRow($index, row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <template #footer>
        <el-button @click="showEdit = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveProject">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { projectApi, type ProjectStats } from '../api/project'
import { imageApi, type ImageInfo } from '../api/image'
import type { UploadFile } from 'element-plus'

const props = defineProps<{ id: string }>()
const router = useRouter()
const projectId = parseInt(props.id)

const project = ref<ProjectStats | null>(null)
const images = ref<ImageInfo[]>([])
const imageTotal = ref(0)
const page = ref(1)
const pageSize = 60
const filterStatus = ref('')
const loading = ref(false)

// 上传
const showUpload = ref(false)
const uploadRef = ref()
const uploadFiles = ref<File[]>([])
const uploadFileList = ref<UploadFile[]>([])
const uploading = ref(false)
const uploadProgress = ref(0)

async function loadProject() {
  const { data } = await projectApi.get(projectId)
  project.value = data
}

async function loadImages(p?: number) {
  if (p) page.value = p
  loading.value = true
  try {
    const params: any = { page: page.value, page_size: pageSize }
    if (filterStatus.value) params.status = filterStatus.value
    const { data } = await imageApi.list(projectId, params)
    images.value = data.items
    imageTotal.value = data.total
  } finally {
    loading.value = false
  }
}

function getThumbUrl(imageId: number) {
  return imageApi.getFileUrl(imageId, true)
}

function goAnnotate(imageId: number) {
  router.push(`/annotate/${projectId}/${imageId}`)
}

function statusLabel(s: string) {
  return { unlabeled: '未标注', labeling: '标注中', labeled: '已标注', reviewed: '已审核' }[s] || s
}

function statusTagType(s: string) {
  return { unlabeled: 'info', labeling: 'warning', labeled: '', reviewed: 'success' }[s] as any || 'info'
}

async function handleDeleteImage(imageId: number, filename: string) {
  try {
    await ElMessageBox.confirm(`确定删除图像「${filename}」？`, '删除确认', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await imageApi.delete(imageId)
    ElMessage.success('已删除')
    loadProject()
    loadImages()
  } catch {}
}

function onFileChange(file: UploadFile) {
  if (file.raw) uploadFiles.value.push(file.raw)
}
function onFileRemove(file: UploadFile) {
  uploadFiles.value = uploadFiles.value.filter(f => f.name !== file.name)
}

async function handleUpload() {
  if (uploadFiles.value.length === 0) return
  uploading.value = true
  uploadProgress.value = 0
  try {
    const { data } = await imageApi.upload(projectId, uploadFiles.value, (pct) => {
      uploadProgress.value = pct
    })
    ElMessage.success(`成功上传 ${data.length} 张图像`)
    showUpload.value = false
    uploadFiles.value = []
    uploadFileList.value = []
    uploadProgress.value = 0
    loadProject()
    loadImages(1)
  } finally {
    uploading.value = false
  }
}

onMounted(() => {
  loadProject()
  loadImages()
})

// ---- 编辑项目 ----
import type { DefectClass } from '../api/project'
import { projectApi } from '../api/project'

const showEdit = ref(false)
const saving = ref(false)
const editForm = ref({ name: '', description: '', resize_h: 2048, resize_w: 2048, crop_size: 640, overlap: 0.2 })
const editClasses = ref<(DefectClass & { _isNew?: boolean })[]>([])

function openEditDialog() {
  if (!project.value) return
  editForm.value = {
    name: project.value.name,
    description: project.value.description || '',
    resize_h: project.value.resize_h,
    resize_w: project.value.resize_w,
    crop_size: project.value.crop_size,
    overlap: project.value.overlap,
  }
  editClasses.value = project.value.defect_classes.map(c => ({ ...c }))
  showEdit.value = true
}

function addClassRow() {
  const maxIdx = editClasses.value.length > 0 ? Math.max(...editClasses.value.map(c => c.class_index)) : -1
  editClasses.value.push({ class_index: maxIdx + 1, name: `defect_${maxIdx + 2}`, color: randomColor(), _isNew: true })
}

async function removeClassRow(idx: number, row: DefectClass & { _isNew?: boolean }) {
  if (row._isNew) {
    editClasses.value.splice(idx, 1)
    return
  }
  try {
    await projectApi.deleteClass(projectId, row.id!)
    editClasses.value.splice(idx, 1)
    ElMessage.success('类别已删除')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '删除失败，可能有标注引用该类别')
  }
}

async function saveProject() {
  saving.value = true
  try {
    // 更新项目基本信息
    await projectApi.update(projectId, editForm.value)
    // 保存类别（新增或更新）
    for (const cls of editClasses.value) {
      if (cls._isNew) {
        await projectApi.addClass(projectId, { class_index: cls.class_index, name: cls.name, color: cls.color })
      } else {
        await projectApi.updateClass(projectId, cls.id!, { class_index: cls.class_index, name: cls.name, color: cls.color })
      }
    }
    ElMessage.success('项目已更新')
    showEdit.value = false
    loadProject()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally { saving.value = false }
}

function randomColor() {
  const colors = ['#FF4D4F','#FF7A45','#FFA940','#FADB14','#52C41A','#13C2C2','#1890FF','#722ED1','#EB2F96']
  return colors[Math.floor(Math.random() * colors.length)]
}
</script>

<style scoped>
.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.header-actions {
  display: flex;
  gap: 10px;
}
.stat-cards .stat-card {
  cursor: pointer;
  transition: transform 0.15s;
}
.stat-cards .stat-card:hover {
  transform: translateY(-2px);
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
}
.total-hint {
  font-size: 13px;
  color: #909399;
}
.image-card .filename {
  font-weight: 500;
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.image-card .meta-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.image-card .ann-count {
  font-size: 11px;
  color: #909399;
}
.pagination {
  display: flex;
  justify-content: center;
  margin-top: 24px;
}
</style>
