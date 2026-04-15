<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-header">
        <h1 style="color:#409EFF;margin:0">YOLO26s-Seg</h1>
        <p style="color:#909399;margin:4px 0 0">缺陷标注平台</p>
      </div>
      <el-form @submit.prevent="handleLogin" style="margin-top:24px">
        <el-form-item>
          <el-input v-model="username" prefix-icon="User" placeholder="用户名" size="large" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="password" prefix-icon="Lock" placeholder="密码" type="password" size="large" show-password @keyup.enter="handleLogin" />
        </el-form-item>
        <el-button type="primary" size="large" :loading="loading" @click="handleLogin" style="width:100%">登 录</el-button>
      </el-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api/index'

const router = useRouter()
const username = ref('')
const password = ref('')
const loading = ref(false)

async function handleLogin() {
  if (!username.value || !password.value) { ElMessage.warning('请输入用户名和密码'); return }
  loading.value = true
  try {
    const { data } = await api.post('/auth/login', { username: username.value, password: password.value })
    localStorage.setItem('token', data.token)
    localStorage.setItem('user', JSON.stringify(data.user))
    ElMessage.success(`欢迎，${data.user.display_name}`)
    router.push('/')
  } catch {} finally { loading.value = false }
}
</script>

<style scoped>
.login-page { display:flex; justify-content:center; align-items:center; min-height:100vh; background:linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
.login-card { background:#fff; border-radius:12px; padding:40px; width:380px; box-shadow:0 8px 32px rgba(0,0,0,0.2); }
.login-header { text-align:center; }
</style>
