<script setup>
// 相对时间（「5 分钟前」），悬停显示完整时间；每 30 秒自己更新一次。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { fmtAgo, fmtTime, parseTs } from '../time.js'

const props = defineProps({ value: { type: String, default: '' } })

const now = ref(Date.now())
let timer = null
onMounted(() => {
  timer = setInterval(() => (now.value = Date.now()), 30000)
})
onBeforeUnmount(() => timer && clearInterval(timer))

const text = computed(() => fmtAgo(props.value, now.value))
const full = computed(() => fmtTime(props.value))
const iso = computed(() => parseTs(props.value)?.toISOString() || '')
</script>

<template>
  <time class="time-ago" :datetime="iso" :title="full">{{ text }}</time>
</template>

<style scoped>
.time-ago {
  white-space: nowrap;
}
</style>
