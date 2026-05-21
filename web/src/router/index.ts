import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('../views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      name: 'ProjectList',
      component: () => import('../views/ProjectList.vue'),
    },
    {
      path: '/import',
      name: 'ImportProject',
      component: () => import('../views/ImportProject.vue'),
    },
    {
      path: '/annotation-convert',
      name: 'AnnotationConvert',
      component: () => import('../views/AnnotationConvert.vue'),
    },
    {
      path: '/users',
      name: 'UserManage',
      component: () => import('../views/UserManage.vue'),
      meta: { adminOnly: true },
    },
    {
      path: '/project/:id',
      name: 'ProjectDetail',
      component: () => import('../views/ProjectDetail.vue'),
      props: true,
    },
    {
      path: '/annotate/:projectId/:imageId',
      name: 'Annotator',
      component: () => import('../views/Annotator.vue'),
      props: true,
    },
    {
      path: '/cls-annotate/:projectId',
      name: 'ClsAnnotator',
      component: () => import('../views/ClsAnnotator.vue'),
      props: true,
    },
    {
      path: '/project/:id/train',
      name: 'TrainConfig',
      component: () => import('../views/TrainConfig.vue'),
      props: true,
    },
    {
      path: '/project/:id/train/monitor',
      name: 'TrainMonitor',
      component: () => import('../views/TrainMonitor.vue'),
      props: true,
    },
    {
      path: '/project/:id/inference',
      name: 'Inference',
      component: () => import('../views/InferenceView.vue'),
      props: true,
    },
    {
      path: '/project/:id/export',
      name: 'ModelExport',
      component: () => import('../views/ModelExport.vue'),
      props: true,
    },
  ],
})

function readStoredUser(): { role?: string } {
  // localStorage 可能被旧版本/手动篡改写入非 JSON，必须容错，
  // 否则 admin 路由守卫会抛异常导致整个导航卡死
  try {
    return JSON.parse(localStorage.getItem('user') || '{}')
  } catch {
    localStorage.removeItem('user')
    return {}
  }
}

// 路由守卫：未登录跳转登录页
router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  if (to.meta.public) {
    // 登录页：已登录则跳首页
    if (token) next('/')
    else next()
  } else if (!token) {
    next('/login')
  } else if (to.meta.adminOnly) {
    const user = readStoredUser()
    if (user.role === 'admin') next()
    else next('/')
  } else {
    next()
  }
})

export default router
