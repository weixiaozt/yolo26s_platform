<template>
  <div class="page-container" style="max-width:900px">
    <div class="page-header">
      <h1>用户管理</h1>
      <el-button type="primary" @click="showAdd = true"><el-icon><Plus /></el-icon> 添加用户</el-button>
    </div>

    <el-table :data="users" stripe style="width:100%">
      <el-table-column prop="id" label="ID" width="55" />
      <el-table-column prop="username" label="用户名" width="120" />
      <el-table-column prop="display_name" label="显示名" width="120" />
      <el-table-column label="角色" width="100">
        <template #default="{row}">
          <el-tag :type="row.role==='admin'?'danger':''" size="small">{{ row.role==='admin'?'管理员':'普通用户' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{row}">
          <el-tag :type="row.is_active?'success':'info'" size="small">{{ row.is_active?'启用':'禁用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="160">
        <template #default="{row}">{{ row.created_at?.replace('T',' ').slice(0,16) }}</template>
      </el-table-column>
      <el-table-column label="操作" min-width="200">
        <template #default="{row}">
          <el-button text size="small" @click="toggleActive(row)">{{ row.is_active?'禁用':'启用' }}</el-button>
          <el-button text size="small" @click="toggleRole(row)">{{ row.role==='admin'?'设为普通':'设为管理员' }}</el-button>
          <el-button text size="small" type="warning" @click="resetPwd(row.id)">重置密码</el-button>
          <el-button text size="small" type="danger" @click="deleteUser(row.id)" :disabled="row.role==='admin'">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 添加用户 -->
    <el-dialog v-model="showAdd" title="添加用户" width="420px">
      <el-form label-width="80px">
        <el-form-item label="用户名"><el-input v-model="newUser.username" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="newUser.password" type="password" show-password /></el-form-item>
        <el-form-item label="显示名"><el-input v-model="newUser.display_name" /></el-form-item>
        <el-form-item label="角色">
          <el-radio-group v-model="newUser.role">
            <el-radio label="user">普通用户</el-radio>
            <el-radio label="admin">管理员</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAdd = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="addUser">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api/index'

interface UserInfo { id:number; username:string; display_name:string; role:string; is_active:boolean; created_at:string }
const users = ref<UserInfo[]>([])
const showAdd = ref(false)
const creating = ref(false)
const newUser = ref({ username:'', password:'123456', display_name:'', role:'user' })

onMounted(loadUsers)

async function loadUsers() {
  const { data } = await api.get('/auth/users')
  users.value = data
}

async function addUser() {
  if (!newUser.value.username) { ElMessage.warning('请输入用户名'); return }
  creating.value = true
  try {
    await api.post('/auth/users', newUser.value)
    ElMessage.success('用户已创建')
    showAdd.value = false
    newUser.value = { username:'', password:'123456', display_name:'', role:'user' }
    await loadUsers()
  } catch {} finally { creating.value = false }
}

async function toggleActive(row: UserInfo) {
  await api.put(`/auth/users/${row.id}`, { is_active: !row.is_active })
  await loadUsers()
}

async function toggleRole(row: UserInfo) {
  const newRole = row.role === 'admin' ? 'user' : 'admin'
  await api.put(`/auth/users/${row.id}`, { role: newRole })
  await loadUsers()
}

async function resetPwd(userId: number) {
  try { await ElMessageBox.confirm('将为该用户生成一次性随机密码，请立即转告本人并提醒首次登录后修改。', '重置密码', { type:'warning' }) } catch { return }
  const resp = await api.put<{ password: string }>(`/auth/users/${userId}/reset-password`)
  const newPwd = resp.data?.password || ''
  if (newPwd) {
    await ElMessageBox.alert(`新密码：${newPwd}\n\n（此密码仅显示一次，请截图或复制后转告用户）`, '重置成功', { confirmButtonText: '我已记录' })
  } else {
    ElMessage.success('密码已重置')
  }
}

async function deleteUser(userId: number) {
  try { await ElMessageBox.confirm('确定删除该用户？', '删除', { type:'warning' }) } catch { return }
  try {
    await api.delete(`/auth/users/${userId}`)
    ElMessage.success('用户已删除')
    await loadUsers()
  } catch {}
}
</script>
