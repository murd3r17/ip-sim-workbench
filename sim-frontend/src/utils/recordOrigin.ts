export type RecordOrigin='normal'|'test'|'unknown'
export interface OriginRecord {record_origin?:string}
export function recordOrigin(row:OriginRecord):RecordOrigin {
  return row.record_origin==='normal'||row.record_origin==='test'?row.record_origin:'unknown'
}
export function filterByRecordOrigin<T extends OriginRecord>(rows:T[],filter:string):T[] {
  return filter==='all'?rows:rows.filter(row=>recordOrigin(row)===filter)
}
export const recordOriginLabel=(origin:string)=>({normal:'已登记业务入口',test:'明确测试',unknown:'来源未明'}[origin]||'来源未明')
