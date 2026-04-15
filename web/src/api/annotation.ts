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
}
