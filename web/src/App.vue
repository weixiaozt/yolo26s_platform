<template>
  <el-container class="app-container">
    <!-- 侧边栏（登录页和标注页不显示） -->
    <el-aside v-if="showSidebar" width="220px" class="app-aside">
      <div class="logo">
        <h2>YOLO26s-Seg</h2>
        <span>缺陷标注平台</span>
      </div>
      <el-menu
        :default-active="currentRoute"
        router
        class="side-menu"
        background-color="#1d1e1f"
        text-color="#bbb"
        active-text-color="#409EFF"
      >
        <el-menu-item index="/">
          <el-icon><Folder /></el-icon>
          <span>项目管理</span>
        </el-menu-item>
        <el-menu-item index="/annotation-convert">
          <el-icon><MagicStick /></el-icon>
          <span>标注转换</span>
        </el-menu-item>
        <el-menu-item v-if="isAdmin" index="/users">
          <el-icon><User /></el-icon>
          <span>用户管理</span>
        </el-menu-item>
      </el-menu>

      <!-- 底部用户信息 -->
      <div class="user-panel" v-if="currentUser">
        <div class="user-info">
          <div class="user-name">{{ currentUser.display_name || currentUser.username }}</div>
          <el-tag size="small" :type="currentUser.role==='admin'?'danger':''">{{ currentUser.role==='admin'?'管理员':'用户' }}</el-tag>
        </div>
        <div class="user-actions">
          <el-button text size="small" @click="showChangePwd = true" style="color:#aaa">修改密码</el-button>
          <el-button text size="small" @click="logout" style="color:#F56C6C">退出</el-button>
        </div>
      </div>
    </el-aside>

    <!-- 主内容区 -->
    <el-main class="app-main" :class="{ 'full-width': !showSidebar }">
      <router-view />
    </el-main>

    <!-- 修改密码 -->
    <el-dialog v-model="showChangePwd" title="修改密码" width="380px">
      <el-form label-width="80px">
        <el-form-item label="原密码"><el-input v-model="pwdForm.old" type="password" show-password /></el-form-item>
        <el-form-item label="新密码"><el-input v-model="pwdForm.new" type="password" show-password /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showChangePwd = false">取消</el-button>
        <el-button type="primary" @click="changePassword">确定</el-button>
      </template>
    </el-dialog>
  </el-container>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from './api/index'

const route = useRoute()
const router = useRouter()
const currentRoute = computed(() => route.path)
const showSidebar = computed(() => route.name !== 'Annotator' && route.name !== 'Login' && route.name !== 'Inference')

const currentUser = computed(() => {
  try { return JSON.parse(localStorage.getItem('user') || 'null') } catch { return null }
})
const isAdmin = computed(() => currentUser.value?.role === 'admin')

function logout() {
  localStorage.removeItem('token')
  localStorage.removeItem('user')
  router.push('/login')
}

const showChangePwd = ref(false)
const pwdForm = ref({ old: '', new: '' })
async function changePassword() {
  if (!pwdForm.value.old || !pwdForm.value.new) { ElMessage.warning('请输入密码'); return }
  if (pwdForm.value.new.length < 4) { ElMessage.warning('密码至少 4 位'); return }
  try {
    await api.put('/auth/me/password', { old_password: pwdForm.value.old, new_password: pwdForm.value.new })
    ElMessage.success('密码已修改')
    showChangePwd.value = false
    pwdForm.value = { old: '', new: '' }
  } catch {}
}
</script>

<style scoped>
.app-container { height:100vh; }
.app-aside { background:#1d1e1f; border-right:1px solid #333; overflow-y:auto; display:flex; flex-direction:column; }
.logo { padding:20px 16px; text-align:center; border-bottom:1px solid #333; }
.logo h2 { color:#409EFF; font-size:18px; margin:0; }
.logo span { color:#888; font-size:12px; }
.side-menu { border-right:none; flex:1; }
.user-panel { padding:12px 16px; border-top:1px solid #333; }
.user-info { display:flex; align-items:center; justify-content:space-between; margin-bottom:6px; }
.user-name { color:#ddd; font-size:13px; font-weight:500; }
.user-actions { display:flex; gap:4px; }
.app-main { padding:0; background:#f5f7fa; overflow-y:auto; }
.app-main.full-width { padding:0; }
</style>
