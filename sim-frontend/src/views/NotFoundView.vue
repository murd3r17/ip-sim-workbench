<template>
  <div class="not-found">
    <el-result icon="warning" title="页面不存在" :sub-title="`没有找到路径 ${path}`">
      <template #extra>
        <el-button type="primary" @click="router.push('/dashboard')">返回运维总览</el-button>
      </template>
    </el-result>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElResult } from 'element-plus/es/components/result/index'
import 'element-plus/es/components/result/style/css'

const route = useRoute()
const router = useRouter()
const path = computed(() => route.fullPath)
</script>

<style scoped>
.not-found {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 48px 16px;
}
</style>
