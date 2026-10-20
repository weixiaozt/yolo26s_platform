import { ref, watch } from 'vue'

const key = 'annotation-preferences-v1'
let saved: Record<string, unknown> = {}
try {
  saved = JSON.parse(localStorage.getItem(key) || '{}') || {}
} catch { /* 浏览器禁止存储或旧值损坏时使用默认值 */ }

// 显示开关仅在本次页面会话内共享；刷新浏览器时恢复默认值。
const showAnnotations = ref(true)
const showClassNames = ref(false)
const showConfidence = ref(false)
const inferConfidence = ref(
  typeof saved.inferConfidence === 'number' && Number.isFinite(saved.inferConfidence)
    && saved.inferConfidence >= 0 && saved.inferConfidence <= 1
    ? saved.inferConfidence : 0.35,
)

watch(inferConfidence, () => {
  try {
    localStorage.setItem(key, JSON.stringify({
      inferConfidence: inferConfidence.value,
    }))
  } catch { /* 不因浏览器存储限制阻断标注 */ }
})

// 所有项目共享当前选项；只保存推理阈值，显示开关不跨刷新恢复。
export function useAnnotationPreferences() {
  return { showAnnotations, showClassNames, showConfidence, inferConfidence }
}
