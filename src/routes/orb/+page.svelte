<script lang="ts">
  import { Canvas, T } from '@threlte/core';
  import CoreOrbShell from '$lib/orb/components/CoreOrbShell.svelte';
  import ResourceRings from '$lib/orb/components/ResourceRings.svelte';
  import CameraOrbit from '$lib/orb/components/CameraOrbit.svelte';
  import { createMockOrbState } from '$lib/orb/mockState';

  const orbState = createMockOrbState();

  const cpuNorm = orbState.resources.cpu != null ? orbState.resources.cpu / 100 : null;
  const ramNorm = orbState.resources.ram != null ? orbState.resources.ram / 8_589_934_592 : null;
  const storageNorm =
    orbState.resources.storage != null ? orbState.resources.storage / 34_359_738_368 : null;
  const apiNorm = orbState.resources.apiUsage != null ? orbState.resources.apiUsage / 500 : null;
</script>

<svelte:head>
  <title>AXIS - Helios Orb</title>
</svelte:head>

<div class="h-full w-full bg-[#0A0A0F]">
  <Canvas>
    <CameraOrbit />
    <T.AmbientLight intensity={0.6} />

    <CoreOrbShell neurobus={orbState.neurobus} />
    <ResourceRings cpu={cpuNorm} ram={ramNorm} storage={storageNorm} api={apiNorm} />
  </Canvas>
</div>
