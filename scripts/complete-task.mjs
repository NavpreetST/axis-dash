#!/usr/bin/env node
/**
 * Marks the newest matching Supabase task as complete.
 *
 * Usage:
 *   node scripts/complete-task.mjs "New Task form"
 *
 * Environment:
 *   PUBLIC_SUPABASE_URL   – Supabase project URL (set on Vercel)
 *   PUBLIC_SUPABASE_ANON_KEY – Supabase anon key (set on Vercel)
 *
 * If env vars are not set locally, provide them inline:
 *   PUBLIC_SUPABASE_URL=https://vbjimkvainiblouofano.supabase.co \
 *   PUBLIC_SUPABASE_ANON_KEY=<your-anon-key> \
 *   node scripts/complete-task.mjs
 */
import { createClient } from '@supabase/supabase-js';

const SUPABASE_URL = process.env.PUBLIC_SUPABASE_URL;
const SUPABASE_ANON_KEY = process.env.PUBLIC_SUPABASE_ANON_KEY;
const TASK_TITLE = process.argv[2] || 'New Task form';

if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
  console.error('Missing PUBLIC_SUPABASE_URL or PUBLIC_SUPABASE_ANON_KEY env vars');
  console.error('Get the anon key from Vercel dashboard → your project → Environment Variables');
  process.exit(1);
}

const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

async function main() {
  const query = supabase.from('tasks').select('id').order('id', { ascending: false }).limit(5);
  query.ilike('title', `%${TASK_TITLE}%`);

  const { data: tasks, error: findError } = await query;
  if (findError) {
    console.error('Find error:', findError);
    process.exit(1);
  }
  if (!tasks || tasks.length === 0) {
    console.log('No matching task found.');
    process.exit(0);
  }

  const task = tasks[0];
  console.log(`Found task #${task.id}`);

  const { error: patchError } = await supabase
    .from('tasks')
    .update({ status: 'complete', result_summary: 'New Task form added to /todo' })
    .eq('id', task.id);

  if (patchError) {
    console.error('PATCH error:', patchError);
    process.exit(1);
  }
  console.log(`Task #${task.id} marked complete.`);
}

main();
