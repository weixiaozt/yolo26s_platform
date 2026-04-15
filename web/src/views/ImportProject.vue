<template>
  <div class="page-container" style="max-width:900px">
    <div class="page-header">
      <div style="display:flex;align-items:center;gap:12px">
        <el-button text @click="router.push('/')"><el-icon><ArrowLeft /></el-icon> 返回</el-button>
        <h1>导入项目</h1>
      </div>
    </div>

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
        <el-form-item label="Resize 高">
          <el-input-number v-model="resizeH" :min="640" :step="256" />
        </el-form-item>
        <el-form-item label="Resize 宽">
          <el-input-number v-model="resizeW" :min="640" :step="256" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="step=1" :disabled="!projectName.trim()">下一步</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- Step 1: 类别配置 -->
    <el-card v-if="step===1" shadow="never">
      <div style="margin-bottom:16px">
        <b>配置像素值 → 类别映射</b>
        <p style="font-size:13px;color:#909399;margin-top:4px">
          Mask PNG 中每个像素值代表一个类别（0=背景）。请配置每个像素值对应的类别名。
        </p>
      </div>

      <!-- 自动识别 -->
      <el-card shadow="never" style="margin-bottom:20px;background:#fafafa">
        <div style="margin-bottom:12px;font-size:13px;font-weight:600">自动识别（可选）</div>
        <div style="display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap">
          <div>
            <div style="font-size:12px;color:#909399;margin-bottom:4px">上传部分 XML + 对应 Mask，自动匹配像素值→类别名</div>
            <div style="display:flex;gap:8px">
              <el-upload ref="xmlUpRef" :auto-upload="false" :show-file-list="false" multiple accept=".xml"
                :on-change="(f:any)=>{if(f.raw)autoXmlFiles.push(f.raw)}">
                <el-button size="small">选 XML</el-button>
              </el-upload>
              <span style="font-size:12px;color:#606266;line-height:32px">{{ autoXmlFiles.length }} 个</span>
              <el-upload ref="maskUpRef" :auto-upload="false" :show-file-list="false" multiple accept=".png,.bmp,.tif"
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

      <!-- 类别列表 -->
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

      <div style="margin-top:20px;display:flex;gap:10px">
        <el-button @click="step=0">上一步</el-button>
        <el-button type="primary" @click="step=2" :disabled="classMappings.length===0">下一步</el-button>
      </div>
    </el-card>

    <!-- Step 2: 上传文件 -->
    <el-card v-if="step===2" shadow="never">
      <el-row :gutter="24">
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

      <el-alert v-if="imgFiles.length>0&&maskFiles.length>0" type="info" :closable="false" style="margin-top:16px">
        <div style="font-size:12px">
          原图 {{ imgFiles.length }} 张，Mask {{ maskFiles.length }} 张。
          原图和 Mask 通过文件名匹配（同名不同后缀）。
        </div>
      </el-alert>

      <div style="margin-top:20px;display:flex;gap:10px">
        <el-button @click="step=1">上一步</el-button>
        <el-button type="primary" :loading="importing" @click="doImport"
          :disabled="imgFiles.length===0||maskFiles.length===0">
          开始导入
        </el-button>
      </div>
    </el-card>

    <!-- Step 3: 完成 -->
    <el-card v-if="step===3" shadow="never" style="text-align:center;padding:40px 0">
      <el-icon style="font-size:48px;color:#67C23A"><SuccessFilled /></el-icon>
      <h2 style="margin:16px 0 8px">导入完成！</h2>
      <div style="color:#606266;margin-bottom:24px">
        共导入 <b>{{ result.stats?.total || 0 }}</b> 张图片，
        <b>{{ result.stats?.with_ann || 0 }}</b> 张有标注，
        <b>{{ result.stats?.total_polygons || 0 }}</b> 个缺陷多边形
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
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api/index'
import type { UploadFile } from 'element-plus'

const router = useRouter()
const step = ref(0)

// Step 0
const projectName = ref('')
const description = ref('')
const resizeH = ref(2048)
const resizeW = ref(2048)

// Step 1
interface ClassMap { pixelVal: number; classIndex: number; name: string; color: string }
const classMappings = ref<ClassMap[]>([])
const autoXmlFiles = ref<File[]>([])
const autoMaskFiles = ref<File[]>([])
const scanning = ref(false)

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
    // 合并到列表（不重复）
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

// Step 2
const imgFiles = ref<File[]>([])
const maskFiles = ref<File[]>([])

function onImgChange(f: UploadFile) { if (f.raw) imgFiles.value.push(f.raw) }
function onMaskChange(f: UploadFile) { if (f.raw) maskFiles.value.push(f.raw) }

// Step 3
const importing = ref(false)
const result = ref<any>({})

async function doImport() {
  // 构建 class_mapping_json
  const mapping: Record<string, any> = {}
  for (const c of classMappings.value) {
    mapping[String(c.pixelVal)] = { class_index: c.classIndex, name: c.name, color: c.color }
  }

  const fd = new FormData()
  fd.append('project_name', projectName.value)
  fd.append('description', description.value)
  fd.append('resize_h', String(resizeH.value))
  fd.append('resize_w', String(resizeW.value))
  fd.append('class_mapping_json', JSON.stringify(mapping))
  imgFiles.value.forEach(f => fd.append('images', f))
  maskFiles.value.forEach(f => fd.append('masks', f))

  importing.value = true
  try {
    const { data } = await api.post('/import/run', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000,
    })
    result.value = data
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
</style>
