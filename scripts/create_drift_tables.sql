-- Run this in Supabase Dashboard → SQL Editor
-- Creates the DRIFT.md state tables for agent-queryable state

CREATE TABLE IF NOT EXISTS system_state (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS exit_criteria (
  id SERIAL PRIMARY KEY,
  phase TEXT NOT NULL,
  criteria TEXT NOT NULL,
  status TEXT DEFAULT 'pending',
  tested_at TIMESTAMPTZ,
  notes TEXT,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS merged_prs (
  id SERIAL PRIMARY KEY,
  repo TEXT NOT NULL,
  pr_number INTEGER NOT NULL,
  branch TEXT,
  title TEXT,
  merged_at TIMESTAMPTZ,
  sha TEXT,
  UNIQUE(repo, pr_number)
);
