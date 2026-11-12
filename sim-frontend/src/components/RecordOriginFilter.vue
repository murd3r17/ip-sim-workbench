<template>
  <div class="record-origin-filter"><label>记录来源<el-select :model-value="modelValue" aria-label="记录来源筛选" @update:model-value="$emit('update:modelValue',String($event))"><el-option v-for="item in options" :key="item.value" :value="item.value" :label="`${item.label}（${count(item.value)}）`" /></el-select></label><span>按保存的入口/测试标记分类；来源未明默认保留，筛选可随时恢复全部。</span></div>
</template>
<script setup lang="ts">
import {recordOrigin,type OriginRecord} from '../utils/recordOrigin'
const props=defineProps<{modelValue:string;records:OriginRecord[];unavailable?:boolean}>()
defineEmits<{'update:modelValue':[value:string]}>()
const options=[{value:'all',label:'全部来源'},{value:'normal',label:'已登记业务入口'},{value:'test',label:'明确测试'},{value:'unknown',label:'来源未明'}]
const count=(value:string)=>props.unavailable?'待重试':value==='all'?props.records.length:props.records.filter(x=>recordOrigin(x)===value).length
</script>
<style scoped>
.record-origin-filter{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:12px 0;color:var(--v7b-muted);font-size:12px}.record-origin-filter label{display:flex;align-items:center;gap:10px}.record-origin-filter .el-select{width:215px}.record-origin-filter span{line-height:1.7;max-width:58ch}
</style>
