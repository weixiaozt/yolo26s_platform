import api from './index'

export interface ImageInfo {
  id: number
  project_id: number
  filename: string
  width: number
  height: number
  file_size: number
  status: 'unlabeled' | 'labeling' | 'labeled' | 'reviewed'
  annotator: string | null
  reviewer: string | null
  created_at: string
  annotation_count: number
  class_id?: number | null  // cls 项目专用：图级分类的类别 id
}

export interface ImageListResponse {
  total: number
  page: number
  page_size: number
  items: ImageInfo[]
}

export const imageApi = {
  list: (projectId: number, params?: { page?: number; page_size?: number; status?: string }) =>
    api.get<ImageListResponse>(`/projects/${projectId}/images`, { params }),

  upload: (projectId: number, files: File[], onProgress?: (pct: number) => void) => {
    const formData = new FormData()
    files.forEach((f) => formData.append('files', f))
    return api.post<ImageInfo[]>(`/projects/${projectId}/images/upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000, // 5 分钟，大文件上传
      onUploadProgress: (e) => {
        if (onProgress && e.total) {
          onProgress(Math.round((e.loaded * 100) / e.total))
        }
      },
    })
  },

  getFileUrl: (imageId: number, thumb = false) =>
    `/api/images/${imageId}/file${thumb ? '?thumb=true' : ''}`,

  updateStatus: (imageId: number, status: string, annotator?: string) =>
    api.put(`/images/${imageId}/status`, { status, annotator }),

  /** 批量给图片打分类标签（cls 项目专用） */
  batchSetClass: (projectId: number, imageIds: number[], classId: number | null, annotator?: string) =>
    api.put(`/projects/${projectId}/images/batch-class`, {
      image_ids: imageIds,
      class_id: classId,
      annotator,
    }),

  delete: (imageId: number) =>
    api.delete(`/images/${imageId}`),
}
