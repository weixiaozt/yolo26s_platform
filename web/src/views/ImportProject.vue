<template>
  <div class="page-container" style="max-width:900px">
    <div class="page-header">
      <div style="display:flex;align-items:center;gap:12px">
        <el-button text @click="router.push('/')"><el-icon><ArrowLeft /></el-icon> 返回</el-button>
        <h1>导入项目</h1>
      </div>
    </div>

    <!-- 任务类型选择 -->
    <el-card shadow="never" style="margin-bottom:16px" v-if="step===0">
      <el-form-item label="任务类型" label-width="100px" style="margin-bottom:0">
        <el-radio-group v-model="taskType">
          <el-radio-button label="seg">实例分割（Mask + XML）</el-radio-button>
          <el-radio-button label="det">目标检测（图片 + XML）</el-radio-button>
        </el-radio-group>
        <div style="font-size:12px;color:#909399;margin-top:4px">
          <span v-if="taskType === 'seg'">分割：上传原图 + Mask PNG + (可选) XML，按像素值映射类别</span>
          <span v-else>检测：上传原图 + Pascal VOC XML 标注，按类别名映射</span>
        </div>
      </el-form-item>
    </el-card>

    <el-steps :active="step" finish-status="success" style="margin-bottom:32px">
      <el-step title="基本信息" />
      <el-step title="类别配置" />
      <el-step title="上传文件" />
      <el-step title="完成" />
    </el-steps>

    <!-- Step 0: 基本信息 -->
    <el-card v-if="step===0" shadow="never">
      <el-form label-width="120px" style="max-width:500px">
        <el-form-item label="项目名称" required>
          <el-input v-model="projectName" placeholder="例如：硅片缺陷检测-批次1" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="description" type="textarea" :rows="2" />
        </el-form-item>
        <template v-if="taskType === 'seg'">
          <el-form-item label="Resize 高">
            <el-input-number v-model="resizeH" :min="640" :step="256" />
          </el-form-item>
          <el-form-item label="Resize 宽">
            <el-input-number v-model="resizeW" :min="640" :step="256" />
          </el-form-item>
        </template>
        <template v-else>
          <el-form-item label="训练图尺寸">
            <el-input-number v-model="cropSize" :min="320" :step="32" />
            <div class="hint">检测项目不滑窗，图片直接以此尺寸训练（推荐与原图一致，如 640）</div>
          </el-form-item>
        </template>
        <el-form-item>
          <el-button type="primary" @click="step=1" :disabled="!projectName.trim()">下一步</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- Step 1: 类别配置 -->
    <el-card v-if="step===1" shadow="never">
      <!-- 分割模式：像素值 → 类别 -->
      <template v-if="taskType === 'seg'">
        <div style="margin-bottom:16px">
          <b>配置像素值 → 类别映射</b>
          <p style="font-size:13px;color:#909399;margin-top:4px">
            Mask PNG 中每个像素值代表一个类别（0=背景）。请配置每个像素值对应的类别名。
          </p>
        </div>

        <el-card shadow="never" style="margin-bottom:20px;background:#fafafa">
          <div style="margin-bottom:12px;font-size:13px;font-weight:600">自动识别（可选）</div>
          <div style="display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap">
            <div>
              <div style="font-size:12px;color:#909399;margin-bottom:4px">上传部分 XML + 对应 Mask，自动匹配像素值→类别名</div>
              <div style="display:flex;gap:8px">
                <el-upload :auto-upload="false" :show-file-list="false" multiple accept=".xml"
                  :on-change="(f:any)=>{if(f.raw)autoXmlFiles.push(f.raw)}">
                  <el-button size="small">选 XML</el-button>
                </el-upload>
                <span style="font-size:12px;color:#606266;line-height:32px">{{ autoXmlFiles.length }} 个</span>
                <el-upload :auto-upload="false" :show-file-list="false" multiple accept=".png,.bmp,.tif"
                  :on-change="(f:any)=>{if(f.raw)autoMaskFiles.push(f.raw)}">
                  <el-button size="small">选 Mask</el-button>
                </el-upload>
                <span style="font-size:12px;color:#606266;line-height:32px">{{ autoMaskFiles.length }} 个</span>
                <el-button type="primary" size="small" :loading="scanning" @click="autoDetect"
                  :disabled="autoXmlFiles.length===0||autoMaskFiles.length===0">
                  自动识别
                </el-button>
              </div>
            </div>
          </div>
        </el-card>

        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
          <b>类别列表</b>
          <el-button type="primary" size="small" @click="addClassMapping">+ 手动添加</el-button>
        </div>
        <el-table :data="classMappings" stripe size="small" style="width:100%" empty-text="请添加或自动识别类别">
          <el-table-column label="像素值" width="100">
            <template #default="{row}"><el-input-number v-model="row.pixelVal" :min="1" :max="255" size="small" style="width:80px" /></template>
          </el-table-column>
          <el-table-column label="类别编号" width="100">
            <template #default="{row}"><el-tag size="small">C{{ row.classIndex }}</el-tag></template>
          </el-table-column>
          <el-table-column label="类别名称" min-width="160">
            <template #default="{row}"><el-input v-model="row.name" size="small" placeholder="如：崩边" /></template>
          </el-table-column>
          <el-table-column label="颜色" width="80">
            <template #default="{row}"><el-color-picker v-model="row.color" size="small" /></template>
          </el-table-column>
          <el-table-column label="操作" width="60">
            <template #default="{$index}"><el-button type="danger" text size="small" @click="classMappings.splice($index,1)">删除</el-button></template>
          </el-table-column>
        </el-table>
      </template>

      <!-- 检测模式：类别名 → 类别编号 -->
      <template v-else>
        <div style="margin-bottom:16px">
          <b>配置类别（VOC XML 中 &lt;name&gt; 标签）</b>
          <p style="font-size:13px;color:#909399;margin-top:4px">
            可上传部分 XML 自动扫描类别名，或手动添加。
          </p>
        </div>

        <el-card shadow="never" style="margin-bottom:20px;background:#fafafa">
          <div style="margin-bottom:12px;font-size:13px;font-weight:600">自动扫描类别（可选）</div>
          <div style="display:flex;gap:8px;align-items:center">
            <el-upload :auto-upload="false" :show-file-list="false" multiple accept=".xml"
              :on-change="(f:any)=>{if(f.raw)scanXmlFiles.push(f.raw)}">
              <el-button size="small">选 XML</el-button>
            </el-upload>
            <span style="font-size:12px;color:#606266;line-height:32px">{{ scanXmlFiles.length }} 个</span>
            <el-button type="primary" size="small" :loading="scanning" @click="scanVocClasses"
              :disabled="scanXmlFiles.length===0">
              扫描类别
            </el-button>
          </div>
        </el-card>

        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
          <b>类别列表</b>
          <el-button type="primary" size="small" @click="addDetClass">+ 手动添加</el-button>
        </div>
        <el-table :data="detClasses" stripe size="small" style="width:100%" empty-text="请添加或扫描类别">
          <el-table-column label="类别名（XML name）" min-width="180">
            <template #default="{row}"><el-input v-model="row.name" size="small" placeholder="如：panel" /></template>
          </el-table-column>
          <el-table-column label="类别编号" width="100">
            <template #default="{row}"><el-tag size="small">C{{ row.classIndex }}</el-tag></template>
          </el-table-column>
          <el-table-column label="出现次数" width="100">
            <template #default="{row}"><span style="font-size:12px;color:#606266">{{ row.count || '-' }}</span></template>
          </el-table-column>
          <el-table-column label="颜色" width="80">
            <template #default="{row}"><el-color-picker v-model="row.color" size="small" /></template>
          </el-table-column>
          <el-table-column label="操作" width="60">
            <template #default="{$index}"><el-button type="danger" text size="small" @click="detClasses.splice($index,1)">删除</el-button></template>
          </el-table-column>
        </el-table>
      </template>

      <div style="margin-top:20px;display:flex;gap:10px">
        <el-button @click="step=0">上一步</el-button>
        <el-button type="primary" @click="step=2"
          :disabled="taskType==='seg' ? classMappings.length===0 : detClasses.length===0">
          下一步
        </el-button>
      </div>
    </el-card>

    <!-- Step 2: 上传文件 -->
    <el-card v-if="step===2" shadow="never">
      <!-- 分割：图片 + Mask -->
      <el-row :gutter="24" v-if="taskType === 'seg'">
        <el-col :span="12">
          <div style="font-weight:600;margin-bottom:8px">原图（{{ imgFiles.length }} 张）</div>
          <el-upload drag :auto-upload="false" :show-file-list="false" multiple
            accept=".bmp,.png,.jpg,.jpeg,.tif,.tiff" :on-change="onImgChange">
            <div style="padding:20px 0;color:#909399">拖拽或点击上传原图</div>
          </el-upload>
          <div v-if="imgFiles.length>0" style="max-height:200px;overflow-y:auto;margin-top:8px;font-size:11px;color:#606266">
            <div v-for="f in imgFiles" :key="f.name">{{ f.name }}</div>
          </div>
        </el-col>
        <el-col :span="12">
          <div style="font-weight:600;margin-bottom:8px">Mask PNG（{{ maskFiles.length }} 张）</div>
          <el-upload drag :auto-upload="false" :show-file-list="false" multiple
            accept=".png,.bmp,.tif,.tiff" :on-change="onMaskChange">
            <div style="padding:20px 0;color:#909399">拖拽或点击上传 Mask</div>
          </el-upload>
          <div v-if="maskFiles.length>0" style="max-height:200px;overflow-y:auto;margin-top:8px;font-size:11px;color:#606266">
            <div v-for="f in maskFiles" :key="f.name">{{ f.name }}</div>
          </div>
        </el-col>
      </el-row>

      <!-- 检测：图片 + XML -->
      <el-row :gutter="24" v-else>
        <el-col :span="12">
          <div style="font-weight:600;margin-bottom:8px">原图（{{ imgFiles.length }} 张）</div>
          <el-upload drag :auto-upload="false" :show-file-list="false" multiple
            accept=".bmp,.png,.jpg,.jpeg,.tif,.tiff" :on-change="onImgChange">
            <div style="padding:20px 0;color:#909399">拖拽或点击上传原图</div>
          </el-upload>
          <div v-if="imgFiles.length>0" style="max-height:200px;overflow-y:auto;margin-top:8px;font-size:11px;color:#606266">
            <div v-for="f in imgFiles" :key="f.name">{{ f.name }}</div>
          </div>
        </el-col>
        <el-col :span="12">
          <div style="font-weight:600;margin-bottom:8px">VOC XML（{{ xmlFiles.length }} 个）</div>
          <el-upload drag :auto-upload="false" :show-file-list="false" multiple
            accept=".xml" :on-change="onXmlChange">
            <div style="padding:20px 0;color:#909399">拖拽或点击上传 XML</div>
          </el-upload>
          <div v-if="xmlFiles.length>0" style="max-height:200px;overflow-y:auto;margin-top:8px;font-size:11px;color:#606266">
            <div v-for="f in xmlFiles" :key="f.name">{{ f.name }}</div>
          </div>
        </el-col>
      </el-row>

      <el-alert
        v-if="imgFiles.length>0 && (taskType==='seg' ? maskFiles.length>0 : xmlFiles.length>0)"
        type="info" :closable="false" style="margin-top:16px">
        <div style="font-size:12px">
          原图 {{ imgFiles.length }} 张，{{ taskType==='seg' ? `Mask ${maskFiles.length} 张` : `XML ${xmlFiles.length} 个` }}。
          按文件名匹配（同名不同后缀）。
        </div>
      </el-alert>

      <div style="margin-top:20px;display:flex;gap:10px">
        <el-button @click="step=1">上一步</el-button>
        <el-button type="primary" :loading="importing" @click="doImport"
          :disabled="canImport === false">
          开始导入
        </el-button>
      </div>
    </el-card>

    <!-- Step 3: 完成 -->
    <el-card v-if="step===3" shadow="never" style="text-align:center;padding:40px 0">
      <el-icon style="font-size:48px;color:#67C23A"><SuccessFilled /></el-icon>
      <h2 style="margin:16px 0 8px">导入完成！</h2>
      <div style="color:#606266;margin-bottom:24px" v-if="taskType==='seg'">
        共导入 <b>{{ result.stats?.total || 0 }}</b> 张图片，
        <b>{{ result.stats?.with_ann || 0 }}</b> 张有标注，
        <b>{{ result.stats?.total_polygons || 0 }}</b> 个缺陷多边形
      </div>
      <div style="color:#606266;margin-bottom:24px" v-else>
        共导入 <b>{{ result.stats?.total || 0 }}</b> 张图片，
        <b>{{ result.stats?.with_ann || 0 }}</b> 张有标注，
        <b>{{ result.stats?.total_boxes || 0 }}</b> 个 bbox
      </div>
      <el-button type="primary" @click="router.push(`/project/${result.project_id}`)">进入项目</el-button>
    </el-card>

    <!-- Loading -->
    <div v-if="importing" class="loading-overlay">
      <el-icon class="is-loading" style="font-size:36px;color:#409EFF"><Loading /></el-icon>
      <div style="color:#fff;margin-top:10px">正在导入... 请勿关闭页面</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api/index'
import type { UploadFile } from 'element-plus'

const router = useRouter()
const step = ref(0)

// 任务类型
const taskType = ref<'seg' | 'det'>('seg')

// Step 0
const projectName = ref('')
const description = ref('')
const resizeH = ref(2048)
const resizeW = ref(2048)
const cropSize = ref(640)

// Step 1 - seg
interface ClassMap { pixelVal: number; classIndex: number; name: string; color: string }
const classMappings = ref<ClassMap[]>([])
const autoXmlFiles = ref<File[]>([])
const autoMaskFiles = ref<File[]>([])
const scanning = ref(false)

// Step 1 - det
interface DetClass { name: string; classIndex: number; color: string; count?: number }
const detClasses = ref<DetClass[]>([])
const scanXmlFiles = ref<File[]>([])

const defaultColors = ['#FF4D4F','#FF7A45','#FFA940','#52C41A','#13C2C2','#1890FF','#722ED1','#EB2F96','#FADB14','#A0D911']

function addClassMapping() {
  const maxPv = classMappings.value.length > 0 ? Math.max(...classMappings.value.map(c => c.pixelVal)) : 0
  const idx = classMappings.value.length
  classMappings.value.push({
    pixelVal: maxPv + 1,
    classIndex: idx,
    name: '',
    color: defaultColors[idx % defaultColors.length],
  })
}

function addDetClass() {
  const idx = detClasses.value.length
  detClasses.value.push({
    name: '',
    classIndex: idx,
    color: defaultColors[idx % defaultColors.length],
  })
}

async function autoDetect() {
  if (autoXmlFiles.value.length === 0 || autoMaskFiles.value.length === 0) return
  scanning.value = true
  try {
    const fd = new FormData()
    autoXmlFiles.value.forEach(f => fd.append('xml_files', f))
    autoMaskFiles.value.forEach(f => fd.append('mask_files', f))
    const { data } = await api.post('/import/auto-mapping', fd, {
      headers: { 'Content-Type': 'multipart/form-data' }, timeout: 60000,
    })
    const mapping = data.mapping as Record<string, string>
    const existingPvs = new Set(classMappings.value.map(c => c.pixelVal))
    for (const [pvStr, name] of Object.entries(mapping)) {
      const pv = parseInt(pvStr)
      if (!existingPvs.has(pv)) {
        const idx = classMappings.value.length
        classMappings.value.push({
          pixelVal: pv, classIndex: idx, name,
          color: defaultColors[idx % defaultColors.length],
        })
        existingPvs.add(pv)
      }
    }
    ElMessage.success(`识别到 ${Object.keys(mapping).length} 个类别映射`)
  } catch { ElMessage.error('自动识别失败') }
  finally { scanning.value = false }
}

async function scanVocClasses() {
  if (scanXmlFiles.value.length === 0) return
  scanning.value = true
  try {
    const fd = new FormData()
    scanXmlFiles.value.forEach(f => fd.append('files', f))
    const { data } = await api.post('/import/voc-scan', fd, {
      headers: { 'Content-Type': 'multipart/form-data' }, timeout: 60000,
    })
    const classes = data.classes as Record<string, number>  // {name: count}
    const existingNames = new Set(detClasses.value.map(c => c.name))
    for (const [name, count] of Object.entries(classes)) {
      if (!existingNames.has(name)) {
        const idx = detClasses.value.length
        detClasses.value.push({
          name, classIndex: idx,
          color: defaultColors[idx % defaultColors.length],
          count,
        })
        existingNames.add(name)
      } else {
        // 更新计数
        const c = detClasses.value.find(c => c.name === name)
        if (c) c.count = count
      }
    }
    ElMessage.success(`扫描到 ${Object.keys(classes).length} 个类别`)
  } catch { ElMessage.error('扫描失败') }
  finally { scanning.value = false }
}

// Step 2
const imgFiles = ref<File[]>([])
const maskFiles = ref<File[]>([])
const xmlFiles = ref<File[]>([])

function onImgChange(f: UploadFile) { if (f.raw) imgFiles.value.push(f.raw) }
function onMaskChange(f: UploadFile) { if (f.raw) maskFiles.value.push(f.raw) }
function onXmlChange(f: UploadFile) { if (f.raw) xmlFiles.value.push(f.raw) }

const canImport = computed(() => {
  if (imgFiles.value.length === 0) return false
  if (taskType.value === 'seg') return maskFiles.value.length > 0
  return xmlFiles.value.length > 0
})

// Step 3
const importing = ref(false)
const result = ref<any>({})

async function doImport() {
  importing.value = true
  try {
    const fd = new FormData()
    fd.append('project_name', projectName.value)
    fd.append('description', description.value)

    if (taskType.value === 'seg') {
      // 分割：原有逻辑
      const mapping: Record<string, any> = {}
      for (const c of classMappings.value) {
        mapping[String(c.pixelVal)] = { class_index: c.classIndex, name: c.name, color: c.color }
      }
      fd.append('resize_h', String(resizeH.value))
      fd.append('resize_w', String(resizeW.value))
      fd.append('class_mapping_json', JSON.stringify(mapping))
      imgFiles.value.forEach(f => fd.append('images', f))
      maskFiles.value.forEach(f => fd.append('masks', f))
      const { data } = await api.post('/import/run', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 600000,
      })
      result.value = data
    } else {
      // 检测：VOC 导入
      const mapping: Record<string, any> = {}
      for (const c of detClasses.value) {
        if (!c.name.trim()) continue
        mapping[c.name] = { class_index: c.classIndex, color: c.color }
      }
      if (Object.keys(mapping).length === 0) {
        ElMessage.error('请至少配置一个类别')
        importing.value = false
        return
      }
      fd.append('crop_size', String(cropSize.value))
      fd.append('class_mapping_json', JSON.stringify(mapping))
      imgFiles.value.forEach(f => fd.append('images', f))
      xmlFiles.value.forEach(f => fd.append('xmls', f))
      const { data } = await api.post('/import/voc-run', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 600000,
      })
      result.value = data
    }

    step.value = 3
    ElMessage.success('导入完成！')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '导入失败')
  } finally { importing.value = false }
}
</script>

<style scoped>
.loading-overlay {
  position: fixed; top: 0; left: 0; right: 0; bottom: 0; z-index: 9999;
  background: rgba(0,0,0,.5); display: flex; flex-direction: column;
  justify-content: center; align-items: center;
}
.hint { font-size: 12px; color: #909399; margin-top: 4px; }
</style>
