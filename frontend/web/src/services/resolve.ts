/**
 * The demo/live branch, in one place.
 *
 * Every service call goes through `resolve`, so the policy cannot drift
 * between endpoints.
 *
 * Demo answers only from `src/data/mock*.ts`.
 * Live answers only from the AeroPulse API. A failed live call is recorded
 * and thrown — it must never return demo data while the header says Live.
 */

import { ApiError } from '../api/client'
import { isDemo, recordFallback, clearFallback } from './dataMode'

/**
 * Run the demo or live implementation according to the current mode.
 *
 * @param endpoint Stable label for the live-failure banner, e.g. `events`.
 * @param demo Demo implementation. Used only when the toggle is Demo.
 * @param live Live implementation.
 */
export async function resolve<T>(
  endpoint: string,
  demo: () => Promise<T>,
  live: () => Promise<T>,
): Promise<T> {
  if (isDemo()) return demo()

  try {
    const result = await live()
    clearFallback(endpoint)
    return result
  } catch (error) {
    const reason = error instanceof ApiError ? error.reason : 'unexpected error'
    recordFallback(endpoint, reason)
    throw error
  }
}
