import { spawn } from 'node:child_process'
import { createRequire } from 'node:module'
import process from 'node:process'

const require = createRequire(import.meta.url)
const child = spawn(process.execPath, [require.resolve('@playwright/test/cli'), 'test', ...process.argv.slice(2)], {
  stdio: 'inherit',
  env: { ...process.env, E2E_REQUIRE_UP: '1' },
})
child.on('error', error => {
  console.error(error.message)
  process.exitCode = 1
})
child.on('exit', code => { process.exitCode = code ?? 1 })
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.once(signal, () => { if (child.exitCode === null) child.kill(signal) })
}
