import * as THREE from 'three';

const mount = document.getElementById('reactor');
const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0x01030a, 0.0024);

const camera = new THREE.PerspectiveCamera(42, innerWidth / innerHeight, 0.1, 3000);
camera.position.set(0, 0, 320);

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.setClearColor(0x01030a, 1);
renderer.outputColorSpace = THREE.SRGBColorSpace;
mount.appendChild(renderer.domElement);

const root = new THREE.Group();
scene.add(root);
const reactor = new THREE.Group();
root.add(reactor);

const cyan = new THREE.Color(0x66efff);
const blue = new THREE.Color(0x16a7ff);
const white = new THREE.Color(0xeaffff);

function mat(color = cyan, opacity = 0.5, blending = THREE.AdditiveBlending) {
  return new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false, blending });
}

const coreUniforms = {
  time: { value: 0 }, intensity: { value: 1.0 },
  colorA: { value: new THREE.Color(0x0d6fff) }, colorB: { value: new THREE.Color(0x9dffff) }
};
const coreMaterial = new THREE.ShaderMaterial({
  transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, uniforms: coreUniforms,
  vertexShader: `varying vec3 vNormal; varying vec3 vPosition; void main(){vNormal=normalize(normalMatrix*normal);vPosition=position;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}`,
  fragmentShader: `uniform float time;uniform float intensity;uniform vec3 colorA;uniform vec3 colorB;varying vec3 vNormal;varying vec3 vPosition;void main(){float fresnel=pow(1.0-abs(vNormal.z),2.3);float bands=.5+.5*sin(vPosition.y*.42-time*3.5);float pulse=.72+.28*sin(time*2.2);vec3 c=mix(colorA,colorB,fresnel*.8+bands*.15);float a=(.18+fresnel*.68+bands*.08)*pulse*intensity;gl_FragColor=vec4(c,a);}`
});
const core = new THREE.Mesh(new THREE.IcosahedronGeometry(44, 5), coreMaterial);
reactor.add(core);

const innerWire = new THREE.Mesh(
  new THREE.IcosahedronGeometry(40, 3),
  new THREE.MeshBasicMaterial({ color: 0x8ff8ff, wireframe: true, transparent: true, opacity: 0.12, depthWrite: false, blending: THREE.AdditiveBlending })
);
reactor.add(innerWire);
const glow = new THREE.Mesh(new THREE.SphereGeometry(58, 40, 28), mat(new THREE.Color(0x168dff), 0.055));
reactor.add(glow);

const ringSpecs = [
  [61,.55,.82,.10,.00,.00],[69,.34,.58,.35,.10,.65],[78,.30,.46,1.18,.40,.14],
  [89,.24,.34,.72,1.08,.48],[103,.20,.23,1.42,.22,.95],[119,.16,.18,.30,1.32,.20]
];
const ringMeshes = [];
for (const [radius,tube,opacity,rx,ry,rz] of ringSpecs) {
  const torus = new THREE.Mesh(new THREE.TorusGeometry(radius,tube,10,256), mat(radius < 80 ? cyan : blue, opacity));
  torus.rotation.set(rx,ry,rz);
  torus.userData.speed = (.06 + Math.random()*.08) * (Math.random()>.5 ? 1 : -1);
  reactor.add(torus); ringMeshes.push(torus);
}

function circleLine(radius, opacity, tiltX=0, tiltY=0) {
  const pts=[]; for(let i=0;i<=256;i++){const a=(i/256)*Math.PI*2;pts.push(new THREE.Vector3(Math.cos(a)*radius,Math.sin(a)*radius,0));}
  const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),new THREE.LineBasicMaterial({color:0x4cdfff,transparent:true,opacity,blending:THREE.AdditiveBlending,depthWrite:false}));
  line.rotation.set(tiltX,tiltY,0); reactor.add(line); return line;
}
circleLine(132,.11,1.15,.25); circleLine(144,.075,.25,1.1); circleLine(156,.05,.72,.74);

const ticks=new THREE.Group();
for(let i=0;i<96;i++){
  const a=(i/96)*Math.PI*2, major=i%8===0, len=major?9:(i%4===0?6:3.4);
  const geo=new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(Math.cos(a)*126,Math.sin(a)*126,0),new THREE.Vector3(Math.cos(a)*(126+len),Math.sin(a)*(126+len),0)]);
  ticks.add(new THREE.Line(geo,new THREE.LineBasicMaterial({color:major?0xb7ffff:0x46d8ff,transparent:true,opacity:major?.65:.22,blending:THREE.AdditiveBlending,depthWrite:false})));
}
reactor.add(ticks);

const arcGroup=new THREE.Group();
for(let k=0;k<24;k++){
  const radius=110+(k%4)*9,start=Math.random()*Math.PI*2,span=.08+Math.random()*.28,pts=[];
  for(let j=0;j<=18;j++){const a=start+span*(j/18);pts.push(new THREE.Vector3(Math.cos(a)*radius,Math.sin(a)*radius,(Math.random()-.5)*.6));}
  const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),new THREE.LineBasicMaterial({color:k%5===0?0xeaffff:0x37cfff,transparent:true,opacity:.32+Math.random()*.3,blending:THREE.AdditiveBlending,depthWrite:false}));
  line.rotation.z=Math.random()*Math.PI*2; arcGroup.add(line);
}
reactor.add(arcGroup);

const particleCount=2400, positions=new Float32Array(particleCount*3), speeds=new Float32Array(particleCount);
for(let i=0;i<particleCount;i++){
  const r=52+Math.pow(Math.random(),.55)*125,theta=Math.random()*Math.PI*2,z=(Math.random()-.5)*56;
  positions[i*3]=Math.cos(theta)*r;positions[i*3+1]=Math.sin(theta)*r;positions[i*3+2]=z;speeds[i]=.15+Math.random()*.85;
}
const pGeo=new THREE.BufferGeometry(); pGeo.setAttribute('position',new THREE.BufferAttribute(positions,3));
const particles=new THREE.Points(pGeo,new THREE.PointsMaterial({color:0x7eeeff,size:1.05,transparent:true,opacity:.55,blending:THREE.AdditiveBlending,depthWrite:false,sizeAttenuation:true}));
reactor.add(particles);

const starsN=1800, starsPos=new Float32Array(starsN*3);
for(let i=0;i<starsN;i++){const r=420+Math.random()*1100,th=Math.random()*Math.PI*2,ph=Math.acos(2*Math.random()-1);starsPos[i*3]=r*Math.sin(ph)*Math.cos(th);starsPos[i*3+1]=r*Math.sin(ph)*Math.sin(th);starsPos[i*3+2]=r*Math.cos(ph);}
const sGeo=new THREE.BufferGeometry();sGeo.setAttribute('position',new THREE.BufferAttribute(starsPos,3));
const starField=new THREE.Points(sGeo,new THREE.PointsMaterial({color:0x268bb8,size:.85,transparent:true,opacity:.24,depthWrite:false,blending:THREE.AdditiveBlending}));scene.add(starField);

const graph=window.__JARVIS_GRAPH__||{nodes:[],stats:{neurons:0,synapses:0}}, satellites=new THREE.Group(), nodes=graph.nodes||[];
nodes.slice(0,14).forEach((node,idx)=>{
  const a=idx/Math.max(1,Math.min(14,nodes.length))*Math.PI*2,r=176+(idx%3)*16;
  const m=new THREE.Mesh(new THREE.SphereGeometry(idx===0?2.8:1.8,12,8),mat(idx===0?white:cyan,idx===0?.92:.48));
  m.position.set(Math.cos(a)*r,Math.sin(a)*r,(idx%2?1:-1)*14);m.userData.angle=a;m.userData.radius=r;m.userData.speed=.04+(idx%5)*.008;satellites.add(m);
});
reactor.add(satellites);
const rayMat=new THREE.LineBasicMaterial({color:0x38cfff,transparent:true,opacity:.08,blending:THREE.AdditiveBlending,depthWrite:false});
for(const sat of satellites.children){const g=new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0,0,0),sat.position.clone()]);reactor.add(new THREE.Line(g,rayMat.clone()));}

let pointerX=0,pointerY=0,targetX=0,targetY=0;
window.addEventListener('pointermove',e=>{targetX=(e.clientX/innerWidth-.5)*.22;targetY=(e.clientY/innerHeight-.5)*.18;});
const modeLabel=document.getElementById('modeLabel');
const modes=[['SISTEMA ONLINE',1.0],['ASCOLTO ATTIVO',1.18],['ANALISI NEURALE',1.34],['RISPOSTA VOCALE',1.22]];
let modeIndex=0,modeAt=performance.now();
function updateMode(now){if(now-modeAt>8000){modeIndex=(modeIndex+1)%modes.length;modeAt=now;modeLabel.textContent=modes[modeIndex][0];}return modes[modeIndex][1];}

window.addEventListener('message',event=>{
  const message=event.data;
  if(message?.type==='graph'){const g=message.graph||{};document.getElementById('neuronCount').textContent=g.stats?.neurons??g.nodes?.length??0;document.getElementById('synapseCount').textContent=g.stats?.synapses??g.links?.length??0;}
  if(message?.type==='mode'&&message.mode){modeLabel.textContent=String(message.mode).toUpperCase();modeAt=performance.now();}
});
window.addEventListener('resize',()=>{camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight);});

const clock=new THREE.Clock();
function animate(){
  const t=clock.getElapsedTime(),now=performance.now(),intensity=updateMode(now);
  coreUniforms.time.value=t;coreUniforms.intensity.value+=(intensity-coreUniforms.intensity.value)*.035;
  pointerX+=(targetX-pointerX)*.025;pointerY+=(targetY-pointerY)*.025;root.rotation.y=pointerX;root.rotation.x=-pointerY;
  reactor.rotation.z+=.0009*intensity;innerWire.rotation.x=t*.12;innerWire.rotation.y=-t*.16;innerWire.rotation.z=t*.08;
  glow.scale.setScalar(1+Math.sin(t*2.1)*.045*intensity);core.scale.setScalar(1+Math.sin(t*2.7)*.018*intensity);
  ticks.rotation.z=-t*.045*intensity;arcGroup.rotation.z=t*.085*intensity;arcGroup.rotation.x=Math.sin(t*.23)*.08;
  ringMeshes.forEach((ring,i)=>{ring.rotation.z+=ring.userData.speed*.008*intensity;ring.rotation.x+=Math.sin(t*.32+i)*.00022;ring.rotation.y+=Math.cos(t*.28+i)*.0002;});
  const attr=pGeo.attributes.position;
  for(let i=0;i<particleCount;i++){const x=attr.array[i*3],y=attr.array[i*3+1],a=Math.atan2(y,x)+.0005*speeds[i]*intensity,r=Math.hypot(x,y);attr.array[i*3]=Math.cos(a)*r;attr.array[i*3+1]=Math.sin(a)*r;}attr.needsUpdate=true;
  particles.rotation.x=Math.sin(t*.18)*.13;particles.rotation.y=t*.028;starField.rotation.y=t*.003;
  satellites.children.forEach((sat,idx)=>{const a=sat.userData.angle+t*sat.userData.speed;sat.position.x=Math.cos(a)*sat.userData.radius;sat.position.y=Math.sin(a)*sat.userData.radius;sat.position.z=Math.sin(a*2+idx)*18;sat.scale.setScalar(1+Math.sin(t*2+idx)*.18);});
  renderer.render(scene,camera);requestAnimationFrame(animate);
}
animate();
