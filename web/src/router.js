import { createRouter, createWebHistory } from 'vue-router'
import { getKey } from './api/client.js'

import LoginView from './views/LoginView.vue'
import HomeView from './views/HomeView.vue'
import DocumentView from './views/DocumentView.vue'
import BlockView from './views/BlockView.vue'
import BlockEditView from './views/BlockEditView.vue'
import BlockDiffView from './views/BlockDiffView.vue'
import ProposalsView from './views/ProposalsView.vue'
import AcksView from './views/AcksView.vue'
import ArchiveView from './views/ArchiveView.vue'
import KeysView from './views/KeysView.vue'
import McpView from './views/McpView.vue'
import MeetingsView from './views/MeetingsView.vue'
import MeetingDetailView from './views/MeetingDetailView.vue'
import MeetingFileView from './views/MeetingFileView.vue'
import MeetingSearchView from './views/MeetingSearchView.vue'
import SeriesDetailView from './views/SeriesDetailView.vue'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: LoginView,
    meta: { public: true, title: '登录' },
  },
  { path: '/', name: 'home', component: HomeView, meta: { title: '文档树' } },
  {
    path: '/documents/:id',
    name: 'document',
    component: DocumentView,
    meta: { title: '文档' },
  },
  {
    path: '/blocks/:id',
    name: 'block',
    component: BlockView,
    meta: { title: '接口块' },
  },
  {
    path: '/blocks/:id/edit',
    name: 'block-edit',
    component: BlockEditView,
    meta: { title: '编辑接口块' },
  },
  {
    path: '/blocks/:id/diff',
    name: 'block-diff',
    component: BlockDiffView,
    meta: { title: '版本对比' },
  },
  {
    path: '/proposals',
    name: 'proposals',
    component: ProposalsView,
    meta: { title: '提案' },
  },
  { path: '/acks', name: 'acks', component: AcksView, meta: { title: '回执' } },
  {
    path: '/archive',
    name: 'archive',
    component: ArchiveView,
    meta: { title: '归档' },
  },
  { path: '/keys', name: 'keys', component: KeysView, meta: { title: '密钥管理' } },
  { path: '/mcp', name: 'mcp', component: McpView, meta: { title: 'AI 接入' } },
  {
    path: '/meetings',
    name: 'meetings',
    component: MeetingsView,
    meta: { title: '会议记录' },
  },
  {
    // 必须放在 /meetings/:id 之前，否则 "search" 会被当成会议 id 吞掉
    path: '/meetings/search',
    name: 'meeting-search',
    component: MeetingSearchView,
    meta: { title: '会议搜索' },
  },
  {
    path: '/meetings/series/:id',
    name: 'series-detail',
    component: SeriesDetailView,
    meta: { title: '业务线详情' },
  },
  {
    path: '/meetings/:id',
    name: 'meeting-detail',
    component: MeetingDetailView,
    meta: { title: '会议详情' },
  },
  {
    path: '/meetings/:id/files/:fileId',
    name: 'meeting-file',
    component: MeetingFileView,
    meta: { title: '会议文件' },
  },
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
    : 'SpecLock · 接口契约文档平台'
})
