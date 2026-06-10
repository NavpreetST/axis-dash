<script lang="ts">
  import { T, useTask } from '@threlte/core';
  import type { ColorRepresentation } from 'three';

  interface RingArc {
    key: string;
    radius: number;
    color: ColorRepresentation;
    tiltX: number;
    tiltZ: number;
    rotSpeed: number;
  }

  let {
    cpu,
    ram,
    storage,
    api
  }: { cpu: number | null; ram: number | null; storage: number | null; api: number | null } =
    $props();

  const RINGS: RingArc[] = [
    { key: 'ram', radius: 1.35, color: '#8b5cf6', tiltX: 0.08, tiltZ: 0.12, rotSpeed: 0.06 },
    { key: 'cpu', radius: 1.5, color: '#22c55e', tiltX: -0.1, tiltZ: 0.05, rotSpeed: 0.08 },
    { key: 'storage', radius: 1.65, color: '#f59e0b', tiltX: 0.15, tiltZ: -0.08, rotSpeed: 0.04 },
    { key: 'api', radius: 1.8, color: '#06b6d4', tiltX: -0.05, tiltZ: -0.15, rotSpeed: 0.1 }
  ];

  const INNER_GAP = 0.025;
  const SEGMENTS = 64;

  let ringRotation = $state<Record<string, number>>({ cpu: 0, ram: 0, storage: 0, api: 0 });

  const values: Record<string, number | null> = $derived({ cpu, ram, storage, api });

  useTask((delta) => {
    const dt = Math.min(delta, 0.05);
    for (const r of RINGS) {
      ringRotation[r.key] = (ringRotation[r.key] ?? 0) + dt * r.rotSpeed;
    }
  });
</script>

{#each RINGS as ring (ring.key)}
  {@const val = values[ring.key]}
  {@const fillAngle = (val != null ? Math.min(Math.max(val, 0), 1) : 0) * Math.PI * 2}
  <T.Group rotation.y={ringRotation[ring.key] ?? 0}>
    <T.Mesh rotation={[ring.tiltX, 0, ring.tiltZ]}>
      <T.MeshBasicMaterial
        color={ring.color}
        opacity={0.08}
        transparent={true}
        depthWrite={false}
      />
      <T.RingGeometry args={[ring.radius - INNER_GAP, ring.radius + INNER_GAP, SEGMENTS]} />
    </T.Mesh>
    <T.Mesh rotation={[ring.tiltX, 0, ring.tiltZ]}>
      <T.MeshBasicMaterial
        color={ring.color}
        opacity={0.55}
        transparent={true}
        depthWrite={false}
      />
      <T.RingGeometry
        args={[ring.radius - INNER_GAP, ring.radius + INNER_GAP, SEGMENTS, 1, 0, fillAngle]}
      />
    </T.Mesh>
  </T.Group>
{/each}
