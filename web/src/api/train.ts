import api from './index'

export interface TrainTask {
  id: number
  project_id: number
  task_name: string
  status: string
  epochs: number
  current_epoch: number
  best_map50: number | null
  best_model_path: string | null
  output_dir: string | null
  error_message: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  config?: Record<string, any> | null   // 训练时使用的完整参数（model_name/epochs/lr0/...）
}

export interface EpochLog {
  epoch: number
  train_box_loss: number | null
  train_seg_loss: number | null
  train_cls_loss: number | null
  train_dfl_loss: number | null
  val_box_loss: number | null
  val_seg_loss: number | null
  val_cls_loss: number | null
  val_dfl_loss: number | null
  precision_b: number | null
  recall_b: number | null
  map50_b: number | null
  map50_95_b: number | null
  map50_m: number | null
  map50_95_m: number | null
  lr: number | null
}

export const trainApi = {
  listTasks: (projectId: number) =>
    api.get<TrainTask[]>(`/projects/${projectId}/train/tasks`),

  getTask: (taskId: number) =>
    api.get<TrainTask>(`/train/tasks/${taskId}`),

  getEpochLogs: (taskId: number) =>
    api.get<EpochLog[]>(`/train/tasks/${taskId}/epochs`),

  cancelTask: (taskId: number) =>
    api.post(`/train/tasks/${taskId}/cancel`),

  deleteTask: (taskId: number) =>
    api.delete(`/train/tasks/${taskId}`),
}
