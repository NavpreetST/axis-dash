import type { HeliosOrbState } from './types';

export function createMockOrbState(): HeliosOrbState {
  return {
    meta: {
      id: 'helios-orb-dashboard',
      title: 'Helios Neural Orb',
      source: 'mock',
      health: 'degraded',
      value: null,
      unit: '',
      description: 'Aggregate cognitive state for the Helios AXIS daemon. Mock deployment.',
      lastUpdatedIso: new Date().toISOString()
    },
    neurobus: {
      reward: 0.73,
      novelty: 0.41,
      attention: 0.88,
      patience: 0.62,
      threat: 0.09,
      trust: 0.91,
      source: 'runtime',
      lastUpdatedIso: new Date().toISOString()
    },
    brain: {
      hiddenState64: 'AAAAcHViIHN0YXRlIGlzIG5vdCBhY3R1YWxseSBiYXNlNjQtZW5jb2RlZA==',
      activations: null,
      actionType: null,
      isSpeaking: false,
      modelLabel: 'helios-axum-v0.1-random-init',
      parameterCount: null,
      trainingStatus: 'random_init',
      source: 'mock'
    },
    resources: {
      cpu: 34.2,
      ram: 1_073_741_824,
      storage: 8_589_934_592,
      network: null,
      apiUsage: 142,
      source: 'bridge'
    },
    data: {
      db: 12,
      memory: 536_870_912,
      logs: 482,
      source: 'bridge'
    },
    forge: {
      status: 'running',
      activeTask: 'a3f1c8e2-9b7d-4f5a-9c3e-1a2b3c4d5e6f',
      queueLength: 3,
      lastPrUrl: 'https://github.com/NavpreetST/axis-dash/pull/34',
      gate: null,
      source: 'bridge'
    },
    completed: [
      {
        id: 'task-templates-diff',
        label: 'Add task templates + improved diff view',
        area: 'forge',
        confidence: null,
        completedAtIso: new Date().toISOString(),
        source: 'bridge',
        url: 'https://github.com/NavpreetST/axis-dash/pull/34'
      },
      {
        id: 'ci-coderabbit-gate',
        label: 'CodeRabbit CI gate pipeline',
        area: 'infra',
        confidence: 0.88,
        completedAtIso: new Date(Date.now() - 86400000).toISOString(),
        source: 'supabase',
        url: 'https://github.com/NavpreetST/axis-dash/pull/30'
      },
      {
        id: 'live-polish',
        label: 'Post-live UI polish',
        area: 'ui',
        confidence: 0.95,
        completedAtIso: new Date(Date.now() - 172800000).toISOString(),
        source: 'github',
        url: 'https://github.com/NavpreetST/axis-dash/pull/29'
      }
    ],
    network: {
      services: [
        {
          id: 'bridge',
          name: 'Helios Bridge',
          health: 'online',
          url: 'https://skins-stories-seed-player.trycloudflare.com'
        },
        { id: 'supabase', name: 'Supabase DB', health: 'online', url: null },
        { id: 'daemon', name: 'Helios Daemon', health: 'degraded', url: null },
        { id: 'orb', name: 'Orb Renderer', health: 'offline', url: null },
        { id: 'notion', name: 'Notion Sync', health: 'unknown', url: null }
      ],
      links: [
        { from: 'bridge', to: 'supabase', status: 'up' },
        { from: 'bridge', to: 'daemon', status: 'degraded' },
        { from: 'daemon', to: 'orb', status: 'down' },
        { from: 'bridge', to: 'orb', status: 'unknown' }
      ],
      source: 'bridge'
    },
    alerts: {
      threat: 14,
      pam: 0.21,
      driftCount: null,
      errors: [
        {
          id: 'alert-001',
          message: 'Orb daemon connection timeout — render pipeline stalled',
          severity: 'critical',
          timestamp: new Date(Date.now() - 300000).toISOString()
        },
        {
          id: 'alert-002',
          message: 'Hidden state activations unavailable — model not trained',
          severity: 'warning',
          timestamp: new Date(Date.now() - 3600000).toISOString()
        },
        {
          id: 'alert-003',
          message: 'Notion sync token expired',
          severity: 'info',
          timestamp: new Date(Date.now() - 7200000).toISOString()
        }
      ],
      gates: [
        { pr: 30, name: 'Lint', passed: true },
        { pr: 30, name: 'Tests', passed: true },
        { pr: 30, name: 'CodeRabbit', passed: true },
        { pr: 30, name: 'Drift Guard', passed: true },
        { pr: 30, name: 'Merge Ready', passed: true },
        { pr: 34, name: 'Lint', passed: true },
        { pr: 34, name: 'Tests', passed: true },
        { pr: 34, name: 'CodeRabbit', passed: false },
        { pr: 34, name: 'Drift Guard', passed: true },
        { pr: 34, name: 'Merge Ready', passed: null }
      ],
      source: 'runtime'
    },
    future: [
      {
        id: 'plan-orb-phase5',
        label: '3D Neural Orb Canvas',
        area: 'orb',
        status: 'planned',
        targetDateIso: null,
        source: 'planned'
      },
      {
        id: 'plan-notion-sync',
        label: 'Notion integration for task sync',
        area: 'infra',
        status: 'planned',
        targetDateIso: '2026-07-15T00:00:00.000Z',
        source: 'notion'
      },
      {
        id: 'plan-memory-ui',
        label: 'Episodic memory viewer',
        area: 'ui',
        status: 'in_progress',
        targetDateIso: null,
        source: 'planned'
      }
    ]
  };
}
