<template>
  <main class="login-container">
    <div class="login-shell">
      <header class="login-intro">
        <h1>IP 仿真运维管理工作台</h1>
        <p>查看设备与拓扑，核对网络状态，继续实训。</p>
      </header>
      <section class="login-card" aria-labelledby="login-title">
        <h2 id="login-title">登录工作台</h2>
        <el-alert
          v-if="sessionExpired"
          type="warning"
          :closable="false"
          show-icon
          title="登录已过期。请用同一账号继续，已保存的记录和此标签页的临时草稿可在原页面查看。"
          style="margin-bottom: 12px"
        />
        <el-alert v-else-if="route.query.password_changed === '1'" title="密码已修改，请使用新密码登录。" type="success" :closable="false" />
        <el-alert v-else-if="route.query.unavailable === '1'" title="无法核对登录状态。请确认工作台已启动，再登录。" type="error" :closable="false" />
        <el-form :model="form" label-position="top" size="large" @submit.prevent="handleLogin">
          <el-form-item label="用户名">
            <el-input v-model="form.username" name="username" autocomplete="username" placeholder="用户名" :prefix-icon="UserIcon" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="form.password" name="password" autocomplete="current-password" type="password" placeholder="密码" :prefix-icon="LockIcon" show-password />
          </el-form-item>
          <el-button class="login-submit" type="primary" native-type="submit" :loading="loading">登录</el-button>
        </el-form>
        <p class="login-help">首次使用请向工作台管理员领取账号。忘记密码时，管理员可在「账号管理」重置普通账号。</p>
      </section>
    </div>
  </main>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus/es/components/message/index'
import { User as UserIcon, Lock as LockIcon } from '@element-plus/icons-vue'
import { login } from '../api/auth'
import { loginRedirectTarget } from '../utils/session'
import { acceptBrowserSession, publishSessionChange } from '../stores/browserSession'

const route = useRoute()
const loading = ref(false)
const form = ref({ username: '', password: '' })
// 被 401 拦截器整页刷回来时带上 expired=1，这里给出原因，避免"莫名其妙被踢"
const sessionExpired = ref(String(route.query.expired || '') === '1')

const handleLogin = async () => {
  if (loading.value) return
  if (!form.value.username || !form.value.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const data = await login(form.value)
    acceptBrowserSession(data)
    publishSessionChange()
    form.value.password = ''
    ElMessage.success('登录成功')
    window.location.replace(loginRedirectTarget(route.query.redirect))
  } catch (error) {
    if (error instanceof Error && error.message.startsWith('登录响应不完整')) ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-help { margin: 14px 0 0; color: var(--v7b-muted); font-size: 13px; line-height: 1.55; }
.login-container {
  height: 100dvh;
  overflow: auto;
  display: grid;
  place-items: center;
  padding: clamp(16px, 4vw, 72px);
  background: radial-gradient(ellipse at 20% 0%, #213a54, #101924 75%);
}
.login-shell {
  width: min(100%, clamp(900px, 72vw, 1720px));
  min-height: clamp(460px, 54dvh, 640px);
  display: grid;
  grid-template-columns: minmax(0, 1.16fr) minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid #465c73;
  border-radius: 16px;
  box-shadow: 0 20px 65px rgba(0, 0, 0, .28);
}
.login-intro,
.login-card {
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: clamp(28px, 4vw, 76px);
}
.login-intro {
  background: linear-gradient(145deg, #2e4a65, #20364d 74%);
  color: #f5f8fc;
}
.login-intro h1 {
  max-width: 12em;
  margin: 0;
  font-size: clamp(28px, 2.5vw, 52px);
  line-height: 1.25;
}
.login-intro p {
  margin: 18px 0 0;
  color: #d5e4f3;
  font-size: clamp(14px, 1.05vw, 21px);
  line-height: 1.65;
}
.login-card {
  background: var(--v7b-surface);
}
.login-card h2 {
  margin: 0 0 26px;
  color: var(--v7b-text);
  font-size: clamp(23px, 1.65vw, 34px);
}
.login-submit { width: 100%; }

@media (max-width: 760px) {
  .login-shell {
    width: min(100%, 500px);
    min-height: 0;
    grid-template-columns: minmax(0, 1fr);
  }
  .login-intro,
  .login-card { padding: clamp(20px, 6vw, 34px); }
  .login-intro h1 { font-size: clamp(22px, 5vw, 30px); }
  .login-intro p { margin-top: 8px; }
  .login-card h2 { margin-bottom: 18px; }
}
</style>
