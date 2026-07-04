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
      <div class="header-actions btn-group">
        <el-button class="hbtn hbtn--blue" @click="showUpload = true">
          <el-icon><Upload /></el-icon>
          上传图像
        </el-button>
        <el-button class="hbtn hbtn--gray" @click="openMerge">
          <el-icon><Connection /></el-icon>
          合并标注包
        </el-button>
        <el-button
          v-if="project?.task_type === 'cls'"
          class="hbtn hbtn--teal"
          @click="router.push(`/cls-annotate/${id}`)"
        >
          <el-icon><Grid /></el-icon>
          批量分类标注
        </el-button>
        <el-button
          class="hbtn hbtn--green"
          :disabled="!project || project.labeled_count + project.reviewed_count === 0"
          @click="router.push(`/project/${id}/train`)"
        >
          <el-icon><VideoPlay /></el-icon>
          训练模型
        </el-button>
        <el-button
          class="hbtn hbtn--cyan"
          @click="router.push(`/project/${id}/train/monitor`)"
        >
          <el-icon><TrendCharts /></el-icon>
          训练监控
        </el-button>
        <el-button
          class="hbtn hbtn--orange"
          @click="router.push(`/project/${id}/inference`)"
        >
          <el-icon><Aim /></el-icon>
          在线推断
        </el-button>
        <el-button
          class="hbtn hbtn--violet"
          @click="router.push(`/project/${id}/export`)"
        >
          <el-icon><Switch /></el-icon>
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
      <div class="batch-actions">
        <template v-if="batchMode">
          <span class="total-hint">已选 {{ selectedIds.size }} 张</span>
          <el-button size="small" @click="selectAllOnPage">全选本页</el-button>
          <el-button size="small" :disabled="selectedIds.size === 0" @click="clearSelection">清空选择</el-button>
          <el-button
            size="small" type="danger"
            :disabled="selectedIds.size === 0"
            :loading="batchDeleting"
            @click="handleBatchDelete"
          >
            <el-icon><Delete /></el-icon>
            删除选中
          </el-button>
          <el-button size="small" @click="exitBatchMode">退出批量</el-button>
        </template>
        <el-button v-else size="small" @click="batchMode = true">批量选择</el-button>
      </div>
    </div>

    <!-- 图像网格 -->
    <div v-if="images.length > 0" class="image-grid">
      <el-card
        v-for="img in images"
        :key="img.id"
        :class="['image-card', { 'batch-selected': batchMode && selectedIds.has(img.id) }]"
        shadow="hover"
        :body-style="{ padding: 0 }"
        @click="onCardClick(img)"
      >
        <div
          v-if="batchMode"
          :class="['batch-check', { checked: selectedIds.has(img.id) }]"
        >
          <el-icon v-if="selectedIds.has(img.id)"><Check /></el-icon>
        </div>
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
              v-if="!batchMode"
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
      <input
        v-if="project?.task_type === 'cls'"
        ref="folderUploadInput"
        type="file"
        webkitdirectory
        multiple
        style="display:none"
        @change="onFolderUploadPick"
      />
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
      <div v-if="project?.task_type === 'cls'" class="cls-upload-tools">
        <el-button size="small" @click="(folderUploadInput as any)?.click?.()">选择文件夹</el-button>
        <el-checkbox v-model="autoLabelByFolder">按文件夹名自动标注</el-checkbox>
      </div>
      <div v-if="project?.task_type === 'cls' && folderUploadCount > 0" class="folder-upload-hint">
        已选择文件夹图片 {{ folderUploadCount }} 张
      </div>

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

    <!-- 合并标注包对话框 -->
    <el-dialog v-model="showMerge" title="合并标注包" width="560px" @close="resetMerge">
      <el-alert type="info" :closable="false" show-icon style="margin-bottom:14px"
        title="把另一台机器导出的标注包合并进当前项目"
        description="按图片内容匹配同一张图，标注并集去重（重复的自动跳过）；对方独有的新标注图连图带标注一起合进来。先预览，确认后再写入。" />

      <el-upload
        v-if="!mergeReport && !mergeChecking"
        drag :auto-upload="false" :show-file-list="false" accept=".zip"
        :on-change="onMergeFileChange"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">拖拽标注包 ZIP，或<em>点击选择</em></div>
        <template #tip>
          <div class="el-upload__tip">导出的标注包即可（只含已标注图 + 标注）；选择后先预览不写入</div>
        </template>
      </el-upload>

      <div v-if="mergeChecking" style="text-align:center;padding:24px;color:#909399">
        <el-icon class="is-loading"><Loading /></el-icon> 正在预览合并结果…
      </div>

      <div v-if="mergeReport" class="merge-report">
        <div class="mr-file">📦 {{ mergeFileName }}</div>
        <div class="mr-grid">
          <div class="mr-cell"><div class="mr-num">{{ mergeReport.matched_images }}</div><div class="mr-lbl">匹配同一张图</div></div>
          <div class="mr-cell"><div class="mr-num" style="color:#3f78f0">+{{ mergeReport.added_annotations }}</div><div class="mr-lbl">新增标注</div></div>
          <div class="mr-cell"><div class="mr-num" style="color:#34b86a">+{{ mergeReport.new_images }}</div><div class="mr-lbl">新增标注图</div></div>
          <div class="mr-cell"><div class="mr-num" style="color:#909399">{{ mergeReport.skipped_duplicates }}</div><div class="mr-lbl">跳过重复</div></div>
        </div>
        <div class="mr-note">包内共 {{ mergeReport.pack_images }} 张标注图 / {{ mergeReport.pack_annotations }} 条标注</div>
        <el-alert v-if="mergeReport.new_classes.length" type="warning" :closable="false" style="margin-top:10px"
          :title="`将新建 ${mergeReport.new_classes.length} 个类别：${mergeReport.new_classes.join('、')}`" />
        <el-alert v-if="mergeReport.cls_conflicts.length" type="error" :closable="false" style="margin-top:10px"
          :title="`${mergeReport.cls_conflicts.length} 张图分类标签冲突（保留当前项目的）`">
          <div style="max-height:120px;overflow:auto;font-size:12px;margin-top:4px">
            <div v-for="(c,i) in mergeReport.cls_conflicts" :key="i">{{ c.filename }}：当前「{{ c.target_class }}」← 包里「{{ c.incoming_class }}」</div>
          </div>
        </el-alert>
        <el-alert v-if="mergeReport.unmatched_no_image" type="info" :closable="false" style="margin-top:10px"
          :title="`${mergeReport.unmatched_no_image} 张新图因包内没带图片字节被跳过`" />
        <el-alert v-if="mergeReport.added_annotations===0 && mergeReport.new_images===0 && mergeReport.new_classes.length===0"
          type="success" :closable="false" style="margin-top:10px" title="没有可合并的新内容（全部已存在）" />
      </div>

      <template #footer>
        <el-button @click="showMerge = false">取消</el-button>
        <el-button
          v-if="mergeReport"
          class="hbtn hbtn--gray" :loading="merging"
          :disabled="mergeReport.added_annotations===0 && mergeReport.new_images===0 && mergeReport.new_classes.length===0"
          @click="confirmMerge"
        >确认合并</el-button>
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
        <!-- cls 项目隐藏 Resize/切割尺寸/重叠率（cls 训练统一走 imgsz=224，不切大图） -->
        <template v-if="project?.task_type !== 'cls'">
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
        </template>
        <el-form-item v-else>
          <el-alert type="info" :closable="false" show-icon
            title="分类项目无需 Resize/切割尺寸"
            description="分类训练统一使用 ImageNet 标准 imgsz=224，原图直接 letterbox 到 224×224。这些字段对分类无效。" />
        </el-form-item>
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
import { projectApi, type ProjectStats, type MergeReport } from '../api/project'
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
const folderUploadInput = ref<HTMLInputElement>()
const uploadFiles = ref<File[]>([])
const uploadFileList = ref<UploadFile[]>([])
const uploading = ref(false)
const uploadProgress = ref(0)
const autoLabelByFolder = ref(false)
const folderUploadCount = ref(0)

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
  // cls 项目跳到批量标注，其他跳到单图标注器
  if (project.value?.task_type === 'cls') {
    router.push(`/cls-annotate/${projectId}`)
  } else {
    router.push(`/annotate/${projectId}/${imageId}`)
  }
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

// ---- 批量选择 / 批量删除 ----
const batchMode = ref(false)
const selectedIds = ref(new Set<number>())
const batchDeleting = ref(false)

function onCardClick(img: ImageInfo) {
  if (!batchMode.value) {
    goAnnotate(img.id)
    return
  }
  if (selectedIds.value.has(img.id)) selectedIds.value.delete(img.id)
  else selectedIds.value.add(img.id)
}

function selectAllOnPage() {
  images.value.forEach((i) => selectedIds.value.add(i.id))
}

function clearSelection() {
  selectedIds.value = new Set()
}

function exitBatchMode() {
  batchMode.value = false
  selectedIds.value = new Set()
}

async function handleBatchDelete() {
  const n = selectedIds.value.size
  if (n === 0) return
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${n} 张图像？图像文件和标注都会一并删除，不可恢复。`,
      '批量删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  batchDeleting.value = true
  try {
    const { data } = await imageApi.batchDelete([...selectedIds.value])
    ElMessage.success(`已删除 ${data.deleted} 张图像`)
    selectedIds.value = new Set()
    loadProject()
    // 当前页可能被删空：回退到仍有内容的页
    const maxPage = Math.max(1, Math.ceil((imageTotal.value - data.deleted) / pageSize))
    loadImages(Math.min(page.value, maxPage))
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '批量删除失败')
  } finally {
    batchDeleting.value = false
  }
}

function onFileChange(file: UploadFile) {
  if (file.raw) {
    folderUploadCount.value = 0
    uploadFiles.value.push(file.raw)
  }
}
function onFileRemove(file: UploadFile) {
  uploadFiles.value = uploadFiles.value.filter(f => f.name !== file.name)
  folderUploadCount.value = 0
}
function onFolderUploadPick(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files || []).filter((f) => /\.(bmp|png|jpe?g|tiff?|tif)$/i.test(f.name))
  uploadFiles.value = files
  folderUploadCount.value = files.length
  uploadFileList.value = []
  input.value = ''
}

function showUploadReport(data: any) {
  const details: string[] = []
  if (data.auto_labeled) details.push(`自动标注 ${data.auto_labeled} 张`)
  if (data.renamed?.length) details.push(`${data.renamed.length} 张同名图片已自动重命名`)
  if (data.unknown_folders?.length) details.push(`未匹配文件夹：${data.unknown_folders.slice(0, 5).join('、')}`)
  if (details.length === 0) {
    ElMessage.success(`成功上传 ${data.uploaded ?? data.items?.length ?? 0} 张图像`)
    return
  }
  ElMessageBox.alert(details.join('\n'), '上传完成', {
    type: data.unknown_folders?.length ? 'warning' : 'success',
    confirmButtonText: '知道了',
  })
}

async function handleUpload() {
  if (uploadFiles.value.length === 0) return
  uploading.value = true
  uploadProgress.value = 0
  try {
    const { data } = await imageApi.upload(projectId, uploadFiles.value, (pct) => {
      uploadProgress.value = pct
    }, autoLabelByFolder.value)
    showUploadReport(data)
    showUpload.value = false
    uploadFiles.value = []
    uploadFileList.value = []
    folderUploadCount.value = 0
    uploadProgress.value = 0
    loadProject()
    loadImages(1)
  } finally {
    uploading.value = false
  }
}

// ---- 合并标注包 ----
const showMerge = ref(false)
const mergeFile = ref<File | null>(null)
const mergeFileName = ref('')
const mergeChecking = ref(false)
const merging = ref(false)
const mergeReport = ref<MergeReport | null>(null)

function openMerge() { resetMerge(); showMerge.value = true }
function resetMerge() {
  mergeFile.value = null; mergeFileName.value = ''
  mergeReport.value = null; mergeChecking.value = false; merging.value = false
}
async function onMergeFileChange(uf: UploadFile) {
  if (!uf.raw) return
  mergeFile.value = uf.raw
  mergeFileName.value = uf.name
  mergeChecking.value = true
  mergeReport.value = null
  try {
    const { data } = await projectApi.mergePackage(projectId, uf.raw, true)
    mergeReport.value = data
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '预览失败，请确认是导出的标注包')
    resetMerge()
  } finally {
    mergeChecking.value = false
  }
}
async function confirmMerge() {
  if (!mergeFile.value) return
  merging.value = true
  try {
    const { data } = await projectApi.mergePackage(projectId, mergeFile.value, false)
    ElMessage.success(`合并完成：新增标注 ${data.added_annotations} 条、新增图 ${data.new_images} 张、跳过重复 ${data.skipped_duplicates} 条`)
    showMerge.value = false
    resetMerge()
    loadProject()
    loadImages(1)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '合并失败')
  } finally {
    merging.value = false
  }
}

onMounted(() => {
  loadProject()
  loadImages()
})

// ---- 编辑项目 ----（projectApi 已在文件顶部导入）
import type { DefectClass } from '../api/project'

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
  align-items: center;
  gap: 10px;
}
.merge-report { margin-top: 4px; }
.mr-file { font-size: 13px; color: #606266; margin-bottom: 12px; word-break: break-all; }
.mr-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.mr-cell { background: #f6f8fb; border: 1px solid #eceff5; border-radius: 8px; padding: 12px 6px; text-align: center; }
.mr-num { font-size: 22px; font-weight: 700; color: #303133; line-height: 1.1; }
.mr-lbl { font-size: 12px; color: #909399; margin-top: 4px; }
.mr-note { font-size: 12px; color: #909399; margin-top: 12px; }
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
.batch-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
}
.image-card {
  position: relative;
  cursor: pointer;
}
.image-card.batch-selected {
  outline: 2px solid #409eff;
}
.batch-check {
  position: absolute;
  top: 8px;
  left: 8px;
  z-index: 2;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 2px solid #fff;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 14px;
  box-shadow: 0 0 4px rgba(0, 0, 0, 0.4);
}
.batch-check.checked {
  background: #409eff;
  border-color: #409eff;
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
.cls-upload-tools {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 12px;
  padding: 10px 12px;
  border: 1px solid #e6ebf2;
  border-radius: 8px;
  background: #f8fafc;
}
.folder-upload-hint {
  margin-top: 8px;
  color: #606266;
  font-size: 12px;
}
</style>
