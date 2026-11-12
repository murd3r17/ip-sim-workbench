<template>
  <section class="effective-config v7b-card">
    <div class="effective-header"><div><h2>当前进程有效配置</h2><p>区分实际读取值与下方已保存键值。</p></div><el-button :loading="loading" @click="$emit('refresh')">刷新配置快照</el-button></div>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" show-icon />
    <template v-if="data">
      <div class="chain-grid"><div v-for="(text,name) in data.chains" :key="name"><strong>{{ chainName(String(name)) }}</strong><p>{{ text }}</p></div></div>
      <p class="effective-note">{{ data.scope }} · {{ formatApiTime(data.generated_at) }}</p>
      <details><summary>查看逐项有效值、来源与生效方式（{{ fields.length }} 项）</summary><p>{{ data.source_note }}</p>
        <el-table :data="fields" class="effective-values" max-height="520">
          <el-table-column prop="key" label="配置项" min-width="215" />
          <el-table-column label="当前有效值" min-width="220"><template #default="{row}"><span class="value">{{ show(row.value) }}</span><small v-if="!row.active">备用链路未启用</small></template></el-table-column>
          <el-table-column label="来源" min-width="150"><template #default="{row}">{{ sourceName(row.source) }}<small v-if="row.inherited_from">{{ row.inherited_from }}</small><small v-if="row.override_status==='invalid_fallback'">无效覆盖已回退</small><small v-if="row.override_status==='empty_fallback'">空覆盖已回退</small></template></el-table-column>
          <el-table-column label="生效方式" min-width="170"><template #default="{row}">{{ activationName(row.activation) }}</template></el-table-column>
          <el-table-column label="代码默认参照" min-width="180"><template #default="{row}">{{ show(row.default_value) }}</template></el-table-column>
        </el-table>
      </details>
      <details><summary>查看监控有效阈值</summary><p>默认值与支持的数据库项合并。旧 interface_down 总数项不控制端口用途告警；用途与预期请在监控页登记。</p><pre>{{ JSON.stringify(data.monitor_thresholds,null,2) }}</pre></details>
    </template>
    <p v-else-if="!loading">尚未取得有效配置快照，请刷新重试。</p>
  </section>
</template>
<script setup lang="ts">
import {computed} from 'vue'
import type {EffectiveConfig} from '../api/system'
import {formatApiTime} from '../utils/datetime'
const props=defineProps<{data:EffectiveConfig|null;loading:boolean;error:string;group:string}>()
defineEmits<{refresh:[]}>()
const fields=computed(()=>props.data?.fields.filter(f=>props.group==='all'||(props.group==='llm'?['llm','fallback','vision'].includes(f.group):props.group==='other'?f.group==='device':f.group===props.group))||[])
const show=(v:unknown)=>v===''?'（未设置）':v===null?'（空）':typeof v==='object'?JSON.stringify(v):String(v)
const chainName=(name:string)=>({dialogue:'对话主模型 / 备用',vision:'图片理解',knowledge:'知识检索'}[name]||name)
const sourceName=(name:string)=>({database:'数据库覆盖',process_settings:'进程启动配置',inherited:'继承主模型'}[name]||'来源未知')
const activationName=(name:string)=>({next_provider:'后续新请求；在途不改',restart_backend:'改启动配置后重启后端'}[name]||name)
</script>
<style scoped>
.effective-config{padding:16px}.effective-header{display:flex;gap:14px;align-items:start;justify-content:space-between;flex-wrap:wrap}h2{font-size:16px;margin:0}.effective-header p,.effective-note{font-size:12px;color:var(--v7b-muted);line-height:1.7}.chain-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,230px),1fr));gap:12px;margin:12px 0}.chain-grid>div{background:var(--v7b-surface-2);padding:12px;border-radius:6px}.chain-grid strong{font-size:13px}.chain-grid p,details p{font-size:12px;color:var(--v7b-muted);line-height:1.8;margin:6px 0}details{margin-top:12px}summary{cursor:pointer;color:var(--v7b-accent);font-size:13px;line-height:1.8}.value{overflow-wrap:anywhere}small{display:block;color:var(--v7b-muted);font-size:11px;line-height:1.8}pre{background:var(--v7b-surface-2);padding:12px;max-height:280px;overflow:auto;white-space:pre-wrap;color:var(--v7b-text);font-size:12px}
</style>
