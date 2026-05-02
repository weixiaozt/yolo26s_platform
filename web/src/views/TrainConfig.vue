<template>
  <div class="page-container">
    <div class="page-header">
      <div style="display:flex;align-items:center;gap:12px">
        <el-button text @click="router.push(`/project/${id}`)"><el-icon><ArrowLeft /></el-icon> 返回</el-button>
        <h1>训练配置</h1>
      </div>
      <div style="display:flex;gap:10px">
        <el-button @click="router.push(`/project/${id}/train/monitor`)">
          查看训练监控
        </el-button>
        <el-button @click="restoreDefaults">
          <el-icon><RefreshLeft /></el-icon> 恢复默认值
        </el-button>
        <el-button type="success" @click="saveAsDefault" :loading="savingDefaults">
          <el-icon><Document /></el-icon> 保存为默认
        </el-button>
        <el-button type="primary" size="large" @click="startTrain" :loading="submitting">
          <el-icon><VideoPlay /></el-icon> 提交训练任务
        </el-button>
      </div>
    </div>

    <el-form label-width="160px" label-position="left">
      <el-row :gutter="24">
        <!-- 左列 -->
        <el-col :span="12">
          <!-- 训练模式 -->
          <el-card shadow="never" style="margin-bottom:20px">
            <template #header><span style="font-weight:600">训练模式</span></template>
            <el-form-item label="模式">
              <el-radio-group v-model="trainMode">
                <el-radio label="scratch">从头训练</el-radio>
                <el-radio label="finetune" :disabled="completedTasks.length===0">继承训练</el-radio>
              </el-radio-group>
            </el-form-item>
            <template v-if="trainMode==='finetune'">
              <el-form-item label="继承模型">
                <el-select v-model="resumeTaskId" placeholder="选择历史训练任务" style="width:100%">
                  <el-option v-for="t in completedTasks" :key="t.id"
                    :label="`${t.task_name} (mAP ${((t.best_map50||0)*100).toFixed(1)}%)${t.status==='cancelled' ? ' [取消@'+t.current_epoch+'/'+t.epochs+']' : ''}`"
                    :value="t.id" />
                </el-select>
              </el-form-item>
              <el-form-item label="权重选择">
                <el-radio-group v-model="resumeModelType">
                  <el-radio label="best">
                    best.pt（最佳）
                    <el-tag v-if="recommendedModelType==='best'" type="success" size="small" effect="plain" style="margin-left:6px">推荐</el-tag>
                  </el-radio>
                  <el-radio label="last">
                    last.pt（最终）
                    <el-tag v-if="recommendedModelType==='last'" type="success" size="small" effect="plain" style="margin-left:6px">推荐</el-tag>
                  </el-radio>
                </el-radio-group>
                <span v-if="recommendReason" class="hint">{{ recommendReason }}</span>
              </el-form-item>
              <el-alert v-if="classCountWarning" type="warning" :closable="false" style="margin-bottom:8px">
                <div style="font-size:12px">{{ classCountWarning }}</div>
              </el-alert>
              <el-alert type="info" :closable="false">
                <div style="font-size:12px">
                  继承训练：在上次训练的权重基础上继续优化，适合新增标注数据后微调。<br>
                  建议降低学习率（lr0=0.001）、减少 epochs（50~100 轮）。
                </div>
              </el-alert>
            </template>
            <el-alert v-else type="info" :closable="false">
              <div style="font-size:12px">从头训练：使用预训练的 YOLO26s-seg 权重开始，适合首次训练或类别变更后。</div>
            </el-alert>
          </el-card>

          <!-- 基本参数 -->
          <el-card shadow="never" style="margin-bottom:20px">
            <template #header><span style="font-weight:600">基本参数</span></template>
            <el-form-item label="任务名称">
              <el-input v-model="taskName" />
            </el-form-item>
            <el-form-item label="模型尺寸">
              <el-select v-model="c.model_name" style="width:100%">
                <template v-if="taskType === 'cls'">
                  <el-option label="yolo11n-cls.pt · Nano — 最快，~1.5M 参数（推荐小数据）" value="yolo11n-cls.pt" />
                  <el-option label="yolo11s-cls.pt · Small — 均衡，~5M 参数" value="yolo11s-cls.pt" />
                  <el-option label="yolo11m-cls.pt · Medium — 更精准，~10M 参数" value="yolo11m-cls.pt" />
                  <el-option label="yolo11l-cls.pt · Large — 高精度，~13M 参数" value="yolo11l-cls.pt" />
                </template>
                <template v-else-if="taskType === 'det'">
                  <el-option label="yolo26n.pt · Nano — 最快，~3M 参数（推荐小数据）" value="yolo26n.pt" />
                  <el-option label="yolo26s.pt · Small — 均衡，~22M 参数" value="yolo26s.pt" />
                  <el-option label="yolo26m.pt · Medium — 更精准，~38M 参数" value="yolo26m.pt" />
                  <el-option label="yolo26l.pt · Large — 高精度，~58M 参数" value="yolo26l.pt" />
                </template>
                <template v-else-if="taskType === 'obb'">
                  <el-option label="yolo11n-obb.pt · Nano — 最快，~3M 参数（推荐先试）" value="yolo11n-obb.pt" />
                  <el-option label="yolo11s-obb.pt · Small — 均衡，~10M 参数（推荐）" value="yolo11s-obb.pt" />
                  <el-option label="yolo11m-obb.pt · Medium — 更精准，~21M 参数" value="yolo11m-obb.pt" />
                  <el-option label="yolo11l-obb.pt · Large — 高精度，~27M 参数" value="yolo11l-obb.pt" />
                  <el-option label="yolo11x-obb.pt · XLarge — 最精准，~58M 参数" value="yolo11x-obb.pt" />
                </template>
                <template v-else>
                  <el-option label="yolo26n-seg · Nano — 最快，~3M 参数，适合快速验证" value="yolo26n-seg" />
                  <el-option label="yolo26s-seg · Small — 均衡，~24M 参数（推荐）" value="yolo26s-seg" />
                  <el-option label="yolo26m-seg · Medium — 更精准，~40M 参数" value="yolo26m-seg" />
                  <el-option label="yolo26l-seg · Large — 高精度，~63M 参数" value="yolo26l-seg" />
                  <el-option label="yolo26x-seg · XLarge — 最精准，~97M 参数" value="yolo26x-seg" />
                </template>
              </el-select>
              <span class="hint">模型越大精度越高，但速度越慢、显存占用越大</span>
            </el-form-item>
            <el-form-item label="Epochs">
              <el-input-number v-model="c.epochs" :min="1" :max="2000" />
              <span class="hint">训练轮数，建议 150~300</span>
            </el-form-item>
            <el-form-item label="Batch Size">
              <el-input-number v-model="c.batch_size" :min="1" :max="128" />
              <span class="hint">显存不够就调小（4/8）</span>
            </el-form-item>
            <el-form-item label="早停 Patience">
              <el-input-number v-model="c.patience" :min="0" :max="500" />
              <span class="hint">0=禁用，建议 50</span>
            </el-form-item>
            <el-form-item label="训练设备">
              <el-select v-model="c.device" style="width:200px">
                <el-option label="GPU 0" value="0" />
                <el-option label="GPU 1" value="1" />
                <el-option label="CPU" value="cpu" />
              </el-select>
            </el-form-item>
          </el-card>

          <!-- 学习率 -->
          <el-card shadow="never" style="margin-bottom:20px">
            <template #header><span style="font-weight:600">学习率</span></template>
            <el-form-item label="初始学习率 (lr0)">
              <el-input-number v-model="c.lr0" :min="0.0001" :max="0.1" :step="0.001" :precision="4" />
              <span class="hint">默认 0.01</span>
            </el-form-item>
            <el-form-item label="最终学习率 (lrf)">
              <el-input-number v-model="c.lrf" :min="0.001" :max="1" :step="0.01" :precision="3" />
              <span class="hint">lr0 × lrf = 最终LR</span>
            </el-form-item>
            <el-form-item label="动量 (momentum)">
              <el-input-number v-model="c.momentum" :min="0.8" :max="0.999" :step="0.01" :precision="3" />
            </el-form-item>
            <el-form-item label="权重衰减">
              <el-input-number v-model="c.weight_decay" :min="0" :max="0.01" :step="0.0001" :precision="5" />
            </el-form-item>
            <el-form-item label="预热轮数">
              <el-input-number v-model="c.warmup_epochs" :min="0" :max="20" :step="1" :precision="1" />
            </el-form-item>
            <el-form-item label="预热动量">
              <el-input-number v-model="c.warmup_momentum" :min="0" :max="0.99" :step="0.01" :precision="2" />
            </el-form-item>
          </el-card>

          <!-- 数据划分 -->
          <el-card shadow="never" style="margin-bottom:20px">
            <template #header><span style="font-weight:600">数据划分</span></template>
            <el-form-item label="训练集比例">
              <el-slider v-model="c.train_ratio" :min="0.5" :max="0.95" :step="0.05" show-input />
            </el-form-item>
            <el-form-item label="稀有类过采样倍数">
              <el-input-number v-model="c.oversample_factor" :min="1" :max="20" />
              <span class="hint">小数据集建议 5~10</span>
            </el-form-item>
          </el-card>
        </el-col>

        <!-- 右列 -->
        <el-col :span="12">
          <!-- 颜色增广 -->
          <el-card shadow="never" style="margin-bottom:20px">
            <template #header><span style="font-weight:600">颜色增广</span></template>
            <el-form-item label="HSV-H (色调)">
              <el-slider v-model="c.hsv_h" :min="0" :max="1" :step="0.005" show-input :show-input-controls="false" />
            </el-form-item>
            <el-form-item label="HSV-S (饱和度)">
              <el-slider v-model="c.hsv_s" :min="0" :max="1" :step="0.1" show-input :show-input-controls="false" />
            </el-form-item>
            <el-form-item label="HSV-V (亮度)">
              <el-slider v-model="c.hsv_v" :min="0" :max="1" :step="0.1" show-input :show-input-controls="false" />
            </el-form-item>
          </el-card>

          <!-- 几何增广 -->
          <el-card shadow="never" style="margin-bottom:20px">
            <template #header><span style="font-weight:600">几何增广</span></template>
            <el-form-item label="旋转角度 (°)">
              <el-slider v-model="c.degrees" :min="0" :max="180" :step="5" show-input :show-input-controls="false" />
              <span class="hint">缺陷无方向性建议 180°</span>
            </el-form-item>
            <el-form-item label="平移比例">
              <el-slider v-model="c.translate" :min="0" :max="0.9" :step="0.05" show-input :show-input-controls="false" />
            </el-form-item>
            <el-form-item label="缩放范围">
              <el-slider v-model="c.scale" :min="0" :max="2" :step="0.1" show-input :show-input-controls="false" />
            </el-form-item>
            <el-form-item label="剪切角度 (°)">
              <el-slider v-model="c.shear" :min="0" :max="45" :step="1" show-input :show-input-controls="false" />
            </el-form-item>
            <el-form-item label="上下翻转概率">
              <el-slider v-model="c.flipud" :min="0" :max="1" :step="0.1" show-input :show-input-controls="false" />
            </el-form-item>
            <el-form-item label="左右翻转概率">
              <el-slider v-model="c.fliplr" :min="0" :max="1" :step="0.1" show-input :show-input-controls="false" />
            </el-form-item>
          </el-card>

          <!-- 高级增广 -->
          <el-card shadow="never" style="margin-bottom:20px">
            <template #header>
              <span style="font-weight:600">高级增广</span>
              <span class="hint" style="margin-left:8px">对小数据集效果显著</span>
            </template>
            <el-form-item label="Mosaic">
              <el-slider v-model="c.mosaic" :min="0" :max="1" :step="0.1" show-input :show-input-controls="false" />
              <span class="hint">4图拼接，增加目标多样性</span>
            </el-form-item>
            <el-form-item label="Copy-Paste">
              <el-slider v-model="c.copy_paste" :min="0" :max="1" :step="0.1" show-input :show-input-controls="false" />
              <span class="hint">复制粘贴缺陷，对小缺陷很有效</span>
            </el-form-item>
            <el-form-item label="MixUp">
              <el-slider v-model="c.mixup" :min="0" :max="1" :step="0.05" show-input :show-input-controls="false" />
              <span class="hint">两图混合，提升泛化</span>
            </el-form-item>
            <el-form-item label="Random Erasing">
              <el-slider v-model="c.erasing" :min="0" :max="1" :step="0.1" show-input :show-input-controls="false" />
              <span class="hint">随机擦除，防过拟合</span>
            </el-form-item>
            <el-form-item label="关闭 Mosaic (最后N轮)">
              <el-input-number v-model="c.close_mosaic" :min="0" :max="100" />
              <span class="hint">最后阶段关闭 Mosaic 稳定训练</span>
            </el-form-item>
          </el-card>

          <!-- 形态学预处理 -->
          <el-card shadow="never" style="margin-bottom:20px">
            <template #header>
              <div style="display:flex;justify-content:space-between;align-items:center">
                <span style="font-weight:600">形态学预处理</span>
                <el-switch v-model="c.use_morphology" active-text="启用" inactive-text="关闭" />
              </div>
            </template>
            <template v-if="c.use_morphology">
              <el-alert type="info" :closable="false" style="margin-bottom:16px">
                <div style="font-size:12px;line-height:1.6">
                  将灰度图转为三通道输入：<b>B=原图</b> · <b>G=膨胀图</b> · <b>R=腐蚀图</b><br>
                  膨胀突出粗轮廓，腐蚀保留细节纹理，三通道组合让模型获得更丰富的特征
                </div>
              </el-alert>
              <el-form-item label="膨胀核大小">
                <el-input-number v-model="c.dilate_kernel" :min="1" :max="15" :step="2" />
                <span class="hint">奇数，越大膨胀越强</span>
              </el-form-item>
              <el-form-item label="腐蚀核大小">
                <el-input-number v-model="c.erode_kernel" :min="1" :max="15" :step="2" />
                <span class="hint">奇数，越大腐蚀越强</span>
              </el-form-item>
              <el-form-item label="标注 Mask 膨胀">
                <el-input-number v-model="c.mask_dilate_kernel" :min="0" :max="15" :step="2" />
                <span class="hint">0=不膨胀，>0 膨胀标注区域边界</span>
              </el-form-item>
            </template>
            <div v-else style="color:#909399;font-size:13px;text-align:center;padding:12px 0">
              关闭后使用原始图像直接训练（不推荐用于灰度硅片图像）
            </div>
          </el-card>
        </el-col>
      </el-row>
    </el-form>

    <!-- 预设说明 -->
    <el-alert type="info" :closable="false" style="margin-top:12px">
      <template #title>当前默认参数说明（针对硅片缺陷检测优化）</template>
      <div style="font-size:13px;line-height:1.8;margin-top:4px">
        <b>旋转 180°</b>：缺陷无固定方向，全角度旋转增强数据多样性<br>
        <b>Copy-Paste 0.5</b>：将缺陷随机粘贴到其他图上，对小目标和稀有缺陷效果显著<br>
        <b>Mosaic 0.5</b>：4 图拼接，每次训练看到更多样本<br>
        <b>过采样 ×5</b>：稀有缺陷类别复制 5 倍，平衡类别分布<br>
        <b>早停 50</b>：连续 50 轮无提升自动停止，避免过拟合浪费时间<br>
        <b>Random Erasing 0.1</b>：轻度随机擦除，防止模型过度依赖局部特征<br>
        <b>形态学三通道</b>：B=原图 G=膨胀 R=腐蚀，为灰度硅片图像提供更丰富的特征输入
      </div>
    </el-alert>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api/index'

const props = defineProps<{ id: string }>()
const router = useRouter()
const submitting = ref(false)
const savingDefaults = ref(false)
const taskName = ref('训练任务-' + new Date().toLocaleDateString('zh-CN'))

// 训练模式
const trainMode = ref<'scratch'|'finetune'>('scratch')
const resumeTaskId = ref<number|null>(null)
const resumeModelType = ref('best')
const completedTasks = ref<any[]>([])
const currentClassCount = ref(0)
const taskType = ref<'seg'|'det'|'cls'|'obb'>('seg')

// ---- 默认参数（按 task_type 分支生成）----
function getBaseDefaults() {
  return {
    model_name: 'yolo26s-seg',
    epochs: 200, batch_size: 8, patience: 50, device: '0',
    lr0: 0.01, lrf: 0.01, momentum: 0.937, weight_decay: 0.0005,
    warmup_epochs: 3, warmup_momentum: 0.8,
    train_ratio: 0.8, oversample_factor: 5,
    hsv_h: 0.015, hsv_s: 0.7, hsv_v: 0.4,
    degrees: 180, translate: 0.1, scale: 0.5, shear: 0.0,
    flipud: 0.5, fliplr: 0.5,
    mosaic: 0.5, copy_paste: 0.5, mixup: 0.1, erasing: 0.1, close_mosaic: 30,
    use_morphology: true, dilate_kernel: 3, erode_kernel: 3, mask_dilate_kernel: 0,
    crop_size: 640,
  } as Record<string, any>
}

function defaultsForTaskType(tt: string): Record<string, any> {
  const d = getBaseDefaults()
  if (tt === 'det') {
    // det 默认 small + 关形态学；几何/混合增强对 det 调保守
    Object.assign(d, { model_name: 'yolo26s.pt', use_morphology: false, train_ratio: 0.85,
      copy_paste: 0, mixup: 0, degrees: 20, flipud: 0.5, mosaic: 0.3, epochs: 300, patience: 80 })
  } else if (tt === 'cls') {
    // cls 走 ImageNet 标准 224；几何/混合增强大多关掉（工业纹理依赖方向）
    Object.assign(d, { model_name: 'yolo11s-cls.pt', use_morphology: false, train_ratio: 0.8,
      crop_size: 224, degrees: 0, flipud: 0, fliplr: 0.5, translate: 0.05, scale: 0.2, shear: 0,
      mosaic: 0, copy_paste: 0, mixup: 0, erasing: 0, epochs: 100, patience: 30 })
  } else if (tt === 'obb') {
    // OBB 受益于任意旋转
    Object.assign(d, { model_name: 'yolo11s-obb.pt', use_morphology: false, train_ratio: 0.85,
      degrees: 180, mosaic: 0.3, copy_paste: 0, mixup: 0 })
  }
  return d
}

const c = ref<Record<string, any>>(getBaseDefaults())

const classCountWarning = computed(() => {
  if (trainMode.value !== 'finetune' || !resumeTaskId.value) return ''
  const prev = completedTasks.value.find((t: any) => t.id === resumeTaskId.value)
  if (!prev || !prev.config) return ''
  const prevNc = prev.num_classes
  if (prevNc && currentClassCount.value > 0 && prevNc !== currentClassCount.value) {
    return `⚠ 当前项目有 ${currentClassCount.value} 个类别，上次训练为 ${prevNc} 个类别。类别数量不同无法继承训练，请选择"从头训练"。`
  }
  return ''
})

// ---- best vs last 推荐 ----
const recommendedModelType = ref<'best' | 'last'>('best')
const recommendReason = ref('')
function recommendModelType(task: any): { type: 'best' | 'last'; reason: string } {
  if (!task) return { type: 'best', reason: '' }
  if (task.status === 'completed') {
    return { type: 'best', reason: '训练已完成，best.pt 是最优收敛权重' }
  }
  if (task.status === 'cancelled') {
    const ep = task.current_epoch || 0
    const total = task.epochs || 0
    const progress = total > 0 ? ep / total : 0
    if (progress < 0.3) {
      return { type: 'last', reason: `训练只到 ${ep}/${total}（${(progress*100).toFixed(0)}%），best 还没充分收敛，建议 last.pt 接着学` }
    }
    return { type: 'best', reason: `已训练 ${ep}/${total}，best.pt 已稳定可用` }
  }
  return { type: 'best', reason: '' }
}

// ---- 切到继承训练 / 切换历史任务时，加载老 config + 推荐 ----
function applyResumeTask(taskId: number | null) {
  if (!taskId) return
  const task = completedTasks.value.find(t => t.id === taskId)
  if (!task) return
  const cfg = task.config ? { ...task.config } : {}
  // 不带过来的字段：当次特殊的、项目级的（项目级在项目编辑页改）
  for (const k of ['train_mode', 'resume_from_task_id', 'resume_model_type',
                   'class_names', 'task_type',
                   'resize_h', 'resize_w', 'crop_size', 'overlap']) {
    delete cfg[k]
  }
  if (Object.keys(cfg).length > 0) {
    Object.assign(c.value, cfg)
    ElMessage.info(`已加载「${task.task_name}」的训练参数`)
  }
  const rec = recommendModelType(task)
  recommendedModelType.value = rec.type
  recommendReason.value = rec.reason
  resumeModelType.value = rec.type
}

watch(resumeTaskId, (id) => {
  if (trainMode.value === 'finetune') applyResumeTask(id)
})

watch(trainMode, (m) => {
  if (m === 'finetune') {
    applyResumeTask(resumeTaskId.value)
  } else {
    recommendReason.value = ''
  }
})

onMounted(async () => {
  try {
    const { data: proj } = await api.get(`/projects/${props.id}`)
    currentClassCount.value = proj.defect_classes?.length || 0
    taskType.value = (proj.task_type || 'seg') as 'seg' | 'det' | 'cls' | 'obb'
    const defaults = defaultsForTaskType(taskType.value)
    if (proj.last_train_config && Object.keys(proj.last_train_config).length > 0) {
      // 用户点过"保存为默认"：缓存覆盖在默认之上
      Object.assign(c.value, defaults, proj.last_train_config)
      ElMessage.info('已加载上次保存的训练参数')
    } else {
      Object.assign(c.value, defaults)
    }
  } catch {}
  try {
    const { data } = await api.get(`/projects/${props.id}/train/tasks`)
    // completed + cancelled 都可继承（cancelled 任务硬盘上仍有 best.pt/last.pt）
    completedTasks.value = (data || []).filter((t: any) =>
      (t.status === 'completed' || t.status === 'cancelled') && (t.best_model_path || t.last_model_path)
    )
    if (completedTasks.value.length > 0) resumeTaskId.value = completedTasks.value[0].id
  } catch {}
})

// ---- 保存为默认 / 恢复默认 按钮 ----
async function saveAsDefault() {
  savingDefaults.value = true
  try {
    await api.put(`/projects/${props.id}/train-config-cache`, c.value)
    ElMessage.success('已保存为该项目默认参数')
  } catch {
    ElMessage.error('保存失败')
  } finally { savingDefaults.value = false }
}

async function restoreDefaults() {
  try {
    await ElMessageBox.confirm(
      '将表单恢复到该任务类型的内置默认值（不会清除已保存的项目默认）。如果想让这套默认生效，请再点「保存为默认」。',
      '恢复默认值',
      { type: 'info', confirmButtonText: '恢复', cancelButtonText: '取消' }
    )
  } catch { return }
  Object.assign(c.value, defaultsForTaskType(taskType.value))
  ElMessage.success('已恢复内置默认值')
}

async function startTrain() {
  if (trainMode.value === 'finetune' && classCountWarning.value) {
    ElMessage.error('类别数量不一致，无法继承训练')
    return
  }
  submitting.value = true
  try {
    const config: any = { ...c.value }
    config.train_mode = trainMode.value
    if (trainMode.value === 'finetune' && resumeTaskId.value) {
      config.resume_from_task_id = resumeTaskId.value
      config.resume_model_type = resumeModelType.value
    }
    await api.post(`/projects/${props.id}/train`, {
      task_name: taskName.value,
      config,
    })
    ElMessage.success('训练任务已提交！')
    router.push(`/project/${props.id}/train/monitor`)
  } catch {} finally { submitting.value = false }
}
</script>

<style scoped>
.hint { font-size: 12px; color: #909399; margin-left: 8px; }
</style>
