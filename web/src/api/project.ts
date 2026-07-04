import api from './index'

export interface DefectClass {
  id?: number
  class_index: number
  name: string
  color: string
}

export interface Project {
  id: number
  name: string
  description: string | null
  task_type: 'seg' | 'det' | 'cls' | 'obb'
  resize_h: number
  resize_w: number
  crop_size: number
  overlap: number
  status: string
  created_at: string
  updated_at: string
  defect_classes: DefectClass[]
}

export interface ProjectStats extends Project {
  total_images: number
  unlabeled_count: number
  labeling_count: number
  labeled_count: number
  reviewed_count: number
  total_annotations: number
}

export interface ProjectCreate {
  name: string
  description?: string
  task_type?: 'seg' | 'det' | 'cls' | 'obb'
  resize_h?: number
  resize_w?: number
  crop_size?: number
  overlap?: number
  class_names?: DefectClass[]
}

export interface MergeReport {
  task_type: string
  pack_images: number
  pack_annotations: number
  matched_images: number
  new_images: number
  added_annotations: number
  skipped_duplicates: number
  new_classes: string[]
  cls_conflicts: { filename: string; target_class: string; incoming_class: string }[]
  unmatched_no_image: number
  dry_run: boolean
}

type DownloadProgressHandler = (percent: number) => void

function downloadProgressConfig(onProgress?: DownloadProgressHandler) {
  return {
    responseType: 'blob' as const,
    timeout: 600000,
    onDownloadProgress: (evt: any) => {
      if (!onProgress) return
      if (evt.total) {
        onProgress(Math.min(99, Math.round((evt.loaded / evt.total) * 100)))
      } else if (evt.loaded > 0) {
        onProgress(8)
      }
    },
  }
}

export const projectApi = {
  list: () =>
    api.get<Project[]>('/projects'),

  get: (id: number) =>
    api.get<ProjectStats>(`/projects/${id}`),

  create: (data: ProjectCreate) =>
    api.post<Project>('/projects', data),

  update: (id: number, data: Partial<ProjectCreate>) =>
    api.put<Project>(`/projects/${id}`, data),

  delete: (id: number) =>
    api.delete(`/projects/${id}`),

  addClass: (projectId: number, data: DefectClass) =>
    api.post(`/projects/${projectId}/classes`, data),

  updateClass: (projectId: number, classId: number, data: DefectClass) =>
    api.put(`/projects/${projectId}/classes/${classId}`, data),

  deleteClass: (projectId: number, classId: number) =>
    api.delete(`/projects/${projectId}/classes/${classId}`),

  exportPackage: (id: number, onProgress?: DownloadProgressHandler) =>
    api.get(`/projects/${id}/export-package`, downloadProgressConfig(onProgress)),

  exportFullPackage: (id: number, onProgress?: DownloadProgressHandler) =>
    api.get(`/projects/${id}/export-full-package`, downloadProgressConfig(onProgress)),

  importPackage: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post<{ project_id: number; project_name: string; renamed: boolean; image_count: number; annotation_count: number }>(
      '/projects/import-package',
      fd,
      { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 600000 }
    )
  },

  importFullPackage: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post<{
      project_id: number
      project_name: string
      renamed: boolean
      image_count: number
      annotation_count: number
      train_task_count: number
      epoch_log_count: number
      weight_file_count: number
    }>(
      '/projects/import-full-package',
      fd,
      { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 600000 }
    )
  },

  mergePackage: (projectId: number, file: File, dryRun: boolean) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post<MergeReport>(
      `/projects/${projectId}/merge-package?dry_run=${dryRun}`,
      fd,
      { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 600000 }
    )
  },
}
