import api from './index'

export interface Point {
  x: number
  y: number
}

export interface AnnotationData {
  id?: number
  image_id?: number
  class_id: number
  polygon: Point[]
  area?: number
  bbox?: { x1: number; y1: number; x2: number; y2: number }
  created_by?: string
  class_name?: string
  class_color?: string
}

export interface AnnotationOut extends AnnotationData {
  id: number
  image_id: number
  created_at: string
  updated_at: string
}

export const annotationApi = {
  /** 获取某张图的全部标注 */
  get: (imageId: number) =>
    api.get<AnnotationOut[]>(`/images/${imageId}/annotations`),

  /** 全量覆盖保存标注 */
  save: (imageId: number, annotations: AnnotationData[], annotator?: string) =>
    api.post<AnnotationOut[]>(`/images/${imageId}/annotations`, {
      annotations,
      annotator,
    }),

  /** 删除单个标注 */
  delete: (annotationId: number) =>
    api.delete(`/annotations/${annotationId}`),

  listInferenceModels: (projectId: number) =>
    api.get<InferenceModelInfo[]>('/inference/models', { params: { project_id: projectId } }),

  inferCurrent: (payload: {
    image_id: number
    project_id: number
    task_id?: number
    model_path?: string
  }) =>
    api.post<InferAnnotationResult>('/inference/annotation-current', payload),

  inferClassBatch: (payload: {
    project_id: number
    image_ids: number[]
    task_id?: number
    model_path?: string
    only_unlabeled?: boolean
    annotator?: string
  }) =>
    api.post<InferClassBatchResult>('/inference/annotation-cls-batch', payload),
}

export interface InferenceModelInfo {
  task_id: number
  model_format: string
  label: string
  model_path: string
}

export interface InferAnnotationResult {
  image_id: number
  task_type: string
  count: number
  skipped: number
  annotations: AnnotationData[]
}

export interface InferClassBatchResult {
  updated: number
  skipped_existing: number
  skipped_unmatched: number
  failed: number
  items: Array<{
    image_id: number
    filename: string
    class_id?: number
    class_name?: string
    confidence?: number
    matched: boolean
    pred_name?: string
  }>
}
