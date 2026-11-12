<template>
  <div class="system-config v7b-page">
    <header class="v7b-page-header"><div><h1>系统配置</h1><p class="sub">查看当前读取值，再决定修改启动配置或数据库覆盖。</p></div><el-button type="primary" @click="showAddDialog">新增配置</el-button></header>
    <div class="config-groups"><el-radio-group v-model="activeGroup" size="small" aria-label="配置分组"><el-radio-button v-for="group in GROUPS" :key="group.key" :value="group.key">{{group.label}} <span class="group-count">{{countOf(group.key)}}</span></el-radio-button></el-radio-group><el-button v-if="showLlmTest" :loading="llmTesting" @click="testLlm">测试模型连通性</el-button></div>
    <el-alert v-if="llmTestResult" :title="llmTestResult" :type="llmTestOk?'success':'warning'" :closable="false" show-icon />
    <EffectiveConfiguration :data="effective" :loading="loading" :error="effectiveError" :group="activeGroup" @refresh="loadConfigs" />
    <el-card shadow="never"><template #header><div class="card-header"><strong>已保存数据库键值（{{visibleConfigs.length}}）</strong><span>保存与实际生效分别核对</span></div></template>
      <el-alert v-if="loadError" :title="loadError" type="warning" :closable="false" show-icon />
      <el-table :data="visibleConfigs" v-loading="loading">
        <template #empty><el-empty :description="loadError||'当前分组没有已保存键值。'" :image-size="72" /></template>
        <el-table-column prop="config_key" label="配置键" min-width="210" />
        <el-table-column label="保存值" min-width="160" show-overflow-tooltip><template #default="{row}"><span v-if="row.is_secret">{{row.config_value?'已配置（内容隐藏）':'未配置'}}</span><span v-else>{{row.config_value??'（空）'}}</span></template></el-table-column>
        <el-table-column label="使用方式" min-width="190"><template #default="{row}"><el-tooltip :content="consumer(row.config_key).note" placement="top"><span>{{activationLabel(consumer(row.config_key).activation)}}</span></el-tooltip><small v-if="consumer(row.config_key).activation==='not_applied'">当前服务不读取此数据库键</small></template></el-table-column>
        <el-table-column prop="description" label="描述" min-width="160" show-overflow-tooltip />
        <el-table-column prop="updated_by" label="更新者" width="95" />
        <el-table-column label="更新时间" width="175"><template #default="{row}">{{formatApiTime(row.updated_at)}}</template></el-table-column>
        <el-table-column label="操作" width="150"><template #default="{row}"><el-button size="small" :disabled="saving||deletingKey===row.config_key" @click="editConfig(row)">编辑</el-button><el-popconfirm :title="deleteMessage(row.config_key)" confirm-button-text="删除覆盖" cancel-button-text="取消" @confirm="deleteConfig(row.config_key)"><template #reference><el-button size="small" type="danger" :loading="deletingKey===row.config_key" :disabled="saving" >删除</el-button></template></el-popconfirm></template></el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="dialogVisible" class="v7b-record-dialog config-editor" top="4vh" :title="editingKey?'编辑配置':'新增配置'" width="min(620px,94vw)" draggable>
      <el-form :model="form" label-position="top">
        <el-form-item label="配置键"><el-input v-model="form.config_key" :disabled="!!editingKey" placeholder="例如: llm.model" /></el-form-item>
        <el-alert :title="consumer(form.config_key.trim()).note" type="info" :closable="false" show-icon />
        <el-form-item label="配置值"><el-input v-if="formIsSecret" v-model="form.config_value" type="password" autocomplete="new-password" :placeholder="editingKey?'留空保留已保存值':'输入新凭据（不会回显）'" /><el-input v-else v-model="form.config_value" type="textarea" :rows="3" placeholder="配置值" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" placeholder="配置说明" /></el-form-item>
        <p v-if="formIsSecret" class="secret-tip">凭据内容隐藏；编辑已有项时留空会保留原值。空的模型覆盖不关闭进程配置。</p>
        <el-alert v-if="saveNotice||saveError" :title="saveError||saveNotice" :type="saveError?'warning':'info'" :closable="false" show-icon />
      </el-form><template #footer><el-button @click="dialogVisible=false">取消</el-button><el-button type="primary" :loading="saving" :disabled="saving||!form.config_key.trim()" @click="saveConfig">保存</el-button></template>
    </el-dialog>
  </div>
</template>
<script setup lang="ts">
import {computed,ref,onMounted,watch} from 'vue'
import {ElMessage} from 'element-plus/es/components/message/index'
import {formatApiTime} from '../../utils/datetime'
import {notifyRequestError,requestErrorMessage} from '../../utils/requestError'
import EffectiveConfiguration from '../../components/EffectiveConfiguration.vue'
import {listSystemConfigs,getEffectiveSystemConfig,testModelConnectivity,createSystemConfig,updateSystemConfig,deleteSystemConfig as deleteConfigApi,type EffectiveConfig,type ConfigConsumer} from '../../api/system'
interface ConfigItem {id:number;config_key:string;config_value:string|null;description:string|null;updated_by:string|null;updated_at:string;is_secret?:boolean}
const GROUPS=[{key:'all',label:'全部',prefix:''},{key:'llm',label:'AI 模型',prefix:'llm.'},{key:'knowledge',label:'知识库',prefix:'knowledge.'},{key:'monitor',label:'监控',prefix:'monitor.'},{key:'deploy',label:'配置下发',prefix:'deploy.'},{key:'other',label:'其他',prefix:''}]
const configs=ref<ConfigItem[]>([]),effective=ref<EffectiveConfig|null>(null),loading=ref(false),loadError=ref(''),effectiveError=ref(''),activeGroup=ref('all')
let loadEpoch=0,editorEpoch=0,formRevision=0,probeEpoch=0
const dialogVisible=ref(false),editingKey=ref<string|null>(null),editingIsSecret=ref(false),saving=ref(false),deletingKey=ref(''),saveNotice=ref(''),saveError=ref('')
const form=ref({config_key:'',config_value:'',description:''})
const formIsSecret=computed(()=>editingIsSecret.value||/(?:api[_-]?key|password|passwd|secret|token|authorization|fernet|device_default_enable)$/i.test(form.value.config_key))
watch(form,()=>{formRevision++},{deep:true,flush:'sync'})
watch(dialogVisible,v=>{if(!v)editorEpoch++},{flush:'sync'})
const inGroup=(item:ConfigItem,key:string)=>key==='all'?true:key==='other'?!GROUPS.some(g=>g.prefix&&item.config_key.startsWith(g.prefix)):item.config_key.startsWith(GROUPS.find(g=>g.key===key)?.prefix||'__unknown__')
const visibleConfigs=computed(()=>configs.value.filter(x=>inGroup(x,activeGroup.value)))
const countOf=(key:string)=>configs.value.filter(x=>inGroup(x,key)).length
const showLlmTest=computed(()=>['all','llm'].includes(activeGroup.value))
const consumer=(key:string):ConfigConsumer=>effective.value?.stored_items.find(x=>x.key===key)||effective.value?.known_items.find(x=>x.key===key)||{key,consumer:'unregistered',activation:'unknown',note:key.startsWith('llm.')?'仅支持已登记的LLM覆盖键，具体生效方式以有效配置快照为准。':'此键尚无已确认消费者；保存键值不证明已改变当前服务。'}
const activationLabel=(value:string)=>({next_provider:'后续新模型请求',next_collection:'后续采集读取',not_applied:'仅保存，未覆盖运行值',unknown:'消费者未登记'}[value]||value)
const deleteMessage=(key:string)=>consumer(key).activation==='next_provider'?'删除此数据库覆盖后，后续新模型请求回退到进程启动配置；在途请求不改。':'只删除此数据库键值；不会修改启动环境或直接修复设备。是否继续？'
const loadConfigs=async()=>{
 const epoch=++loadEpoch;loading.value=true
 const [stored,runtime]=await Promise.allSettled([listSystemConfigs(),getEffectiveSystemConfig()]);if(epoch!==loadEpoch)return
 if(stored.status==='fulfilled'){configs.value=stored.value as unknown as ConfigItem[];loadError.value=''}else{loadError.value='数据库键值读取失败；保留的列表可能陈旧，请刷新重试。';notifyRequestError(stored.reason,'加载配置失败')}
 if(runtime.status==='fulfilled'){effective.value=runtime.value;effectiveError.value=''}else effectiveError.value='有效配置读取失败；已有快照可能陈旧，请刷新重试。'
 loading.value=false
}
const showAddDialog=()=>{editorEpoch++;editingKey.value=null;editingIsSecret.value=false;form.value={config_key:'',config_value:'',description:''};saveError.value=saveNotice.value='';dialogVisible.value=true}
const editConfig=(row:ConfigItem)=>{editorEpoch++;editingKey.value=row.config_key;editingIsSecret.value=!!row.is_secret;form.value={config_key:row.config_key,config_value:row.is_secret?'':row.config_value||'',description:row.description||''};saveError.value=saveNotice.value='';dialogVisible.value=true}
const saveConfig=async()=>{
 if(saving.value||!form.value.config_key.trim())return
 const epoch=editorEpoch,revision=formRevision,key=editingKey.value,payload={...form.value,config_key:form.value.config_key.trim()},preserve=editingIsSecret.value&&!payload.config_value.trim()
 saving.value=true;saveError.value=saveNotice.value=''
 try{
  if(key)await updateSystemConfig(key,{config_value:preserve?undefined:payload.config_value,description:payload.description});else await createSystemConfig(payload)
  probeEpoch++;llmTestResult.value=''
  if(epoch===editorEpoch&&dialogVisible.value){if(revision===formRevision)dialogVisible.value=false;else saveNotice.value='已保存提交时的内容；你之后的编辑仍保留，尚未保存。'}
  ElMessage.success('键值已保存并记审计；实际生效方式请看有效配置。');await loadConfigs()
 }catch(error){if(epoch===editorEpoch){saveError.value='保存未成功，当前输入已保留。'+requestErrorMessage(error,'请稍后重试。');notifyRequestError(error,'保存失败')}}finally{saving.value=false}
}
const deleteConfig=async(key:string)=>{if(deletingKey.value||saving.value)return;deletingKey.value=key;try{await deleteConfigApi(key);probeEpoch++;llmTestResult.value='';ElMessage.success('已删除数据库键值并记审计');await loadConfigs()}catch(error){notifyRequestError(error,'删除失败')}finally{deletingKey.value=''}}
const llmTesting=ref(false),llmTestResult=ref(''),llmTestOk=ref(false)
const testLlm=async()=>{if(llmTesting.value)return;const epoch=++probeEpoch;llmTesting.value=true;try{const result=await testModelConnectivity(),llm=result.components?.llm||{};if(epoch!==probeEpoch)return;llmTestOk.value=llm.status==='healthy';llmTestResult.value=`模型链路${llmTestOk.value?'可连接':'当前不可用'} · ${llm.model||'模型未登记'} · ${formatApiTime(result.generated_at)}。${result.scope||'健康检查不等于回答质量通过。'}`}catch(error){if(epoch===probeEpoch){llmTestOk.value=false;llmTestResult.value=requestErrorMessage(error,'模型连通性检查失败，请重试。')}}finally{llmTesting.value=false}}
onMounted(loadConfigs)
</script>
<style scoped>
.system-config{--el-text-color-primary:var(--v7b-text);--el-text-color-regular:var(--v7b-muted);--el-border-color:var(--v7b-line);--el-border-color-light:var(--v7b-line);--el-border-color-lighter:var(--v7b-line)}.config-groups,.card-header{display:flex;align-items:center;gap:12px;justify-content:space-between;flex-wrap:wrap}.config-groups :deep(.el-radio-group){display:flex;flex-wrap:wrap;gap:4px}.config-groups :deep(.el-radio-button__inner){border:1px solid var(--v7b-line);border-radius:4px}.group-count{opacity:.7;margin-left:4px}.card-header span,small,.secret-tip{color:var(--v7b-muted);font-size:12px;line-height:1.7}small{display:block}.system-config :deep(.el-card){border-color:var(--v7b-line)}.system-config :deep(.el-button:not(.el-button--primary):not(.el-button--danger):not(.el-button--warning):not(.is-link)){background:#fff;color:var(--v7b-text);border-color:var(--v7b-line)}.system-config :deep(.el-button.is-disabled){color:#778396;background:var(--v7b-surface-2)}
</style>
<style scoped>
.system-config :deep(.el-radio-button__inner){background:#fff;color:var(--v7b-text)}.system-config :deep(.el-radio-button.is-active .el-radio-button__inner){background:var(--v7b-accent);color:#fff;border-color:var(--v7b-accent)}
</style>
