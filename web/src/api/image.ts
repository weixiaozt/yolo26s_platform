import api from './index'

export interface ImageInfo {
  id: number
  project_id: number
  filename: string
  source_relative_path?: string | null
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

export interface ImageUploadResponse {
  items: ImageInfo[]
  uploaded: number
  auto_labeled: number
  renamed: Array<{ original: string; new: string }>
  unknown_folders: string[]
  matched_classes: Record<string, number>
}

export interface FolderLabelResponse {
  updated: number
  skipped: number
  unknown_folders: string[]
  matched_classes: Record<string, number>
}

export const imageApi = {
  list: (projectId: number, params?: { page?: number; page_size?: number; status?: string; class_id?: number; class_ids?: string }) =>
    api.get<ImageListResponse>(`/projects/${projectId}/images`, { params }),

  upload: (projectId: number, files: File[], onProgress?: (pct: number) => void, autoLabelByFolder = false) => {
    const formData = new FormData()
    formData.append('auto_label_by_folder', String(autoLabelByFolder))
    files.forEach((f) => {
      const rel = (f as any).webkitRelativePath || f.name
      formData.append('files', f, rel)
    })
    return api.post<ImageUploadResponse>(`/projects/${projectId}/images/upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000, // 5 分钟，大文件上传
      onUploadProgress: (e) => {
        if (onProgress && e.total) {
          onProgress(Math.round((e.loaded * 100) / e.total))
        }
      },
    })
  },

  getFileUrl: (imageId: number, thumb = false) => {
    // 图片经 <img src> 加载，浏览器不带 Authorization 头，鉴权用 ?token= 传（后端中间件已支持）
    const t = localStorage.getItem('token') || ''
    return `/api/images/${imageId}/file?token=${t}${thumb ? '&thumb=true' : ''}`
  },

  updateStatus: (imageId: number, status: string, annotator?: string) =>
    api.put(`/images/${imageId}/status`, { status, annotator }),

  /** 批量给图片打分类标签（cls 项目专用） */
  batchSetClass: (projectId: number, imageIds: number[], classId: number | null, annotator?: string) =>
    api.put(`/projects/${projectId}/images/batch-class`, {
      image_ids: imageIds,
      class_id: classId,
      annotator,
    }),

  /** cls 项目：项目级类别计数（每类多少张 + 未分类数 + 总数） */
  getClassStats: (projectId: number) =>
    api.get<{ by_class: Record<string, number>; unlabeled: number; total: number }>(
      `/projects/${projectId}/images/class-stats`,
    ),

  labelByFolder: (projectId: number, onlyUnlabeled = true) =>
    api.post<FolderLabelResponse>(`/projects/${projectId}/images/label-by-folder`, {
      only_unlabeled: onlyUnlabeled,
    }),

  delete: (imageId: number) =>
    api.delete(`/images/${imageId}`),

  /** 批量删除图像（标注与磁盘文件一并删除） */
  batchDelete: (imageIds: number[]) =>
    api.post<{ ok: boolean; deleted: number }>(`/images/batch-delete`, { image_ids: imageIds }),
}
