<script setup>
// 占位视图：标题 + 「建设中」。后续页面开发者替换本文件的模板与逻辑即可。
defineProps({
  title: { type: String, required: true },
  eyebrow: { type: String, default: '' },
})
</script>

<template>
  <div class="page">
    <p v-if="eyebrow" class="page-eyebrow">{{ eyebrow }}</p>
    <h1 class="page-title">{{ title }}</h1>
    <p class="page-desc">建设中</p>
  </div>
</template>
