import React, { useEffect, useRef } from 'react';

const CORE_PARTICLES = 18000;
const SWARM_PARTICLES = 6000;
const FILAMENT_PARTICLES = 4000;

export const WEBGL_PARTICLE_COUNT = CORE_PARTICLES + SWARM_PARTICLES + FILAMENT_PARTICLES;

const VERTEX_SHADER = `#version 300 es
precision highp float;

in vec3 aPosition;
in vec4 aSeed;

uniform float uTime;
uniform float uEnergy;
uniform float uBass;
uniform float uMid;
uniform float uHigh;
uniform float uState;
uniform float uAspect;
uniform float uPixelRatio;
uniform float uLayer;
uniform float uGlowPass;
uniform vec2 uMouse;

out float vAlpha;
out float vHeat;
out float vLayer;
out float vAlong;
out float vSpark;

mat2 rot(float a) {
  float c = cos(a);
  float s = sin(a);
  return mat2(c, -s, s, c);
}

vec3 flowField(vec3 p, float t) {
  vec3 q = p * 3.0;
  return vec3(
    sin(q.y + t * 0.72) + cos(q.z * 1.27 - t * 0.39),
    sin(q.z * 1.13 - t * 0.55) + cos(q.x * 1.25 + t * 0.34),
    sin(q.x * 1.19 + t * 0.47) + cos(q.y * 1.31 - t * 0.30)
  ) * 0.5;
}

float organicNoise(vec3 p, float t) {
  float a = sin(dot(p, vec3(2.7, 4.1, 3.3)) * 2.0 + t * 0.60 + aSeed.y * 6.0);
  float b = cos(dot(p.yzx, vec3(5.1, 2.4, 4.6)) * 1.5 - t * 0.42 + aSeed.z * 7.0);
  float c = sin((p.x - p.z) * 7.0 + p.y * 4.4 + t * 0.28 + aSeed.w * 8.0);
  return a * 0.50 + b * 0.31 + c * 0.19;
}

void main() {
  float t = uTime;
  float along = clamp(aSeed.x, 0.0, 1.0);
  vec3 p = aPosition;

  float stateSpeed = 0.72;
  float warp = 0.84;
  float reach = 1.0;

  if (uState > 0.5 && uState < 1.5) {
    stateSpeed = 1.15;
    warp = 1.14;
    reach = 1.04 + uBass * 0.10;
  } else if (uState > 1.5 && uState < 2.5) {
    stateSpeed = 2.05;
    warp = 1.58;
    reach = 1.10 + uEnergy * 0.08;
  } else if (uState > 2.5 && uState < 3.5) {
    stateSpeed = 2.55;
    warp = 1.90;
    reach = 1.14 + uEnergy * 0.10;
  } else if (uState > 3.5 && uState < 4.5) {
    stateSpeed = 1.55;
    warp = 1.30;
    reach = 1.05 + uMid * 0.08;
  } else if (uState > 4.5) {
    stateSpeed = 0.45;
    warp = 0.66;
    reach = 0.96;
  }

  if (uLayer < 0.5) {
    float radius = max(length(p), 0.0001);
    vec3 n = p / radius;
    vec3 flow = flowField(p, t * stateSpeed + aSeed.x * 1.8);
    float noise = organicNoise(n + p * 0.3, t * stateSpeed);

    p += flow * (0.020 + uEnergy * 0.034) * warp;
    p += n * noise * (0.030 + uEnergy * 0.055) * warp;

    float breathe = 1.0 + sin(t * 1.05 + aSeed.y * 4.0) * 0.010 + uBass * 0.060;
    p *= breathe;

    p.x *= 0.90 + sin(t * 0.34 + aSeed.z * 2.0) * 0.065 + uMid * 0.024;
    p.y *= 1.05 + cos(t * 0.29 + aSeed.w * 2.4) * 0.075 + uBass * 0.030;
    p.z *= 0.88 + sin(t * 0.27 + aSeed.y * 3.0) * 0.060;

    float localSpin = (0.09 + (1.0 - clamp(radius, 0.0, 1.2)) * 0.16) * stateSpeed;
    p.xz = rot(t * localSpin + noise * 0.10) * p.xz;

    if (uState > 0.5 && uState < 1.5) {
      float voiceWave = sin(atan(p.y, p.x) * 5.0 + t * 1.6) * (uMid * 0.055 + uHigh * 0.020);
      p += normalize(p + vec3(0.001)) * voiceWave;
    }

    if (uState > 1.5 && uState < 3.5) {
      float side = p.x >= 0.0 ? 1.0 : -1.0;
      p.x += side * (0.050 + uEnergy * 0.035) * smoothstep(0.20, 1.0, radius);
      p.yz = rot(side * t * 0.18 * stateSpeed) * p.yz;
    }

    if (uState > 3.5 && uState < 4.5) {
      float speech = sin(p.y * 10.0 - t * 7.6 + aSeed.z * 2.0) * (0.020 + uMid * 0.075);
      p.x += speech;
      p.z += cos(p.x * 8.4 - t * 5.7) * uHigh * 0.028;
    }

    float wisp = smoothstep(0.90, 0.995, aSeed.w);
    p += normalize(p + vec3(0.001)) * wisp * (0.025 + uEnergy * 0.10) * (0.5 + 0.5 * sin(t * 1.4 + aSeed.z * 10.0));
  } else if (uLayer < 1.5) {
    float orbit = t * (0.08 + aSeed.y * 0.28) * stateSpeed + aSeed.z * 6.283185;
    p.xz = rot(orbit) * p.xz;
    p.xy = rot(sin(t * 0.12 + aSeed.w * 5.0) * (0.055 + aSeed.x * 0.08)) * p.xy;

    vec3 flow = flowField(p * 0.52, t * 0.62 + aSeed.y * 3.0);
    p += flow * (0.020 + uEnergy * 0.030 + uHigh * 0.030);
    p.y += sin(t * (0.40 + aSeed.w * 0.70) + aSeed.x * 9.0) * (0.026 + uMid * 0.045);

    if (uState > 1.5 && uState < 3.5) p *= 0.96;
    if (uState > 0.5 && uState < 1.5) p *= 1.0 + uBass * 0.018;
  } else {
    float phase = aSeed.y * 6.283185;
    vec3 direction = normalize(p + vec3(0.001));
    vec3 flow = flowField(p * 0.78, t * 0.82 + phase);
    float wave = sin(along * 17.0 - t * (2.2 + stateSpeed) + phase * 2.0);
    float flutter = cos(along * 9.0 + t * 0.70 + phase);

    p *= mix(0.98, reach, smoothstep(0.10, 1.0, along));
    p += flow * (0.008 + along * 0.024 + uMid * 0.018);
    p += direction * wave * (0.005 + along * 0.018 + uHigh * 0.016);
    p.y += flutter * (0.005 + along * 0.012);
  }

  float yaw = t * (0.034 + uEnergy * 0.048) * stateSpeed + uMouse.x * 0.10;
  float pitch = sin(t * 0.17) * 0.046 + uMouse.y * 0.068;
  p.xz = rot(yaw) * p.xz;
  p.yz = rot(pitch) * p.yz;

  float cameraZ = 4.05 + p.z;
  float persp = 3.02 / max(cameraZ, 0.52);
  float worldScale = uLayer < 0.5 ? 0.62 : (uLayer < 1.5 ? 0.50 : 0.58);
  vec2 screen = vec2((p.x * persp * worldScale) / uAspect, p.y * persp * worldScale);
  screen.y += 0.075;
  gl_Position = vec4(screen, 0.0, 1.0);

  float front = clamp((p.z + 1.9) / 3.8, 0.10, 1.0);
  float radial = length(p);
  float coreBoost = uLayer < 0.5 ? 1.0 - smoothstep(0.12, 0.55, radial) : 0.0;

  float sizeBase = mix(0.95, 2.75, aSeed.y);
  if (uLayer > 0.5 && uLayer < 1.5) sizeBase *= 0.60;
  if (uLayer > 1.5) sizeBase = mix(0.60, 1.48, aSeed.z) * mix(1.0, 0.72, along);
  sizeBase *= 1.0 + uEnergy * 0.16 + uHigh * 0.20 + coreBoost * 0.10;
  sizeBase *= mix(1.0, uLayer > 1.5 ? 3.35 : 3.0, uGlowPass);
  gl_PointSize = sizeBase * uPixelRatio * (0.82 + persp * 0.32);

  float flicker = 0.78 + 0.22 * sin(t * (1.25 + uEnergy * 2.8) + aSeed.z * 12.0);
  vAlpha = front * flicker * mix(0.58, 0.96, aSeed.w);
  if (uLayer < 0.5) vAlpha *= 0.86 + coreBoost * 0.28;
  if (uLayer > 0.5 && uLayer < 1.5) vAlpha *= 0.22 + uEnergy * 0.22;
  if (uLayer > 1.5) {
    float taper = smoothstep(0.0, 0.10, along) * (1.0 - smoothstep(0.82, 1.0, along));
    vAlpha *= taper * (0.56 + uEnergy * 0.22);
  }
  if (uGlowPass > 0.5) vAlpha *= uLayer > 1.5 ? 0.13 : 0.09;

  vHeat = clamp(0.30 + front * 0.44 + uEnergy * 0.22 + uBass * 0.12 + coreBoost * 0.18, 0.0, 1.0);
  vLayer = uLayer;
  vAlong = along;
  vSpark = smoothstep(0.88, 1.0, aSeed.z) * (0.30 + uHigh * 0.70);
}
`;

const FRAGMENT_SHADER = `#version 300 es
precision highp float;

in float vAlpha;
in float vHeat;
in float vLayer;
in float vAlong;
in float vSpark;
out vec4 outColor;

void main() {
  vec2 uv = gl_PointCoord - vec2(0.5);
  float d = length(uv) * 2.0;
  float halo = 1.0 - smoothstep(0.07, 1.0, d);
  float pointCore = 1.0 - smoothstep(0.0, 0.32, d);
  if (halo <= 0.002) discard;

  vec3 deep = vec3(0.035, 0.30, 0.52);
  vec3 cyan = vec3(0.10, 0.73, 0.97);
  vec3 electric = vec3(0.43, 0.92, 1.0);
  vec3 color = mix(deep, cyan, vHeat);
  color = mix(color, electric, clamp(pointCore * 0.18 + vSpark * 0.10, 0.0, 0.34));

  if (vLayer > 0.5 && vLayer < 1.5) color *= vec3(0.68, 0.93, 1.08);
  if (vLayer > 1.5) {
    float filamentPulse = 0.30 + 0.14 * sin(vAlong * 16.0);
    color = mix(color, vec3(0.30, 0.88, 1.0), filamentPulse);
  }

  float alpha = halo * vAlpha * (0.48 + pointCore * 0.62 + vSpark * 0.10);
  outColor = vec4(color, alpha);
}
`;

function stateToCode(state) {
  switch (String(state || 'IDLE').toUpperCase()) {
    case 'LISTENING': return 1;
    case 'THINKING': return 2;
    case 'EXECUTING': return 3;
    case 'SPEAKING': return 4;
    case 'ERROR': return 5;
    default: return 0;
  }
}

function createShader(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(`Shader compile error: ${log}`);
  }
  return shader;
}

function createProgram(gl) {
  const vertex = createShader(gl, gl.VERTEX_SHADER, VERTEX_SHADER);
  const fragment = createShader(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
  const program = gl.createProgram();
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  gl.deleteShader(vertex);
  gl.deleteShader(fragment);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    const log = gl.getProgramInfoLog(program);
    gl.deleteProgram(program);
    throw new Error(`Shader link error: ${log}`);
  }
  return program;
}

function randomDirection() {
  const z = Math.random() * 2 - 1;
  const theta = Math.random() * Math.PI * 2;
  const r = Math.sqrt(Math.max(0, 1 - z * z));
  return [Math.cos(theta) * r, z, Math.sin(theta) * r];
}

function normalize3(v) {
  const len = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / len, v[1] / len, v[2] / len];
}

function cross3(a, b) {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}

function cubicBezier(a, b, c, d, t) {
  const mt = 1 - t;
  const mt2 = mt * mt;
  const t2 = t * t;
  return [
    a[0] * mt2 * mt + 3 * b[0] * mt2 * t + 3 * c[0] * mt * t2 + d[0] * t2 * t,
    a[1] * mt2 * mt + 3 * b[1] * mt2 * t + 3 * c[1] * mt * t2 + d[1] * t2 * t,
    a[2] * mt2 * mt + 3 * b[2] * mt2 * t + 3 * c[2] * mt * t2 + d[2] * t2 * t,
  ];
}

function buildCoreParticles(count) {
  const positions = new Float32Array(count * 3);
  const seeds = new Float32Array(count * 4);

  for (let i = 0; i < count; i += 1) {
    const dir = randomDirection();
    const group = Math.random();
    let radius;
    if (group < 0.58) radius = 0.10 + Math.pow(Math.random(), 0.78) * 0.58;
    else if (group < 0.91) radius = 0.55 + Math.pow(Math.random(), 0.58) * 0.43;
    else radius = 0.89 + Math.random() * 0.24;

    positions[i * 3] = dir[0] * radius * (0.89 + Math.random() * 0.12);
    positions[i * 3 + 1] = dir[1] * radius * (0.96 + Math.random() * 0.17);
    positions[i * 3 + 2] = dir[2] * radius * (0.85 + Math.random() * 0.13);

    seeds[i * 4] = Math.random();
    seeds[i * 4 + 1] = Math.random();
    seeds[i * 4 + 2] = Math.random();
    seeds[i * 4 + 3] = Math.random();
  }
  return { positions, seeds };
}

function buildSwarmParticles(count) {
  const positions = new Float32Array(count * 3);
  const seeds = new Float32Array(count * 4);

  for (let i = 0; i < count; i += 1) {
    const angle = Math.random() * Math.PI * 2;
    const radius = 1.10 + Math.pow(Math.random(), 0.46) * 3.0;
    const band = i % 6;
    const bandOffset = (band - 2.5) * 0.12;
    const spiral = Math.sin(angle * (1.45 + band * 0.17) + band * 0.7) * 0.22;

    positions[i * 3] = Math.cos(angle) * radius;
    positions[i * 3 + 1] = bandOffset + spiral + (Math.random() - 0.5) * 0.58;
    positions[i * 3 + 2] = Math.sin(angle) * radius * (0.54 + Math.random() * 0.42);

    seeds[i * 4] = Math.random();
    seeds[i * 4 + 1] = Math.random();
    seeds[i * 4 + 2] = Math.random();
    seeds[i * 4 + 3] = Math.random();
  }
  return { positions, seeds };
}

function buildFilamentParticles(count) {
  const positions = new Float32Array(count * 3);
  const seeds = new Float32Array(count * 4);
  const filamentCount = 24;
  const pointsPerFilament = Math.ceil(count / filamentCount);

  const filaments = Array.from({ length: filamentCount }, (_, index) => {
    const dir = normalize3(randomDirection());
    const fallback = Math.abs(dir[1]) > 0.82 ? [1, 0, 0] : [0, 1, 0];
    const side = normalize3(cross3(dir, fallback));
    const side2 = normalize3(cross3(dir, side));
    const startRadius = 0.48 + Math.random() * 0.18;
    const endRadius = 1.35 + Math.random() * 0.85;
    const bend = (Math.random() - 0.5) * 0.72;
    const bend2 = (Math.random() - 0.5) * 0.48;

    const start = dir.map((v) => v * startRadius);
    const end = [
      dir[0] * endRadius + side[0] * bend + side2[0] * bend2,
      dir[1] * endRadius + side[1] * bend + side2[1] * bend2,
      dir[2] * endRadius + side[2] * bend + side2[2] * bend2,
    ];
    const c1 = [
      start[0] + dir[0] * 0.32 + side[0] * bend * 0.58,
      start[1] + dir[1] * 0.32 + side[1] * bend * 0.58,
      start[2] + dir[2] * 0.32 + side[2] * bend * 0.58,
    ];
    const c2 = [
      end[0] - dir[0] * 0.46 + side2[0] * bend2 * 0.80,
      end[1] - dir[1] * 0.46 + side2[1] * bend2 * 0.80,
      end[2] - dir[2] * 0.46 + side2[2] * bend2 * 0.80,
    ];
    return { start, c1, c2, end, index };
  });

  for (let i = 0; i < count; i += 1) {
    const filamentIndex = Math.min(filamentCount - 1, Math.floor(i / pointsPerFilament));
    const local = i % pointsPerFilament;
    const u = local / Math.max(1, pointsPerFilament - 1);
    const f = filaments[filamentIndex];
    const p = cubicBezier(f.start, f.c1, f.c2, f.end, u);
    const thickness = (0.008 + (1 - u) * 0.012) * (0.7 + Math.random() * 0.6);

    positions[i * 3] = p[0] + (Math.random() - 0.5) * thickness;
    positions[i * 3 + 1] = p[1] + (Math.random() - 0.5) * thickness;
    positions[i * 3 + 2] = p[2] + (Math.random() - 0.5) * thickness;

    seeds[i * 4] = u;
    seeds[i * 4 + 1] = filamentIndex / filamentCount;
    seeds[i * 4 + 2] = Math.random();
    seeds[i * 4 + 3] = Math.random();
  }
  return { positions, seeds };
}

function createParticleVao(gl, program, data) {
  const vao = gl.createVertexArray();
  gl.bindVertexArray(vao);

  const positionBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, data.positions, gl.STATIC_DRAW);
  const positionLocation = gl.getAttribLocation(program, 'aPosition');
  gl.enableVertexAttribArray(positionLocation);
  gl.vertexAttribPointer(positionLocation, 3, gl.FLOAT, false, 0, 0);

  const seedBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, seedBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, data.seeds, gl.STATIC_DRAW);
  const seedLocation = gl.getAttribLocation(program, 'aSeed');
  gl.enableVertexAttribArray(seedLocation);
  gl.vertexAttribPointer(seedLocation, 4, gl.FLOAT, false, 0, 0);

  gl.bindVertexArray(null);
  return { vao, positionBuffer, seedBuffer };
}

export default function JarvisCore({ visualStateRef, audioLevelRef, audioBandsRef }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const gl = canvas.getContext('webgl2', {
      alpha: false,
      antialias: false,
      depth: false,
      powerPreference: 'high-performance',
      preserveDrawingBuffer: false,
    });

    if (!gl) {
      canvas.dataset.webgl = 'unsupported';
      return undefined;
    }

    let program;
    try {
      program = createProgram(gl);
      canvas.dataset.webgl = 'ready';
    } catch (error) {
      console.error(error);
      canvas.dataset.webgl = 'shader-error';
      return undefined;
    }

    const coreData = buildCoreParticles(CORE_PARTICLES);
    const swarmData = buildSwarmParticles(SWARM_PARTICLES);
    const filamentData = buildFilamentParticles(FILAMENT_PARTICLES);
    const coreGpu = createParticleVao(gl, program, coreData);
    const swarmGpu = createParticleVao(gl, program, swarmData);
    const filamentGpu = createParticleVao(gl, program, filamentData);

    const uniforms = {
      time: gl.getUniformLocation(program, 'uTime'),
      energy: gl.getUniformLocation(program, 'uEnergy'),
      bass: gl.getUniformLocation(program, 'uBass'),
      mid: gl.getUniformLocation(program, 'uMid'),
      high: gl.getUniformLocation(program, 'uHigh'),
      state: gl.getUniformLocation(program, 'uState'),
      aspect: gl.getUniformLocation(program, 'uAspect'),
      pixelRatio: gl.getUniformLocation(program, 'uPixelRatio'),
      layer: gl.getUniformLocation(program, 'uLayer'),
      glowPass: gl.getUniformLocation(program, 'uGlowPass'),
      mouse: gl.getUniformLocation(program, 'uMouse'),
    };

    let raf = 0;
    let width = 1;
    let height = 1;
    let dpr = 1;
    let mouseX = 0;
    let mouseY = 0;
    let smoothX = 0;
    let smoothY = 0;
    let energy = 0.14;
    const start = performance.now();

    const resize = () => {
      width = Math.max(1, window.innerWidth);
      height = Math.max(1, window.innerHeight);
      dpr = Math.min(window.devicePixelRatio || 1, 1.8);
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      gl.viewport(0, 0, canvas.width, canvas.height);
    };

    const onPointerMove = (event) => {
      mouseX = (event.clientX / width - 0.5) * 2;
      mouseY = (event.clientY / height - 0.5) * 2;
    };

    gl.disable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
    gl.clearColor(0.002, 0.008, 0.012, 1.0);

    const drawLayer = (gpu, count, layer) => {
      gl.uniform1f(uniforms.layer, layer);
      gl.bindVertexArray(gpu.vao);
      gl.uniform1f(uniforms.glowPass, 1.0);
      gl.drawArrays(gl.POINTS, 0, count);
      gl.uniform1f(uniforms.glowPass, 0.0);
      gl.drawArrays(gl.POINTS, 0, count);
    };

    const render = (now) => {
      const time = (now - start) * 0.001;
      const state = stateToCode(visualStateRef.current);
      const audio = audioLevelRef.current || 0;
      const bands = audioBandsRef.current || { bass: 0, mid: 0, high: 0 };
      const baseEnergy = state === 0 ? 0.16 : state === 1 ? 0.43 : state === 2 ? 0.78 : state === 3 ? 0.96 : state === 4 ? 0.64 : 0.28;
      const targetEnergy = Math.min(1.40, baseEnergy + audio * 0.64 + (bands.bass || 0) * 0.20);
      energy += (targetEnergy - energy) * 0.068;
      smoothX += (mouseX - smoothX) * 0.025;
      smoothY += (mouseY - smoothY) * 0.025;

      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.useProgram(program);
      gl.uniform1f(uniforms.time, time);
      gl.uniform1f(uniforms.energy, energy);
      gl.uniform1f(uniforms.bass, bands.bass || 0);
      gl.uniform1f(uniforms.mid, bands.mid || 0);
      gl.uniform1f(uniforms.high, bands.high || 0);
      gl.uniform1f(uniforms.state, state);
      gl.uniform1f(uniforms.aspect, Math.max(0.6, width / height));
      gl.uniform1f(uniforms.pixelRatio, dpr);
      gl.uniform2f(uniforms.mouse, smoothX, smoothY);

      drawLayer(swarmGpu, SWARM_PARTICLES, 1.0);
      drawLayer(filamentGpu, FILAMENT_PARTICLES, 2.0);
      drawLayer(coreGpu, CORE_PARTICLES, 0.0);

      gl.bindVertexArray(null);
      raf = requestAnimationFrame(render);
    };

    resize();
    window.addEventListener('resize', resize);
    window.addEventListener('pointermove', onPointerMove);
    raf = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
      window.removeEventListener('pointermove', onPointerMove);
      [coreGpu, swarmGpu, filamentGpu].forEach((gpu) => {
        gl.deleteBuffer(gpu.positionBuffer);
        gl.deleteBuffer(gpu.seedBuffer);
        gl.deleteVertexArray(gpu.vao);
      });
      gl.deleteProgram(program);
    };
  }, [audioBandsRef, audioLevelRef, visualStateRef]);

  return <canvas id="space" ref={canvasRef} aria-hidden="true" />;
}
