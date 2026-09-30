import React, { useEffect, useRef } from 'react';

const CORE_PARTICLES = 22000;
const DUST_PARTICLES = 6000;

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

mat2 rot(float a) {
  float c = cos(a);
  float s = sin(a);
  return mat2(c, -s, s, c);
}

float organicField(vec3 p, float t) {
  float n1 = sin(dot(p, vec3(3.17, 4.31, 2.73)) * 2.1 + t * 0.72 + aSeed.y * 6.2831);
  float n2 = sin(dot(p.yzx, vec3(5.31, 2.27, 4.83)) * 1.6 - t * 0.49 + aSeed.z * 5.21);
  float n3 = cos((p.x + p.z) * 8.2 + p.y * 5.4 + t * 0.33 + aSeed.w * 7.17);
  return n1 * 0.52 + n2 * 0.31 + n3 * 0.17;
}

void main() {
  float t = uTime;
  vec3 p = aPosition;
  float seed = aSeed.x;
  float statePulse = 1.0;
  float stateWarp = 1.0;
  float stateSpeed = 1.0;

  if (uState > 1.5 && uState < 2.5) {
    statePulse = 1.28;
    stateWarp = 1.42;
    stateSpeed = 1.85;
  } else if (uState > 2.5 && uState < 3.5) {
    statePulse = 1.46;
    stateWarp = 1.72;
    stateSpeed = 2.45;
  } else if (uState > 0.5 && uState < 1.5) {
    statePulse = 1.14;
    stateWarp = 1.16;
    stateSpeed = 1.18;
  } else if (uState > 3.5 && uState < 4.5) {
    statePulse = 1.22;
    stateWarp = 1.27;
    stateSpeed = 1.36;
  } else if (uState > 4.5) {
    statePulse = 0.82;
    stateWarp = 0.78;
    stateSpeed = 0.62;
  }

  if (uLayer < 0.5) {
    vec3 normalP = normalize(p);
    float field = organicField(normalP, t * stateSpeed);
    float voiceLow = sin((normalP.y + 1.0) * 6.0 - t * 4.4 + aSeed.y * 2.0) * uBass;
    float voiceMid = sin((normalP.x + normalP.z) * 10.0 - t * 7.2 + aSeed.z * 4.0) * uMid;
    float voiceHigh = cos((normalP.z + 1.0) * 18.0 + t * 11.0 + aSeed.w * 5.0) * uHigh;

    float deform = 1.0;
    deform += field * (0.045 + uEnergy * 0.055) * stateWarp;
    deform += voiceLow * 0.105 + voiceMid * 0.055 + voiceHigh * 0.022;
    deform += sin(t * 1.15 + aSeed.y * 6.2831) * 0.012 * statePulse;

    float detachGate = smoothstep(0.91 - uEnergy * 0.055, 0.995, seed);
    float detach = detachGate * (0.04 + uEnergy * 0.16) * (0.45 + 0.55 * sin(t * (1.4 + stateSpeed) + aSeed.z * 12.0));
    p = normalP * (length(p) * deform + detach);

    vec3 tangent = normalize(cross(normalP, vec3(0.0, 1.0, 0.001)));
    p += tangent * detachGate * sin(t * 1.8 + aSeed.w * 9.0) * (0.015 + uHigh * 0.035);
  } else {
    float orbitSpeed = (0.18 + aSeed.y * 0.42) * stateSpeed;
    float orbit = t * orbitSpeed + aSeed.z * 6.2831;
    p.xz = rot(orbit) * p.xz;
    p.y += sin(t * (0.35 + aSeed.w) + aSeed.x * 8.0) * (0.05 + uMid * 0.12);
    float pull = 1.0 - min(uEnergy * 0.06, 0.08);
    p *= pull;
    p += normalize(p) * sin(t * 0.8 + aSeed.y * 9.0) * uHigh * 0.045;
  }

  float yaw = t * (0.095 + uEnergy * 0.14) * stateSpeed + uMouse.x * 0.16;
  float pitch = 0.12 * sin(t * 0.21) + uMouse.y * 0.10;
  p.xz = rot(yaw) * p.xz;
  p.yz = rot(pitch) * p.yz;

  float cameraZ = 3.85 + p.z;
  float persp = 2.75 / max(cameraZ, 0.35);
  float scale = uLayer < 0.5 ? 0.66 : 0.58;
  vec2 screen = vec2((p.x * persp * scale) / uAspect, p.y * persp * scale);
  screen.y += 0.065;

  gl_Position = vec4(screen, 0.0, 1.0);

  float front = clamp((p.z + 1.7) / 3.4, 0.08, 1.0);
  float sizeBase = mix(1.15, 3.25, aSeed.y);
  if (uLayer > 0.5) sizeBase *= 0.72;
  sizeBase *= 1.0 + uEnergy * 0.22 + uHigh * 0.25;
  sizeBase *= mix(1.0, 2.8, uGlowPass);
  gl_PointSize = sizeBase * uPixelRatio * (0.76 + persp * 0.35);

  float flicker = 0.74 + 0.26 * sin(t * (1.7 + uEnergy * 3.5) + aSeed.z * 11.0);
  vAlpha = front * flicker * mix(0.44, 0.95, aSeed.w);
  if (uLayer > 0.5) vAlpha *= 0.38 + uEnergy * 0.30;
  if (uGlowPass > 0.5) vAlpha *= 0.14;
  vHeat = clamp(front * 0.72 + uEnergy * 0.28 + uBass * 0.18, 0.0, 1.0);
  vLayer = uLayer;
}
`;

const FRAGMENT_SHADER = `#version 300 es
precision highp float;

in float vAlpha;
in float vHeat;
in float vLayer;
out vec4 outColor;

void main() {
  vec2 uv = gl_PointCoord - vec2(0.5);
  float d = length(uv) * 2.0;
  float soft = 1.0 - smoothstep(0.18, 1.0, d);
  float core = 1.0 - smoothstep(0.0, 0.42, d);
  if (soft <= 0.002) discard;

  vec3 cold = vec3(0.16, 0.71, 0.91);
  vec3 hot = vec3(0.82, 0.98, 1.0);
  vec3 color = mix(cold, hot, clamp(vHeat + core * 0.24, 0.0, 1.0));
  if (vLayer > 0.5) color *= vec3(0.72, 0.95, 1.08);
  float alpha = soft * vAlpha * (0.52 + core * 0.62);
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

function buildCoreParticles(count) {
  const positions = new Float32Array(count * 3);
  const seeds = new Float32Array(count * 4);
  const golden = Math.PI * (3 - Math.sqrt(5));

  for (let i = 0; i < count; i += 1) {
    const y = 1 - (i / Math.max(1, count - 1)) * 2;
    const radius = Math.sqrt(Math.max(0, 1 - y * y));
    const theta = golden * i;
    const shell = 0.79 + Math.random() * 0.34;
    positions[i * 3] = Math.cos(theta) * radius * shell;
    positions[i * 3 + 1] = y * shell;
    positions[i * 3 + 2] = Math.sin(theta) * radius * shell;
    seeds[i * 4] = Math.random();
    seeds[i * 4 + 1] = Math.random();
    seeds[i * 4 + 2] = Math.random();
    seeds[i * 4 + 3] = Math.random();
  }
  return { positions, seeds };
}

function buildDustParticles(count) {
  const positions = new Float32Array(count * 3);
  const seeds = new Float32Array(count * 4);

  for (let i = 0; i < count; i += 1) {
    const a = Math.random() * Math.PI * 2;
    const radial = 1.25 + Math.pow(Math.random(), 0.48) * 2.75;
    const flatten = 0.42 + Math.random() * 0.78;
    positions[i * 3] = Math.cos(a) * radial;
    positions[i * 3 + 1] = (Math.random() - 0.5) * 2.4 * flatten;
    positions[i * 3 + 2] = Math.sin(a) * radial * (0.55 + Math.random() * 0.62);
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
    const dustData = buildDustParticles(DUST_PARTICLES);
    const coreGpu = createParticleVao(gl, program, coreData);
    const dustGpu = createParticleVao(gl, program, dustData);

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
    let energy = 0.15;
    const start = performance.now();

    const resize = () => {
      width = Math.max(1, window.innerWidth);
      height = Math.max(1, window.innerHeight);
      dpr = Math.min(window.devicePixelRatio || 1, 1.75);
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
    gl.clearColor(0.002, 0.012, 0.019, 1.0);

    const drawLayer = (gpu, count, layer, glowPass) => {
      gl.uniform1f(uniforms.layer, layer);
      gl.uniform1f(uniforms.glowPass, glowPass);
      gl.bindVertexArray(gpu.vao);
      gl.drawArrays(gl.POINTS, 0, count);
    };

    const render = (now) => {
      const t = (now - start) / 1000;
      const bands = audioBandsRef.current || { bass: 0, mid: 0, high: 0 };
      const audio = audioLevelRef.current || 0;
      const stateCode = stateToCode(visualStateRef.current);
      const stateEnergy = [0.14, 0.43, 0.76, 0.96, 0.61, 0.24][stateCode] || 0.14;
      const targetEnergy = Math.min(1.3, stateEnergy + audio * 0.65 + (bands.bass || 0) * 0.22);
      energy += (targetEnergy - energy) * 0.065;
      smoothX += (mouseX - smoothX) * 0.035;
      smoothY += (mouseY - smoothY) * 0.035;

      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.useProgram(program);
      gl.uniform1f(uniforms.time, t);
      gl.uniform1f(uniforms.energy, energy);
      gl.uniform1f(uniforms.bass, bands.bass || 0);
      gl.uniform1f(uniforms.mid, bands.mid || 0);
      gl.uniform1f(uniforms.high, bands.high || 0);
      gl.uniform1f(uniforms.state, stateCode);
      gl.uniform1f(uniforms.aspect, width / height);
      gl.uniform1f(uniforms.pixelRatio, dpr);
      gl.uniform2f(uniforms.mouse, smoothX, smoothY);

      drawLayer(coreGpu, CORE_PARTICLES, 0, 1);
      drawLayer(dustGpu, DUST_PARTICLES, 1, 1);
      drawLayer(coreGpu, CORE_PARTICLES, 0, 0);
      drawLayer(dustGpu, DUST_PARTICLES, 1, 0);

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
      gl.deleteBuffer(coreGpu.positionBuffer);
      gl.deleteBuffer(coreGpu.seedBuffer);
      gl.deleteVertexArray(coreGpu.vao);
      gl.deleteBuffer(dustGpu.positionBuffer);
      gl.deleteBuffer(dustGpu.seedBuffer);
      gl.deleteVertexArray(dustGpu.vao);
      gl.deleteProgram(program);
    };
  }, [audioBandsRef, audioLevelRef, visualStateRef]);

  return <canvas id="space" ref={canvasRef} aria-hidden="true" />;
}

export const WEBGL_PARTICLE_COUNT = CORE_PARTICLES + DUST_PARTICLES;
