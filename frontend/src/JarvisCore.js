import React, { useEffect, useRef } from 'react';

const CORE_PARTICLES = 20000;
const SWARM_PARTICLES = 8000;

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
out float vSpark;
out float vCoreBoost;

mat2 rot(float a) {
  float c = cos(a);
  float s = sin(a);
  return mat2(c, -s, s, c);
}

float hashField(vec3 p, float t) {
  float a = sin(dot(p, vec3(2.71, 4.13, 3.37)) * 2.2 + t * 0.61 + aSeed.y * 8.0);
  float b = cos(dot(p.yzx, vec3(5.19, 2.47, 4.61)) * 1.65 - t * 0.43 + aSeed.z * 7.0);
  float c = sin((p.x - p.z) * 7.3 + p.y * 4.7 + t * 0.31 + aSeed.w * 9.0);
  return a * 0.50 + b * 0.31 + c * 0.19;
}

vec3 flowField(vec3 p, float t) {
  vec3 q = p * 3.2;
  return vec3(
    sin(q.y + t * 0.73) + cos(q.z * 1.31 - t * 0.41),
    sin(q.z * 1.17 - t * 0.57) + cos(q.x * 1.29 + t * 0.36),
    sin(q.x * 1.23 + t * 0.49) + cos(q.y * 1.37 - t * 0.32)
  ) * 0.5;
}

void main() {
  float t = uTime;
  vec3 p = aPosition;
  float stateSpeed = 0.72;
  float warp = 0.84;
  float pulse = 0.88;

  if (uState > 0.5 && uState < 1.5) {
    stateSpeed = 1.10;
    warp = 1.12;
    pulse = 1.10;
  } else if (uState > 1.5 && uState < 2.5) {
    stateSpeed = 2.10;
    warp = 1.62;
    pulse = 1.30;
  } else if (uState > 2.5 && uState < 3.5) {
    stateSpeed = 2.65;
    warp = 1.92;
    pulse = 1.45;
  } else if (uState > 3.5 && uState < 4.5) {
    stateSpeed = 1.45;
    warp = 1.30;
    pulse = 1.22;
  } else if (uState > 4.5) {
    stateSpeed = 0.42;
    warp = 0.62;
    pulse = 0.72;
  }

  if (uLayer < 0.5) {
    float radius = max(length(p), 0.0001);
    vec3 n = p / radius;
    float field = hashField(n + p * 0.34, t * stateSpeed);
    vec3 flow = flowField(p, t * stateSpeed + aSeed.x * 2.0);

    // Fluid, non-spherical breathing body.
    p += flow * (0.024 + 0.036 * uEnergy) * warp;
    p += n * field * (0.036 + 0.064 * uEnergy) * warp;

    float breathe = 1.0 + sin(t * 1.12 + aSeed.y * 4.5) * 0.012 * pulse + uBass * 0.070;
    p *= breathe;

    // More obvious asymmetry so the core does not read as a planet.
    p.x *= 0.90 + sin(t * 0.37 + aSeed.z * 2.0) * 0.075 + uMid * 0.030;
    p.y *= 1.05 + cos(t * 0.31 + aSeed.w * 2.5) * 0.090 + uBass * 0.035;
    p.z *= 0.88 + sin(t * 0.29 + aSeed.y * 3.0) * 0.075;

    // Local vortex: inner and outer particles rotate at different speeds.
    float localSpin = (0.11 + (1.0 - clamp(radius, 0.0, 1.2)) * 0.18) * stateSpeed;
    p.xz = rot(t * localSpin + field * 0.13) * p.xz;
    p.xy = rot(sin(t * 0.24 + aSeed.w * 5.0) * 0.055) * p.xy;

    // LISTENING: sound opens soft petals on the surface.
    if (uState > 0.5 && uState < 1.5) {
      float petal = sin(atan(p.y, p.x) * 5.0 + t * 1.6) * (uMid * 0.062 + uHigh * 0.024);
      p += normalize(p + vec3(0.001)) * petal;
    }

    // THINKING / EXECUTING: split the intelligence core into counter-moving lobes.
    if (uState > 1.5 && uState < 3.5) {
      float side = p.x >= 0.0 ? 1.0 : -1.0;
      float splitStrength = (uState > 2.5 ? 0.108 : 0.070) + uEnergy * 0.030;
      p.x += side * splitStrength * (0.35 + 0.65 * smoothstep(0.2, 1.0, radius));
      p.yz = rot(side * t * 0.22 * stateSpeed) * p.yz;
    }

    // SPEAKING: travelling wave follows Jarvis voice energy.
    if (uState > 3.5 && uState < 4.5) {
      float wave = sin(p.y * 11.0 - t * 8.0 + aSeed.z * 2.0) * (0.026 + uMid * 0.085);
      p.x += wave;
      p.z += cos(p.x * 9.0 - t * 6.0) * uHigh * 0.032;
    }

    // Detached wisps.
    float wispGate = smoothstep(0.84, 0.982, aSeed.x);
    float wispPulse = 0.5 + 0.5 * sin(t * (1.1 + stateSpeed) + aSeed.z * 12.0);
    p += normalize(p + vec3(0.001)) * wispGate * wispPulse * (0.045 + uEnergy * 0.15);
    p += flow * wispGate * (0.032 + uHigh * 0.070);

    // A smaller subset becomes long neural tendrils instead of random dust.
    float tendrilGate = smoothstep(0.94, 0.997, aSeed.w);
    vec3 tendrilDirection = normalize(flow + n * 0.42 + vec3(
      sin(aSeed.y * 17.0 + t * 0.5),
      cos(aSeed.z * 19.0 - t * 0.4),
      sin(aSeed.x * 13.0 + t * 0.35)
    ) * 0.22);
    float tendrilPulse = 0.45 + 0.55 * sin(t * (0.9 + stateSpeed) + aSeed.x * 18.0);
    float tendrilLength = tendrilGate * tendrilPulse * (0.10 + uEnergy * 0.28 + uMid * 0.10);
    p += tendrilDirection * tendrilLength;
  } else {
    // Free particle swarm around the intelligence body.
    float orbit = t * (0.10 + aSeed.y * 0.34) * stateSpeed + aSeed.z * 6.283185;
    p.xz = rot(orbit) * p.xz;
    p.xy = rot(sin(t * 0.13 + aSeed.w * 5.0) * (0.08 + aSeed.x * 0.12)) * p.xy;

    vec3 flow = flowField(p * 0.55, t * 0.68 + aSeed.y * 3.0);
    p += flow * (0.030 + uEnergy * 0.042 + uHigh * 0.042);
    p.y += sin(t * (0.45 + aSeed.w * 0.8) + aSeed.x * 9.0) * (0.040 + uMid * 0.070);

    // Make the swarm form loose streaming bands rather than a uniform fog.
    float band = sin(atan(p.z, p.x) * 3.0 + t * 0.38 + aSeed.z * 5.0);
    p.y += band * (0.035 + uEnergy * 0.025);

    if (uState > 1.5 && uState < 3.5) {
      float attract = 1.0 - (0.055 + uEnergy * 0.025);
      p *= attract;
    }
    if (uState > 0.5 && uState < 1.5) {
      p *= 1.0 + uBass * 0.025;
    }
  }

  float yaw = t * (0.040 + uEnergy * 0.055) * stateSpeed + uMouse.x * 0.11;
  float pitch = sin(t * 0.18) * 0.055 + uMouse.y * 0.075;
  p.xz = rot(yaw) * p.xz;
  p.yz = rot(pitch) * p.yz;

  float cameraZ = 4.15 + p.z;
  float persp = 2.96 / max(cameraZ, 0.5);
  float worldScale = uLayer < 0.5 ? 0.59 : 0.52;
  vec2 screen = vec2((p.x * persp * worldScale) / uAspect, p.y * persp * worldScale);
  screen.y += 0.078;
  gl_Position = vec4(screen, 0.0, 1.0);

  float front = clamp((p.z + 1.9) / 3.8, 0.08, 1.0);
  float radial = length(p);
  float coreBoost = uLayer < 0.5 ? (1.0 - smoothstep(0.18, 0.72, radial)) : 0.0;
  float sizeBase = mix(1.05, 3.10, aSeed.y);
  if (uLayer > 0.5) sizeBase *= 0.64;
  sizeBase *= 1.0 + uEnergy * 0.20 + uHigh * 0.26 + coreBoost * 0.34;
  sizeBase *= mix(1.0, 3.35, uGlowPass);
  gl_PointSize = sizeBase * uPixelRatio * (0.80 + persp * 0.34);

  float flicker = 0.73 + 0.27 * sin(t * (1.35 + uEnergy * 3.2) + aSeed.z * 13.0);
  float densityFade = uLayer < 0.5 ? mix(0.80, 1.0, smoothstep(0.0, 1.05, radial)) : 1.0;
  vAlpha = front * flicker * densityFade * mix(0.54, 1.0, aSeed.w);
  vAlpha *= 1.0 + coreBoost * 0.75;
  if (uLayer > 0.5) vAlpha *= 0.34 + uEnergy * 0.30;
  if (uGlowPass > 0.5) vAlpha *= 0.15;

  vHeat = clamp(0.32 + front * 0.48 + uEnergy * 0.26 + uBass * 0.17 + coreBoost * 0.42, 0.0, 1.0);
  vLayer = uLayer;
  vSpark = smoothstep(0.80, 1.0, aSeed.x) * (0.52 + uHigh * 0.9);
  vCoreBoost = coreBoost;
}
`;

const FRAGMENT_SHADER = `#version 300 es
precision highp float;

in float vAlpha;
in float vHeat;
in float vLayer;
in float vSpark;
in float vCoreBoost;
out vec4 outColor;

void main() {
  vec2 uv = gl_PointCoord - vec2(0.5);
  float d = length(uv) * 2.0;
  float halo = 1.0 - smoothstep(0.06, 1.0, d);
  float core = 1.0 - smoothstep(0.0, 0.31, d);
  if (halo <= 0.002) discard;

  vec3 deep = vec3(0.06, 0.42, 0.64);
  vec3 cyan = vec3(0.20, 0.86, 1.0);
  vec3 whiteHot = vec3(0.93, 1.0, 1.0);
  vec3 color = mix(deep, cyan, vHeat);
  color = mix(color, whiteHot, clamp(core * 0.48 + vSpark * 0.22 + vCoreBoost * 0.28, 0.0, 0.86));
  if (vLayer > 0.5) color *= vec3(0.70, 0.94, 1.10);

  float alpha = halo * vAlpha * (0.50 + core * 0.82 + vSpark * 0.16 + vCoreBoost * 0.20);
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

function buildCoreParticles(count) {
  const positions = new Float32Array(count * 3);
  const seeds = new Float32Array(count * 4);

  for (let i = 0; i < count; i += 1) {
    const dir = randomDirection();
    const group = Math.random();
    let radius;
    if (group < 0.60) {
      radius = 0.08 + Math.pow(Math.random(), 0.76) * 0.60;
    } else if (group < 0.91) {
      radius = 0.56 + Math.pow(Math.random(), 0.58) * 0.43;
    } else {
      radius = 0.90 + Math.random() * 0.26;
    }

    positions[i * 3] = dir[0] * radius * (0.88 + Math.random() * 0.13);
    positions[i * 3 + 1] = dir[1] * radius * (0.95 + Math.random() * 0.18);
    positions[i * 3 + 2] = dir[2] * radius * (0.84 + Math.random() * 0.14);

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
    const radius = 1.10 + Math.pow(Math.random(), 0.42) * 3.25;
    const spiral = Math.sin(angle * 2.3 + Math.random() * 2.2) * 0.40;
    const height = (Math.random() - 0.5) * (1.55 + Math.random() * 1.9);

    positions[i * 3] = Math.cos(angle) * radius;
    positions[i * 3 + 1] = height + spiral;
    positions[i * 3 + 2] = Math.sin(angle) * radius * (0.47 + Math.random() * 0.60);

    seeds[i * 4] = Math.random();
    seeds[i * 4 + 1] = Math.random();
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
    } catch (error) {
      console.error(error);
      canvas.dataset.webgl = 'shader-error';
      return undefined;
    }

    const coreData = buildCoreParticles(CORE_PARTICLES);
    const swarmData = buildSwarmParticles(SWARM_PARTICLES);
    const coreGpu = createParticleVao(gl, program, coreData);
    const swarmGpu = createParticleVao(gl, program, swarmData);

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
    let energy = 0.13;
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

    gl.useProgram(program);
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
      const baseEnergy = state === 0 ? 0.15 : state === 1 ? 0.42 : state === 2 ? 0.78 : state === 3 ? 0.96 : state === 4 ? 0.64 : 0.28;
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
      [coreGpu, swarmGpu].forEach((gpu) => {
        gl.deleteBuffer(gpu.positionBuffer);
        gl.deleteBuffer(gpu.seedBuffer);
        gl.deleteVertexArray(gpu.vao);
      });
      gl.deleteProgram(program);
    };
  }, [audioBandsRef, audioLevelRef, visualStateRef]);

  return <canvas id="space" ref={canvasRef} aria-hidden="true" />;
}
