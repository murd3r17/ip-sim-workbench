import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { ElAlert } from 'element-plus/es/components/alert/index'
import { ElButton } from 'element-plus/es/components/button/index'
import { ElForm, ElFormItem } from 'element-plus/es/components/form/index'
import { ElInput } from 'element-plus/es/components/input/index'
import 'element-plus/es/components/alert/style/css'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/config-provider/style/css'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/form-item/style/css'
import 'element-plus/es/components/input/style/css'
import 'element-plus/es/components/message/style/css'
import './styles/v7b.css'
import App from './App.vue'
import router from './router'
import { retireLegacyLoginStorage } from './utils/session'

retireLegacyLoginStorage()
const app = createApp(App)
for (const component of [ElAlert, ElButton, ElForm, ElFormItem, ElInput]) {
  app.component(component.name!, component)
}

let workbenchControls: Promise<void> | undefined
router.beforeResolve(async to => {
  if (to.path === '/login') return
  workbenchControls ??= import('./workbenchControls').then(module => {
    module.registerWorkbenchControls(app)
  }).catch(error => {
    workbenchControls = undefined
    throw error
  })
  await workbenchControls
})
app.use(createPinia())
app.use(router)
app.mount('#app')
