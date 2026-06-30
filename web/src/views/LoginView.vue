<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-header">
        <h1 class="brand-title">VP_vision</h1>
        <p class="brand-sub">缺陷标注平台</p>
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
.brand-title {
  margin:0;
  font-family:'Orbitron','Segoe UI',system-ui,sans-serif;
  font-size:40px;
  font-weight:800;
  letter-spacing:2px;
  line-height:1.1;
  background:linear-gradient(120deg,#22d3ee 0%,#6366f1 45%,#a855f7 100%);
  background-size:200% auto;
  -webkit-background-clip:text;
  background-clip:text;
  -webkit-text-fill-color:transparent;
  color:transparent;
  filter:drop-shadow(0 2px 6px rgba(99,102,241,.25));
  animation:logoShimmer 6s linear infinite;
}
@keyframes logoShimmer { to { background-position:200% center; } }
.brand-sub { margin:8px 0 0; color:#909399; font-size:13px; letter-spacing:6px; }
</style>
