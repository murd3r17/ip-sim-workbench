<template>
  <div class="login-container">
    <div class="login-card">
      <h1>IP仿真运维管理工作台</h1>
      <el-alert
        v-if="sessionExpired"
        type="warning"
        :closable="false"
        show-icon
        title="登录已过期，请重新登录（未保存的输入已丢失）"
        style="margin-bottom: 12px"
      />
      <el-form :model="form" @submit.prevent="handleLogin">
        <el-form-item>
          <el-input v-model="form.username" placeholder="用户名" :prefix-icon="UserIcon" @keyup.enter="handleLogin" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" placeholder="密码" :prefix-icon="LockIcon" show-password @keyup.enter="handleLogin" />
        </el-form-item>
        <el-form-item>
          <!-- native-type=submit：不然表单里没有提交按钮，输完口令敲回车毫无反应 -->
          <el-button type="primary" native-type="submit" :loading="loading" @click="handleLogin" style="width: 100%">登录</el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus/es/components/message/index'
import { User as UserIcon, Lock as LockIcon } from '@element-plus/icons-vue'
import { login } from '../api/auth'
import { loginRedirectTarget } from '../utils/session'

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const form = ref({ username: '', password: '' })
// 被 401 拦截器整页刷回来时带上 expired=1，这里给出原因，避免"莫名其妙被踢"
const sessionExpired = ref(String(route.query.expired || '') === '1')

const handleLogin = async () => {
  if (!form.value.username || !form.value.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const data: any = await login(form.value)
    // 校验字段再写：后端契约变化时若写入字符串 "undefined"（truthy），
    // 路由守卫会放行，随后所有请求 401 循环跳回登录页
    const token = typeof data?.access_token === 'string' ? data.access_token.trim() : ''
    if (!token) {
      ElMessage.error('登录响应缺少 access_token，请联系管理员检查后端版本')
      return
    }
    localStorage.setItem('token', token)
    localStorage.setItem('user', JSON.stringify(data.user ?? {}))
    ElMessage.success('登录成功')
    router.push(loginRedirectTarget(route.query.redirect))
  } catch {
    // 错误已在拦截器处理
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
/* 与全局暗色主题一致（P2-23）：此前是白底卡片 + 亮紫渐变 + #333 标题，
   和 App.vue 的 --el-* 暗色变量冲突，输入框在卡片上"半亮半暗"。 */
.login-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: radial-gradient(circle at 50% 0%, #16273a 0%, #0b1118 60%);
}
.login-card {
  width: 400px;
  padding: 40px;
  background: var(--el-bg-color-overlay, #101922);
  border: 1px solid var(--el-border-color, #273444);
  border-radius: 12px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.55);
}
.login-card h1 {
  text-align: center;
  margin-bottom: 30px;
  color: var(--el-text-color-primary, #dce8f2);
  font-size: 20px;
}
</style>
