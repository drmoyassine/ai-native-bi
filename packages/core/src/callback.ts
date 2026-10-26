import { SupplyIssuesSchema, type SupplyBody } from '@bi/contract';

export type CallbackResult =
  | { status: 200 }
  | { status: 401 | 409; final: true }
  | { status: 422; issues: { path: string; message: string }[] }
  | { status: 'error'; message: string };

/** Posts the supply to the AMS (contract 4.2) with the run's one-time token. Never follows a redirect. */
export async function postSupply(url: string, token: string, body: SupplyBody, timeoutMs: number, fetcher: typeof fetch = fetch): Promise<CallbackResult> {
  let res: Response;
  try {
    res = await fetcher(url, {
      method: 'POST', body: JSON.stringify(body), redirect: 'error', signal: AbortSignal.timeout(timeoutMs),
      headers: { 'content-type': 'application/json', authorization: `Bearer ${token}` },
    });
  } catch (e) {
    return { status: 'error', message: (e as Error).message };
  }
  if (res.status === 200) return { status: 200 };
  if (res.status === 401 || res.status === 409) return { status: res.status, final: true };
  if (res.status === 422) {
    const parsed = SupplyIssuesSchema.safeParse(await res.json().catch(() => ({})));
    return { status: 422, issues: parsed.success ? parsed.data.issues ?? [] : [] };
  }
  return { status: 'error', message: `the AMS answered ${res.status}` };
}
