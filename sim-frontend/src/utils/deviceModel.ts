/** 工作台现网是 NE40E 家族。未选设备、库里没填型号、或字面 unknown 时按此校验/生成。 */
export function resolveWorkbenchDeviceModel(model?: string | null): string {
  const raw = (model || '').trim()
  if (!raw || ['unknown', 'generic', '通用', 'none', 'null'].includes(raw.toLowerCase())) {
    return 'NE40E'
  }
  return raw
}
