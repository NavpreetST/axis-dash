import { createClient } from '@supabase/supabase-js';
import { PUBLIC_SUPABASE_URL, PUBLIC_SUPABASE_ANON_KEY } from '$env/static/public';

export const supabase =
  typeof PUBLIC_SUPABASE_URL === 'string' &&
  PUBLIC_SUPABASE_URL.length > 0 &&
  typeof PUBLIC_SUPABASE_ANON_KEY === 'string' &&
  PUBLIC_SUPABASE_ANON_KEY.length > 0
    ? createClient(PUBLIC_SUPABASE_URL, PUBLIC_SUPABASE_ANON_KEY)
    : null;

export interface Task {
  id: number;
  title: string;
  description: string;
  phase: string;
  owner: string;
  priority: 'high' | 'medium' | 'low';
  status: 'open' | 'in_progress' | 'complete' | 'pending';
  branch: string;
  pr_number: number | null;
  repo: string;
  gates_passed: number;
  gates_total: number;
  created_at: string;
  updated_at: string;
}

export interface Phase {
  id: number;
  sort_order: number;
  title: string;
  codename: string;
  timeline: string;
  headline: string;
  completion_pct: number;
  status: 'active' | 'complete' | 'pending';
  exit_criteria: string;
  created_at: string;
}

export interface GateStatus {
  id: number;
  repo: string;
  pr_number: number;
  branch: string;
  gate_name: string;
  status: string;
  details: string;
  created_at: string;
  updated_at: string;
}

export interface NewTaskInput {
  title: string;
  description?: string;
  phase?: string;
  priority?: 'high' | 'medium' | 'low';
}

export async function createTask(input: NewTaskInput): Promise<Task | null> {
  if (!supabase) return null;
  const { data, error } = await supabase
    .from('tasks')
    .insert({
      title: input.title,
      description: input.description ?? '',
      phase: input.phase ?? '',
      owner: '',
      priority: input.priority ?? 'medium',
      status: 'open',
      branch: '',
      pr_number: null,
      repo: '',
      gates_passed: 0,
      gates_total: 0
    })
    .select()
    .single();
  if (error) {
    console.error('[supabase] createTask error:', error);
    return null;
  }
  return data;
}

export async function fetchTasks(): Promise<Task[]> {
  if (!supabase) return [];
  const { data, error } = await supabase
    .from('tasks')
    .select('*')
    .order('id', { ascending: false });
  if (error) {
    console.error('[supabase] fetchTasks error:', error);
    return [];
  }
  return data ?? [];
}

export async function fetchPhases(): Promise<Phase[]> {
  if (!supabase) return [];
  const { data, error } = await supabase
    .from('phases')
    .select('*')
    .order('sort_order', { ascending: true });
  if (error) {
    console.error('[supabase] fetchPhases error:', error);
    return [];
  }
  return data ?? [];
}
