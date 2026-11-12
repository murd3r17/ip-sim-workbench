<template>
  <el-tooltip :disabled="isAdmin" content="需要管理员权限" placement="top">
    <span class="admin-action-wrap">
      <slot :disabled="!isAdmin" :is-admin="isAdmin" />
    </span>
  </el-tooltip>
</template>

<script setup lang="ts">
import { useCurrentUser } from '../composables/useCurrentUser'

const { isAdmin } = useCurrentUser()
</script>

<style scoped>
.admin-action-wrap {
  display: inline-flex;
  vertical-align: middle;
}
</style>
