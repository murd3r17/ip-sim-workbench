import { logOperation } from '../api/training'
import { useLabContextStore } from '../stores/labContext'

export function useTrainingCommandLog() {
  const labCtx = useLabContextStore()

  const logTerminalCommand = async (payload: {
    command: string
    success: boolean
    result?: string
    hostname?: string
  }) => {
    const sessionId = labCtx.sessionId
    const labId = labCtx.labId
    // A-04：只有进行中的会话才写操作记录；已结束会话只读回看。
    if (!sessionId || !labId || !labCtx.isActive) return
    try {
      await logOperation(sessionId, {
        lab_id: labId,
        action: 'command',
        target_device: payload.hostname || labCtx.device?.hostname,
        command: payload.command,
        result: payload.result?.slice(0, 500),
        success: payload.success,
        // Captured in the browser; only the server can attest execution evidence.
        meta: { source: 'webssh', evidence_trust: 'client_reported' },
      }, { silent: true })
    } catch {
      /* 记录失败不打断终端；拦截器已提示 */
    }
  }

  return { logTerminalCommand }
}
