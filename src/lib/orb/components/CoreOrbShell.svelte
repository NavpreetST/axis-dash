<script lang="ts">
  import { T, useTask } from '@threlte/core';
  import { DoubleSide, BufferGeometry, Float32BufferAttribute } from 'three';
  import type { NeuroBusState } from '$lib/orb/types';

  const VERTEX = `
uniform float uTime;
uniform float uNovelty;
uniform float uThreat;
uniform float uPatience;
uniform float uAwake;

varying vec3 vNormal;
varying vec3 vViewPosition;
varying float vDisplacement;

float hash(vec3 p) {
  return fract(sin(dot(p, vec3(12.9898, 78.233, 45.5432))) * 43758.5453);
}

float noise3(vec3 p) {
  vec3 i = floor(p);
  vec3 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  float a = hash(i);
  float b = hash(i + vec3(1, 0, 0));
  float c = hash(i + vec3(0, 1, 0));
  float d = hash(i + vec3(1, 1, 0));
  float e = hash(i + vec3(0, 0, 1));
  float f_ = hash(i + vec3(1, 0, 1));
  float g = hash(i + vec3(0, 1, 1));
  float h = hash(i + vec3(1, 1, 1));
  float mx1 = mix(a, b, f.x);
  float mx2 = mix(c, d, f.x);
  float mx3 = mix(e, f_, f.x);
  float mx4 = mix(g, h, f.x);
  float my1 = mix(mx1, mx2, f.y);
  float my2 = mix(mx3, mx4, f.y);
  return mix(my1, my2, f.z);
}

float fbm(vec3 p) {
  float v = 0.0;
  float a = 0.5;
  float freq = 1.0;
  for (int i = 0; i < 3; i++) {
    v += a * noise3(p * freq);
    freq *= 2.0;
    a *= 0.5;
  }
  return v;
}

void main() {
  float freq = 3.0 + uNovelty * 3.0;
  float speed = 0.4 + uThreat * 1.2;
  vec3 p = position * freq + uTime * speed;
  float displacement = fbm(p) * 0.18 * uAwake;

  float breath = sin(uTime * 0.4 * uPatience) * 0.04 * uAwake;

  vec3 newPos = position + normal * (displacement + breath);

  vec4 mvPosition = modelViewMatrix * vec4(newPos, 1.0);
  vNormal = normalize(normalMatrix * normal);
  vViewPosition = -mvPosition.xyz;
  vDisplacement = displacement;

  gl_Position = projectionMatrix * mvPosition;
}
`;

  const FRAGMENT = `
uniform float uThreat;
uniform float uTrust;
uniform float uAttention;
uniform float uReward;

varying vec3 vNormal;
varying vec3 vViewPosition;

void main() {
  vec3 viewDir = normalize(vViewPosition);
  float fresnel = pow(1.0 - abs(dot(vNormal, viewDir)), 3.0);
  float attentionSharp = 1.0 + (1.0 - uAttention) * 3.0;
  fresnel = pow(fresnel, attentionSharp);

  vec3 gold = vec3(1.0, 0.78, 0.34);
  vec3 threatColor = vec3(1.0, 0.1, 0.1);
  vec3 trustColor = vec3(0.0, 0.85, 0.95);

  vec3 color = gold;
  color = mix(color, threatColor, uThreat * 0.5);
  color = mix(color, trustColor, uTrust * 0.35);

  float brightness = 0.25 + uReward * 0.75;
  color *= brightness;

  float glow = fresnel * uAttention;
  color += vec3(0.85, 0.75, 0.55) * glow * 0.6;

  float alpha = 0.5 + fresnel * 0.5 * uAttention;
  alpha *= (0.4 + uReward * 0.6);

  gl_FragColor = vec4(color, alpha);
}
`;

  const R = 1;
  const SEG = 64;

  function s2c(theta: number, phi: number, r: number = R): [number, number, number] {
    return [
      r * Math.sin(theta) * Math.cos(phi),
      r * Math.cos(theta),
      r * Math.sin(theta) * Math.sin(phi)
    ];
  }

  function addArc(
    positions: number[],
    indices: number[],
    theta: number,
    width: number,
    phiStart: number,
    phiEnd: number
  ) {
    const t0 = theta - width / 2;
    const t1 = theta + width / 2;
    const n = Math.max(2, Math.ceil(((phiEnd - phiStart) / (Math.PI * 2)) * SEG));
    const dPhi = (phiEnd - phiStart) / n;
    const base = positions.length / 3;

    for (let i = 0; i <= n; i++) {
      const phi = phiStart + i * dPhi;
      positions.push(...s2c(t0, phi), ...s2c(t1, phi));
    }

    for (let i = 0; i < n; i++) {
      const a = base + i * 2;
      const b = base + i * 2 + 1;
      const c = base + (i + 1) * 2;
      const d = base + (i + 1) * 2 + 1;
      indices.push(a, c, b, b, c, d);
    }
  }

  function addVertArc(
    positions: number[],
    indices: number[],
    phi: number,
    thetaStart: number,
    thetaEnd: number,
    width: number
  ) {
    const p0 = phi - width / 2;
    const p1 = phi + width / 2;
    const n = Math.max(2, Math.ceil(((thetaEnd - thetaStart) / Math.PI) * (SEG / 2)));
    const dTheta = (thetaEnd - thetaStart) / n;
    const base = positions.length / 3;

    for (let i = 0; i <= n; i++) {
      const t = thetaStart + i * dTheta;
      positions.push(...s2c(t, p0), ...s2c(t, p1));
    }

    for (let i = 0; i < n; i++) {
      const a = base + i * 2;
      const b = base + i * 2 + 1;
      const c = base + (i + 1) * 2;
      const d = base + (i + 1) * 2 + 1;
      indices.push(a, c, b, b, c, d);
    }
  }

  function buildShellGeometry(): BufferGeometry {
    const positions: number[] = [];
    const indices: number[] = [];

    // Latitudinal arcs — staggered gaps so no single continuous shell
    addArc(positions, indices, 0.25, 0.05, 0.4, Math.PI * 1.5);
    addArc(positions, indices, 0.42, 0.05, Math.PI * 0.3, Math.PI * 1.8);
    addArc(positions, indices, 0.58, 0.06, 0.0, Math.PI * 1.6);
    addArc(positions, indices, 0.75, 0.05, Math.PI * 0.4, Math.PI * 1.9);
    addArc(positions, indices, 0.92, 0.06, 0.1, Math.PI * 1.5);
    addArc(positions, indices, 1.1, 0.05, Math.PI * 0.3, Math.PI * 1.3);
    addArc(positions, indices, 1.3, 0.04, 0.0, Math.PI * 1.4);
    addArc(positions, indices, 1.5, 0.04, Math.PI * 0.5, Math.PI * 1.2);

    // Longitudinal structural arcs
    addVertArc(positions, indices, 0.0, 0.15, 1.6, 0.04);
    addVertArc(positions, indices, Math.PI * 0.5, 0.2, 1.5, 0.035);
    addVertArc(positions, indices, Math.PI * 1.0, 0.12, 1.7, 0.05);
    addVertArc(positions, indices, Math.PI * 1.5, 0.25, 1.4, 0.03);

    const geo = new BufferGeometry();
    geo.setAttribute('position', new Float32BufferAttribute(positions, 3));
    geo.setIndex(indices);
    geo.computeVertexNormals();
    return geo;
  }

  const shellGeometry = buildShellGeometry();

  let { neurobus }: { neurobus: NeuroBusState | null } = $props();

  const IDLE = {
    reward: 0,
    novelty: 0,
    attention: 0,
    patience: 0.3,
    threat: 0,
    trust: 0,
    awake: 0
  };
  let current = $state({ ...IDLE });

  const TARGET = $derived(
    neurobus
      ? {
          reward: neurobus.reward ?? 0,
          novelty: neurobus.novelty ?? 0,
          attention: neurobus.attention ?? 0,
          patience: neurobus.patience ?? 1,
          threat: neurobus.threat ?? 0,
          trust: neurobus.trust ?? 0,
          awake: 1
        }
      : { ...IDLE }
  );

  const uniforms = {
    uTime: { value: 0 },
    uNovelty: { value: 0 },
    uThreat: { value: 0 },
    uTrust: { value: 0 },
    uAttention: { value: 0 },
    uReward: { value: 0 },
    uPatience: { value: 0.3 },
    uAwake: { value: 0 }
  };

  const LERP_SPEED = 2;

  useTask((delta) => {
    const dt = Math.min(delta, 0.05);
    for (const k of [
      'reward',
      'novelty',
      'attention',
      'patience',
      'threat',
      'trust',
      'awake'
    ] as const) {
      current[k] += (TARGET[k] - current[k]) * dt * LERP_SPEED;
    }
    uniforms.uTime.value += dt;
    uniforms.uNovelty.value = current.novelty;
    uniforms.uThreat.value = current.threat;
    uniforms.uTrust.value = current.trust;
    uniforms.uAttention.value = current.attention;
    uniforms.uReward.value = current.reward;
    uniforms.uPatience.value = Math.max(current.patience, 0.1);
    uniforms.uAwake.value = current.awake;
  });
</script>

<T.Mesh geometry={shellGeometry}>
  <T.ShaderMaterial
    {uniforms}
    vertexShader={VERTEX}
    fragmentShader={FRAGMENT}
    transparent={true}
    side={DoubleSide}
    depthWrite={false}
  />
</T.Mesh>
