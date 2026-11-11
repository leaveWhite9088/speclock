<script setup>
// 库里有多个项目、地址又没指明看哪个：先选一个。网页一次只看一个项目，选了以后用的是绑定该项目的 key。
import { onMounted, ref } from 'vue'
import { embedded } from '../embed.js'

const projects = ref([])
const error = ref('')

onMounted(async () => {
  if (embedded) return // 嵌进别的页面时不列项目：外层页面必须自己指明（data-project）
  try {
    const res = await fetch('/api/v1/web/projects')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    projects.value = await res.json()
  } catch (e) {
    error.value = `读不到项目列表：${e.message}`
  }
})
</script>

<template>
  <main class="page picker-page">
    <p class="page-eyebrow">SpecLock</p>
    <h1 class="page-title">选择项目</h1>
    <template v-if="embedded">
      <p class="page-desc">
        这个库里有多个项目，嵌入时要指明看哪一个：<code>&lt;div data-speclock="overview" data-project="项目 id"&gt;</code>
        （或地址加 <code>?project=项目 id</code>）。每个项目的网页只看得到它自己的内容。
      </p>
    </template>
    <template v-else>
      <p class="page-desc">
        这个库里有多个项目。网页一次只看一个项目，看不到其他项目的内容。
      </p>
      <p v-if="error" class="error-text">{{ error }}</p>
      <ul class="picker-list">
        <li v-for="p in projects" :key="p.id">
          <a :href="`/?project=${p.id}`" class="btn">{{ p.name }}</a>
          <span class="muted mono"> #{{ p.id }}</span>
        </li>
      </ul>
    </template>
  </main>
</template>
