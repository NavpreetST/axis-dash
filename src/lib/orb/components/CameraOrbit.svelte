<script lang="ts">
  import { T, useTask } from '@threlte/core';
  import { PerspectiveCamera } from 'three';

  let camera = $state<PerspectiveCamera>();
  let angle = $state(0);

  useTask((delta) => {
    angle += delta * 0.12;
    if (camera) {
      const r = 5;
      camera.position.x = Math.sin(angle) * r;
      camera.position.z = Math.cos(angle) * r;
      camera.position.y = 0.8;
      camera.lookAt(0, 0, 0);
    }
  });
</script>

<T.PerspectiveCamera bind:ref={camera} makeDefault position={[0, 0.8, 5]} fov={45} />
