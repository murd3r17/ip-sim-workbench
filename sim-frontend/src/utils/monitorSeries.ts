import {parseApiTime} from './datetime'
import type {MonitorTrendPoint} from '../api/monitor'

/** Keep series identity by device ID; labels use inventory names when available. */
export function buildMonitorSeries(points:MonitorTrendPoint[]) {
 const groups=new Map<number,{id:string;name:string;data:[number,number][]}>()
 for(const point of points){
  const time=parseApiTime(point.time)?.getTime()
  if(!Number.isInteger(point.device_id)||point.device_id<=0||time===undefined||typeof point.value!=='number'||!Number.isFinite(point.value))continue
  const item=groups.get(point.device_id)||{id:`device-${point.device_id}`,name:point.device_name?.trim()||`设备 #${point.device_id}`,data:[]}
  if(point.device_name?.trim())item.name=point.device_name.trim()
  item.data.push([time,point.value]);groups.set(point.device_id,item)
 }
 const counts=new Map<string,number>()
 for(const item of groups.values())counts.set(item.name,(counts.get(item.name)||0)+1)
 return [...groups].map(([id,item])=>({...item,name:(counts.get(item.name)||0)>1?`${item.name} · #${id}`:item.name,data:item.data.sort((a,b)=>a[0]-b[0])}))
}
