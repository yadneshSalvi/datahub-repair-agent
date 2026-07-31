import type {
  CatalogDataset,
  DatasetSchema,
  DriftEvent,
  HealthResponse,
  LineageGraph,
  RepairRun,
  Scenario,
  StartRunRequest,
} from './types'

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })

  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    try {
      const body = (await response.json()) as { detail?: string }
      message = body.detail ?? message
    } catch {
      // Preserve the HTTP status text for non-JSON failures.
    }
    throw new ApiError(message, response.status)
  }

  return response.json() as Promise<T>
}

export const api = {
  health: () => request<HealthResponse>('/api/health'),
  scenarios: () => request<Scenario[]>('/api/scenarios'),
  applyScenario: (name: string) =>
    request<{ ok: boolean; scenario: string; reverted: boolean; detail: string }>(`/api/scenarios/${name}/apply`, {
      method: 'POST',
    }),
  drift: () => request<DriftEvent[]>('/api/drift'),
  catalog: () => request<CatalogDataset[]>('/api/catalog'),
  schema: (urn: string) => request<DatasetSchema>(`/api/catalog/${encodeURIComponent(urn)}/schema`),
  startRun: (body: StartRunRequest) =>
    request<{ run_id: string }>('/api/runs', { method: 'POST', body: JSON.stringify(body) }),
  runs: () => request<RepairRun[]>('/api/runs'),
  run: (runId: string) => request<RepairRun>(`/api/runs/${runId}`),
  graph: (runId: string) => request<LineageGraph>(`/api/runs/${runId}/graph`),
  reset: () => request<{ ok: boolean; detail: string }>('/api/reset', { method: 'POST' }),
}
