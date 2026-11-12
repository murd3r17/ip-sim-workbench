import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { ElAlert } from 'element-plus/es/components/alert/index'
import { ElButton, ElButtonGroup } from 'element-plus/es/components/button/index'
import { ElCard } from 'element-plus/es/components/card/index'
import { ElCheckbox } from 'element-plus/es/components/checkbox/index'
import { ElCol } from 'element-plus/es/components/col/index'
import { ElAside, ElContainer, ElHeader, ElMain } from 'element-plus/es/components/container/index'
import { ElDescriptions, ElDescriptionsItem } from 'element-plus/es/components/descriptions/index'
import { ElDialog } from 'element-plus/es/components/dialog/index'
import { ElDrawer } from 'element-plus/es/components/drawer/index'
import { ElDropdown, ElDropdownItem, ElDropdownMenu } from 'element-plus/es/components/dropdown/index'
import { ElForm, ElFormItem } from 'element-plus/es/components/form/index'
import { ElIcon } from 'element-plus/es/components/icon/index'
import { ElInput } from 'element-plus/es/components/input/index'
import { ElInputNumber } from 'element-plus/es/components/input-number/index'
import { ElMenu, ElMenuItem, ElMenuItemGroup, ElSubMenu } from 'element-plus/es/components/menu/index'
import { ElOption, ElSelect } from 'element-plus/es/components/select/index'
import { ElPagination } from 'element-plus/es/components/pagination/index'
import { ElPopconfirm } from 'element-plus/es/components/popconfirm/index'
import { ElProgress } from 'element-plus/es/components/progress/index'
import { ElRadio, ElRadioGroup, ElRadioButton } from 'element-plus/es/components/radio/index'
import { ElRow } from 'element-plus/es/components/row/index'
import { ElSwitch } from 'element-plus/es/components/switch/index'
import { ElTabPane, ElTabs } from 'element-plus/es/components/tabs/index'
import { ElTable, ElTableColumn } from 'element-plus/es/components/table/index'
import { ElTag } from 'element-plus/es/components/tag/index'
import { ElUpload } from 'element-plus/es/components/upload/index'
import { ElEmpty } from 'element-plus/es/components/empty/index'
import { ElSkeleton, ElSkeletonItem } from 'element-plus/es/components/skeleton/index'
import { ElStep, ElSteps } from 'element-plus/es/components/steps/index'
import { ElTooltip } from 'element-plus/es/components/tooltip/index'
import { ElDivider } from 'element-plus/es/components/divider/index'
import { ElLoadingDirective } from 'element-plus/es/components/loading/index'
// 按需引入样式：`element-plus/dist/index.css` 是整库 CSS（349 KB），而实际只用到
// 下面这些组件。每个 `<comp>/style/css` 自带 base 与依赖组件的样式，按需引入后
// 体积明显下降（P2-24）。
import 'element-plus/es/components/alert/style/css'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/card/style/css'
import 'element-plus/es/components/checkbox/style/css'
import 'element-plus/es/components/col/style/css'
import 'element-plus/es/components/config-provider/style/css'
import 'element-plus/es/components/container/style/css'
import 'element-plus/es/components/descriptions/style/css'
import 'element-plus/es/components/dialog/style/css'
import 'element-plus/es/components/divider/style/css'
import 'element-plus/es/components/drawer/style/css'
import 'element-plus/es/components/dropdown/style/css'
import 'element-plus/es/components/empty/style/css'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/form-item/style/css'
import 'element-plus/es/components/icon/style/css'
import 'element-plus/es/components/input/style/css'
import 'element-plus/es/components/input-number/style/css'
import 'element-plus/es/components/menu/style/css'
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import 'element-plus/es/components/pagination/style/css'
import 'element-plus/es/components/popconfirm/style/css'
import 'element-plus/es/components/progress/style/css'
import 'element-plus/es/components/radio/style/css'
import 'element-plus/es/components/radio-button/style/css'
import 'element-plus/es/components/row/style/css'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/skeleton/style/css'
import 'element-plus/es/components/steps/style/css'
import 'element-plus/es/components/switch/style/css'
import 'element-plus/es/components/table/style/css'
import 'element-plus/es/components/tabs/style/css'
import 'element-plus/es/components/tag/style/css'
import 'element-plus/es/components/tooltip/style/css'
import 'element-plus/es/components/upload/style/css'
import 'element-plus/es/components/loading/style/css'
import 'element-plus/es/components/radio-group/style/css'
import 'element-plus/es/components/table-column/style/css'
import 'element-plus/es/components/step/style/css'
import './styles/v7b.css'
import App from './App.vue'
import router from './router'

const app = createApp(App)
const elementComponents = [
  ElAlert,
  ElAside,
  ElButton,
  ElButtonGroup,
  ElCard,
  ElCheckbox,
  ElCol,
  ElContainer,
  ElDescriptions,
  ElDescriptionsItem,
  ElDialog,
  ElDrawer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElForm,
  ElFormItem,
  ElHeader,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElMain,
  ElMenu,
  ElMenuItem,
  ElMenuItemGroup,
  ElOption,
  ElPagination,
  ElPopconfirm,
  ElProgress,
  ElRadio,
  ElRadioGroup,
  ElRadioButton,
  ElRow,
  ElSelect,
  ElSubMenu,
  ElSwitch,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTag,
  ElUpload,
  ElEmpty,
  ElSkeleton,
  ElSkeletonItem,
  ElStep,
  ElSteps,
  ElTooltip,
  ElDivider,
]

elementComponents.forEach(component => app.component(component.name!, component))
// v-loading 此前未注册：表格加载态不显示，容易把“正在加载”误读为“暂无数据”
app.directive('loading', ElLoadingDirective)
app.use(createPinia())
app.use(router)
app.mount('#app')
