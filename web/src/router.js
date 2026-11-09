import { createRouter, createWebHistory } from 'vue-router'
import { getKey } from './api/client.js'

import LoginView from './views/LoginView.vue'
import OverviewView from './views/OverviewView.vue'
import HomeView from './views/HomeView.vue'
import CapabilityView from './views/CapabilityView.vue'
import BlockView from './views/BlockView.vue'
import BlockDiffView from './views/BlockDiffView.vue'
import CRListView from './views/CRListView.vue'
import CRDetailView from './views/CRDetailView.vue'
import WorkView from './views/WorkView.vue'
import ArchiveView from './views/ArchiveView.vue'
import McpView from './views/McpView.vue'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: LoginView,
    meta: { public: true, title: '登录' },
  },
  { path: '/', name: 'home', component: OverviewView, meta: { title: '总览' } },
  { path: '/tree', name: 'tree', component: HomeView, meta: { title: '文档树' } },
  {
    path: '/capabilities/:id',
    name: 'capability',
    component: CapabilityView,
    meta: { title: '小业务' },
  },
  {
    path: '/blocks/:id',
    name: 'block',
    component: BlockView,
    meta: { title: '模块' },
  },
  {
    path: '/blocks/:id/diff',
    name: 'block-diff',
    component: BlockDiffView,
    meta: { title: '版本对比' },
  },
  {
    path: '/change-requests',
    name: 'change-requests',
    component: CRListView,
    meta: { title: '审核单' },
  },
  {
    path: '/change-requests/:id',
    name: 'change-request',
    component: CRDetailView,
    meta: { title: '审核单详情' },
  },
  { path: '/work', name: 'work', component: WorkView, meta: { title: '待办' } },
  {
    path: '/archive',
    name: 'archive',
    component: ArchiveView,
    meta: { title: '归档' },
  },
  { path: '/mcp', name: 'mcp', component: McpView, meta: { title: 'AI 接入' } },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  linkActiveClass: 'is-active',
  linkExactActiveClass: 'is-exact',
})

router.beforeEach((to) => {
  if (to.meta.public) {
    // 已登录时访问登录页，直接回工作台
    if (getKey()) return { name: 'home' }
    return true
  }
  if (!getKey()) {
    return { name: 'login', query: to.fullPath !== '/' ? { from: to.fullPath } : {} }
  }
  return true
})

router.afterEach((to) => {
  document.title = to.meta.title
    ? `${to.meta.title} · SpecLock`
    : 'SpecLock · 需求规格'
})
