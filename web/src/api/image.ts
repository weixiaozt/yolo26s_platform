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

  delete: (imageId: number) =>
    api.delete(`/images/${imageId}`),
}
