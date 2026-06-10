export type OrbSource =
  | 'runtime'
  | 'bridge'
  | 'supabase'
  | 'github'
  | 'notion'
  | 'mock'
  | 'planned'
  | 'unknown';

export type OrbHealth = 'online' | 'degraded' | 'offline' | 'unknown';

export type TrainingStatus =
  | 'random_init'
  | 'training'
  | 'fine_tuning'
  | 'converged'
  | 'deployed'
  | 'unknown';

export interface VisualSourceMeta {
  id: string;
  title: string;
  source: OrbSource;
  health: OrbHealth;
  value: number | null;
  unit: string;
  description: string;
  lastUpdatedIso: string | null;
}

export interface NeuroBusState {
  reward: number | null;
  novelty: number | null;
  attention: number | null;
  patience: number | null;
  threat: number | null;
  trust: number | null;
  source: OrbSource;
  lastUpdatedIso: string | null;
}

export interface BrainState {
  hiddenState64: string | null;
  activations: number[] | null;
  actionType: string | null;
  isSpeaking: boolean | null;
  modelLabel: string | null;
  parameterCount: number | null;
  trainingStatus: TrainingStatus;
  source: OrbSource;
}

export interface ResourceState {
  cpu: number | null;
  ram: number | null;
  storage: number | null;
  network: number | null;
  apiUsage: number | null;
  source: OrbSource;
}

export interface DataSpineState {
  db: number | null;
  memory: number | null;
  logs: number | null;
  source: OrbSource;
}

export interface ForgeGateState {
  lint: boolean | null;
  test: boolean | null;
  build: boolean | null;
  passed: boolean | null;
}

export interface ForgeState {
  status: 'idle' | 'running' | 'gated' | 'error' | 'unknown';
  activeTask: string | null;
  queueLength: number | null;
  lastPrUrl: string | null;
  gate: ForgeGateState | null;
  source: OrbSource;
}

export interface CompletedItem {
  id: string;
  label: string;
  area: string;
  confidence: number | null;
  completedAtIso: string | null;
  source: OrbSource;
  url: string | null;
}

export interface NetworkService {
  id: string;
  name: string;
  health: OrbHealth;
  url: string | null;
}

export interface NetworkLink {
  from: string;
  to: string;
  status: 'up' | 'down' | 'degraded' | 'unknown';
}

export interface NetworkState {
  services: NetworkService[];
  links: NetworkLink[];
  source: OrbSource;
}

export interface AlertError {
  id: string;
  message: string;
  severity: 'critical' | 'warning' | 'info';
  timestamp: string | null;
}

export interface AlertGate {
  pr: number | null;
  name: string;
  passed: boolean | null;
}

export interface AlertState {
  threat: number | null;
  pam: number | null;
  driftCount: number | null;
  errors: AlertError[];
  gates: AlertGate[];
  source: OrbSource;
}

export interface FuturePlan {
  id: string;
  label: string;
  area: string;
  status: 'planned' | 'in_progress' | 'complete' | 'cancelled';
  targetDateIso: string | null;
  source: OrbSource;
}

export interface HeliosOrbState {
  meta: VisualSourceMeta;
  neurobus: NeuroBusState;
  brain: BrainState;
  resources: ResourceState;
  data: DataSpineState;
  forge: ForgeState;
  completed: CompletedItem[];
  network: NetworkState;
  alerts: AlertState;
  future: FuturePlan[];
}

export interface OrbInspectorState {
  selected: string | null;
  hovered: string | null;
  mode: 'overview' | 'detail' | 'debug';
}
