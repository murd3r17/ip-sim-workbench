/** A server risk challenge always waits for a fresh human decision. */
export async function confirmWithRisk(
  confirm: (risk: boolean) => Promise<unknown>,
  askRiskConfirmation: () => Promise<unknown>,
): Promise<boolean> {
  try {
    await confirm(false)
    return false
  } catch (error) {
    const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })?.response
    if (response?.status !== 422 || response.data?.detail !== '高风险任务需要二次确认') throw error
  }
  await askRiskConfirmation()
  await confirm(true)
  return true
}
