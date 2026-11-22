"""F1 CUSTOM PARTS LAB — 설치 위치: pages/parts.py

실행: 프로젝트 루트에서 streamlit run main.py
Python 의존성: 기존 streamlit만 사용(권장 1.32 이상).
Three.js 0.164.1은 브라우저가 CDN에서 불러옵니다. 인터넷/WebGL 필요.
기존 main.py/racing.py/chat.py를 import하거나 수정하지 않습니다.
기존 차량 선택/성능 키는 변경하지 않습니다. 실제 차량 장착은 미구현입니다.
모든 치수는 게임 모델용이며 FIA 규정/실측 형상/CFD를 재현하지 않습니다.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
from uuid import uuid4

import streamlit as st
import streamlit.components.v1 as components

NS = "f1_parts_lab_v1"
SCHEMA_VERSION = 1
MODEL_VERSION = "arcade-aero-v1"
# label, min, max, default, step, unit
SPECS = {
    "front_wing": {
        "name": "Front Wing", "ko": "프론트 윙", "mesh": "frontWing",
        "description": "앞쪽 다운포스와 공기저항의 균형을 설계합니다.",
        "fields": {
            "width": ("윙 폭", 120, 220, 180, 5, "cm"),
            "chord": ("윙 앞뒤 길이", 20, 60, 38, 1, "cm"),
            "angle": ("받음각", 0, 32, 14, 1, "°"),
            "camber": ("단면 곡률", 0, 15, 6, 1, "%"),
            "endplate": ("엔드플레이트 높이", 10, 45, 24, 1, "cm"),
        },
    },
    "rear_wing": {
        "name": "Rear Wing", "ko": "리어 윙", "mesh": "rearWing",
        "description": "메인 윙과 플랩으로 뒤쪽 다운포스를 설계합니다.",
        "fields": {
            "width": ("윙 폭", 75, 140, 110, 5, "cm"),
            "chord": ("메인 윙 앞뒤 길이", 20, 55, 36, 1, "cm"),
            "angle": ("메인 윙 받음각", 0, 38, 18, 1, "°"),
            "height": ("지지대 높이", 45, 110, 75, 5, "cm"),
            "gap": ("메인 윙–플랩 간격", 2, 14, 6, 1, "cm"),
        },
    },
    "diffuser": {
        "name": "Diffuser", "ko": "디퓨저", "mesh": "diffuser",
        "description": "상승하는 바닥 패널과 스트레이크로 출구를 설계합니다.",
        "fields": {
            "width": ("입구 폭", 70, 150, 110, 5, "cm"),
            "length": ("디퓨저 길이", 45, 120, 80, 5, "cm"),
            "angle": ("램프 상승각", 3, 25, 12, 1, "°"),
            "inlet": ("입구 통로 높이", 5, 18, 10, 1, "cm"),
            "flare": ("출구 폭 확장률", 0, 30, 12, 1, "%"),
            "strakes": ("내부 스트레이크 수", 2, 8, 4, 1, "개"),
        },
    },
}


def defaults(kind):
    return {key: spec[3] for key, spec in SPECS[kind]["fields"].items()}


def widget_key(kind, field):
    return f"{NS}:input:{kind}:{field}"


def initialize_state():
    if NS not in st.session_state:
        st.session_state[NS] = {
            "drafts": {kind: defaults(kind) for kind in SPECS},
            "saved": {}, "notice": "",
        }
    st.session_state.setdefault(f"{NS}:kind", "front_wing")


def sync_draft(kind, field):
    # 위젯이 다른 페이지에서 정리되어도 draft는 별도로 보존됩니다.
    st.session_state[NS]["drafts"][kind][field] = st.session_state[widget_key(kind, field)]


def set_draft(kind, params):
    """콜백에서만 호출: 렌더링된 위젯의 상태를 사후 변경하지 않습니다."""
    st.session_state[NS]["drafts"][kind] = deepcopy(params)
    for field, value in params.items():
        st.session_state[widget_key(kind, field)] = value


def reset_draft(kind):
    set_draft(kind, defaults(kind))
    st.session_state[NS]["notice"] = "현재 파츠를 기본값으로 되돌렸습니다. 저장된 파츠는 유지됩니다."


def load_saved():
    saved_id = st.session_state.get(f"{NS}:saved_choice")
    record = st.session_state[NS]["saved"].get(saved_id)
    if record is None:
        return
    kind = record["part_type"]
    st.session_state[f"{NS}:kind"] = kind
    set_draft(kind, record["parameters"])
    st.session_state[NS]["notice"] = f"‘{record['name']}’ 설정을 불러왔습니다."


def clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


def calculate_aero(kind, p):
    """결정론적 게임 전용 근사 모델. 힘/계수/CFD 결과가 아닌 무차원 지표.

    efficiency는 두 지표의 비율로 정의하며 실제 양항비가 아닙니다.
    stall은 급격한 각도 설정의 손실을 설명하기 위한 게임용 페널티입니다.
    """
    a = p["angle"]
    if kind == "front_wing":
        area = (p["width"] / 180) * (p["chord"] / 38)
        stall = clamp((a - 22) / 14, 0, 1)
        load = (0.32 + a / 30 + p["camber"] / 28) * (1 - 0.45 * stall)
        down = 53 * area ** 0.65 * load * (0.88 + p["endplate"] / 200)
        drag = 12 + 20 * area ** 0.7 + 0.032 * a * a + p["camber"] * 0.65 + p["endplate"] * 0.12
    elif kind == "rear_wing":
        area = (p["width"] / 110) * (p["chord"] / 36)
        stall = clamp((a - 26) / 14, 0, 1)
        slot = 1 - 0.22 * abs(p["gap"] - 6) / 8
        exposure = 0.9 + p["height"] / 750
        down = 61 * area ** 0.65 * (0.4 + a / 28) * slot * exposure * (1 - 0.5 * stall)
        drag = 16 + 20 * area ** 0.7 + 0.03 * a * a + p["height"] * 0.06 + abs(p["gap"] - 6) * 0.8
    else:
        area = (p["width"] / 110) * (p["length"] / 80)
        stall = clamp((a - 15) / 12, 0, 1)
        channel = 1 + 0.025 * (p["strakes"] - 4)
        inlet = 1 - 0.025 * abs(p["inlet"] - 10)
        down = 64 * area ** 0.6 * (0.35 + a / 20) * (1 + p["flare"] / 160) * channel * inlet * (1 - 0.55 * stall)
        drag = 10 + 13 * area ** 0.6 + 0.042 * a * a + p["flare"] * 0.2 + p["strakes"] * 0.8 + abs(p["inlet"] - 10) * 0.4
    down, drag = round(clamp(down), 1), round(clamp(drag), 1)
    return {
        "downforce": down, "drag": drag,
        "efficiency": round(down / max(drag, 1), 2),
        "separation_risk": round(stall, 3),
    }


def airflow_descriptor(kind, p, aero):
    """후속 입자/스트림라인 렌더러가 소비할 인터페이스. 현재 애니메이션 없음.

    좌표계: X=폭, Y=위, Z=입구(-)→출구(+). 길이 단위=게임용 m.
    보간 벡터장/입자 충돌 계산은 향후 구현 대상으로 남겨 둡니다.
    """
    return {
        "version": 1, "coordinate_system": "x-span_y-up_z-flow",
        "flow_direction": [0, 0, 1],
        "deflection_degrees": p["angle"],
        "wake_strength": round(aero["drag"] / 100, 3),
        "separation_risk": aero["separation_risk"],
        "span_m": p["width"] / 100,
        "part_type": kind,
    }


def make_record(kind, p, name):
    aero = calculate_aero(kind, p)
    return {
        "schema_version": SCHEMA_VERSION,
        "id": uuid4().hex,
        "name": name.strip()[:60],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "part_type": kind,
        "garage_mesh_name": SPECS[kind]["mesh"],
        "parameters": deepcopy(p),
        "parameter_units": {key: spec[5] for key, spec in SPECS[kind]["fields"].items()},
        "performance_model": MODEL_VERSION,
        "performance": aero,
        "airflow": airflow_descriptor(kind, p, aero),
        "installed": False,
    }


STYLE = """<style>
.stApp{background:radial-gradient(ellipse at 50% 0,#1c2835,#090d13 60%);color:#edf3fa;color-scheme:dark}
[data-testid="stMainBlockContainer"]{max-width:1680px;padding:1rem 1.5rem 3rem}
[data-testid="stHeader"]{background:transparent}
header [data-testid="stToolbar"]{visibility:hidden}
#MainMenu,footer{display:none}
h1,h2,h3{color:#f3f6fa!important;letter-spacing:.5px}
.lab-head{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap;padding:16px 20px;background:#0c1118;border:1px solid #27313d;border-top:3px solid #ff3158;margin-bottom:16px}
.lab-brand{font:bold 24px Arial,sans-serif;letter-spacing:1px}.lab-brand b{color:#ff3158}
.lab-tag{font:11px monospace;color:#9aa8b7;letter-spacing:2px}
.lab-note{padding:12px 16px;background:#101923;border:1px solid #293847;border-left:3px solid #27d6ff;color:#c2cfdd;font-size:13px;margin:8px 0 18px;line-height:1.7}
.lab-section{font:bold 12px monospace;color:#a3b3c4;letter-spacing:2px;padding:10px 0;border-bottom:1px solid #2b3948;margin-bottom:14px}
.lab-preview{padding:10px 14px;background:#101720;border:1px solid #2b3948;display:flex;justify-content:space-between;font:12px monospace;color:#cfdae6}
[data-testid="stWidgetLabel"] p,[data-testid="stCaptionContainer"]{color:#bdcada!important}
[data-testid="stMetric"]{background:#152131;border:1px solid #304053;border-radius:5px;padding:14px}
[data-testid="stMetricLabel"],[data-testid="stMetricValue"]{color:#f4f7fb!important}
.stButton>button,.stDownloadButton>button{width:100%;min-height:44px;background:#101923;color:#f4f7fb;border:1px solid #35465a;border-radius:4px;font-weight:700}
.stButton>button:hover,.stDownloadButton>button:hover{color:#fff;border-color:#ff3158;background:#251824}
.stButton>button[kind="primary"]{background:#db2146;border:1px solid #ff5677;color:white}
[data-baseweb="input"]>div,[data-baseweb="select"]>div{background-color:#142031!important;color:#eef4fa!important;border-color:#35465a!important}
input{color:#eef4fa!important}
@media(max-width:700px){[data-testid="stMainBlockContainer"]{padding:1rem .8rem 2rem}.lab-brand{font-size:19px}}
</style>"""


# 한 HTML 템플릿으로 유지하여 Python f-string과 JS 중괄호의 충돌을 피합니다.
PREVIEW_HTML = r'''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box}html,body,#root{margin:0;width:100%;height:100%;overflow:hidden;background:#090e15;color:#d5e4f2;font-family:Arial,sans-serif}
#root{background:radial-gradient(ellipse at 50% 40%,#223345,#090e15 75%)}canvas{display:block;touch-action:none}
#hint,#status{position:absolute;left:14px;right:14px;font-size:11px;line-height:1.7;pointer-events:none}
#hint{bottom:12px;color:#a9bdce}#status{top:12px;color:#9bdff3}
#status.error{color:#ff849a;background:#24131c;border:1px solid #92374b;padding:10px}
#camera{position:absolute;right:12px;bottom:12px;color:#e3eef9;background:#101c29;border:1px solid #41556b;padding:7px;cursor:pointer}
</style>
<script type="importmap">{"imports":{"three":"https://unpkg.com/three@0.164.1/build/three.module.js","three/addons/":"https://unpkg.com/three@0.164.1/examples/jsm/"}}</script>
</head><body><div id="root"></div><div id="status">3D 모듈을 불러오는 중…</div>
<div id="hint">DRAG 회전 · WHEEL 확대/축소<br>게임용 절차적 모델 / 실제 CAD·CFD 아님</div><button id="camera">시점 초기화</button>
<script type="module">
const cfg=__CONFIG__,root=document.getElementById('root'),status=document.getElementById('status');
const fail=message=>{status.textContent=message;status.className='error'};
const timeout=setTimeout(()=>fail('3D 로딩이 지연됩니다. CDN 인터넷 연결과 브라우저 WebGL 지원을 확인해 주세요.'),18000);
let renderer,controls,scene,raf=0,resizeObserver,disposed=false;
try{
 const THREE=await import('three');
 const {OrbitControls}=await import('three/addons/controls/OrbitControls.js');
 if(disposed)throw new Error('closed');
 const p=cfg.parameters,k=cfg.part_type;
 scene=new THREE.Scene();
 const camera=new THREE.PerspectiveCamera(38,1,0.01,100);
 renderer=new THREE.WebGLRenderer({antialias:true,alpha:true});
 renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));
 renderer.outputColorSpace=THREE.SRGBColorSpace;
 root.appendChild(renderer.domElement);
 controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;
 controls.minDistance=1;controls.maxDistance=12;controls.maxPolarAngle=Math.PI*.90;
 scene.add(new THREE.HemisphereLight(0xcce9ff,0x132030,2.7));
 const light=new THREE.DirectionalLight(0xffffff,3.6);light.position.set(3,5,3);scene.add(light);
 const rim=new THREE.PointLight(0xff3158,14,9);rim.position.set(-2,2,-2);scene.add(rim);
 const group=new THREE.Group();scene.add(group);
 const carbon=new THREE.MeshStandardMaterial({color:0x29333e,metalness:.65,roughness:.35,side:THREE.DoubleSide});
 const red=new THREE.MeshStandardMaterial({color:0xff3158,metalness:.5,roughness:.3,side:THREE.DoubleSide});
 const metal=new THREE.MeshStandardMaterial({color:0x9db0c2,metalness:.75,roughness:.3});
 const rad=THREE.MathUtils.degToRad;
 function add(parent,geometry,material,pos=[0,0,0]){
  const mesh=new THREE.Mesh(geometry,material);mesh.position.set(...pos);parent.add(mesh);return mesh;
 }
 // 임의 곡면을 유한 두께의 닫힌 메시로 생성합니다. X=폭, Z=앞뒤.
 function skin(parent,width,length,surface,material,thickness=.012,flare=0){
  const nx=36,nz=28,verts=[],indices=[];
  for(let layer=0;layer<2;layer++)for(let i=0;i<=nx;i++)for(let j=0;j<=nz;j++){
   const s=i/nx*2-1,t=j/nz,x=s*width*.5*(1+flare*t);
   const v=surface(s,t);verts.push(x,v.y-layer*thickness,(t-.5)*length+(v.sweep||0));
  }
  const count=(nx+1)*(nz+1),idx=(i,j)=>i*(nz+1)+j;
  function quad(a,b,c,d){indices.push(a,b,c,a,c,d)}
  for(let i=0;i<nx;i++)for(let j=0;j<nz;j++){
   const a=idx(i,j),b=idx(i+1,j),c=idx(i+1,j+1),d=idx(i,j+1);
   quad(a,b,c,d);quad(a+count,d+count,c+count,b+count);
  }
  for(let i=0;i<nx;i++)for(const j of [0,nz]){const a=idx(i,j),b=idx(i+1,j);quad(a,a+count,b+count,b)}
  for(let j=0;j<nz;j++)for(const i of [0,nx]){const a=idx(i,j),b=idx(i,j+1);quad(a,b,b+count,a+count)}
  const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(verts,3));geo.setIndex(indices);geo.computeVertexNormals();
  return add(parent,geo,material);
 }
 function wing(parent,width,chord,camber,sweep=0){
  return skin(parent,width,chord,(s,t)=>({y:-4*camber*chord*t*(1-t)+.025*s*s,sweep:sweep*s*s}),carbon);
 }
 const width=p.width/100;
 if(k==='front_wing'){
  const chord=p.chord/100,assembly=new THREE.Group();group.add(assembly);
  assembly.rotation.x=-rad(p.angle);
  wing(assembly,width,chord,p.camber/100,.08);
  // 엔드플레이트도 윙과 함께 회전합니다.
  [-1,1].forEach(sign=>add(assembly,new THREE.BoxGeometry(.016,p.endplate/100,chord*1.08),red,[sign*width/2,p.endplate/200-.035,.04]));
 }else if(k==='rear_wing'){
  const h=p.height/100,chord=p.chord/100;
  [-1,1].forEach(sign=>add(group,new THREE.BoxGeometry(.025,h,.055),metal,[sign*width*.28,h/2,0]));
  const assembly=new THREE.Group();assembly.position.y=h;assembly.rotation.x=-rad(p.angle);group.add(assembly);
  wing(assembly,width,chord,.065);
  const flap=new THREE.Group();flap.position.set(0,p.gap/100,chord*.62);flap.rotation.x=-rad(8);assembly.add(flap);
  wing(flap,width*.96,chord*.42,.09);
  [-1,1].forEach(sign=>add(assembly,new THREE.BoxGeometry(.018,.32,chord*1.65),red,[sign*width/2,.08,chord*.18]));
 }else{
  const length=p.length/100,inlet=p.inlet/100,rise=Math.tan(rad(p.angle))*length,flare=p.flare/100;
  const ramp=t=>inlet+rise*t*t;
  skin(group,width,length,(s,t)=>({y:ramp(t)}),carbon,.016,flare);
  // 곡면 램프이므로 angle은 끝단 접선각이 아닌 평균 상승각입니다.
  function fin(s,material){
   const shape=new THREE.Shape();shape.moveTo(-length/2,0);
   for(let j=0;j<=32;j++){const t=j/32;shape.lineTo((t-.5)*length,ramp(t))}
   shape.lineTo(length/2,0);shape.closePath();
   const geo=new THREE.ExtrudeGeometry(shape,{depth:.012,bevelEnabled:false,steps:1});
   // shape.x -> world.z, shape.y -> world.y, depth -> world.x
   geo.rotateY(-Math.PI/2);geo.translate(.006,0,0);
   const mesh=add(group,geo,material); // 각 정점의 z 위치에 따라 출구 확장률 적용
   const attr=geo.attributes.position;
   for(let i=0;i<attr.count;i++){
    const t=(attr.getZ(i)+length/2)/length;
    attr.setX(i,attr.getX(i)+s*width*.5*(1+flare*t));
   }
   attr.needsUpdate=true;geo.computeVertexNormals();return mesh;
  }
  fin(-1,red);fin(1,red);
  for(let i=1;i<=p.strakes;i++)fin(-1+2*i/(p.strakes+1),carbon);
 }
 // 고정 초기 카메라 거리로 치수 변경의 시각적 차이를 유지합니다.
 const bounds=new THREE.Box3().setFromObject(group),center=bounds.getCenter(new THREE.Vector3());
 const floorY=bounds.min.y-.06;
 const grid=new THREE.GridHelper(5,25,0x3b5269,0x1b2a3b);grid.position.y=floorY;scene.add(grid);
 const reset=()=>{controls.target.copy(center);camera.position.set(center.x+2.6,center.y+1.6,center.z+2.8);controls.update()};
 reset();document.getElementById('camera').onclick=reset;
 const resize=()=>{const w=Math.max(root.clientWidth,1),h=Math.max(root.clientHeight,1);camera.aspect=w/h;camera.updateProjectionMatrix();renderer.setSize(w,h)};
 resizeObserver=new ResizeObserver(resize);resizeObserver.observe(root);resize();
 renderer.domElement.addEventListener('webglcontextlost',e=>{e.preventDefault();cancelAnimationFrame(raf);fail('WebGL 연결이 중단되었습니다. 설정을 변경해 미리보기를 다시 불러와 주세요.')});
 const tick=()=>{if(disposed)return;raf=requestAnimationFrame(tick);controls.update();renderer.render(scene,camera)};tick();
 clearTimeout(timeout);status.textContent=cfg.name+' / PARAMETRIC 3D · 공기 흐름 애니메이션 미구현';
}catch(error){clearTimeout(timeout);fail('3D 미리보기를 시작하지 못했습니다. 인터넷/CDN 접근 및 WebGL 설정을 확인해 주세요. 성능 계산과 저장은 계속 사용할 수 있습니다.');}
window.addEventListener('pagehide',()=>{disposed=true;clearTimeout(timeout);cancelAnimationFrame(raf);resizeObserver?.disconnect();controls?.dispose();scene?.traverse(o=>{o.geometry?.dispose();if(o.material)(Array.isArray(o.material)?o.material:[o.material]).forEach(m=>m.dispose())});renderer?.dispose()},{once:true});
</script></body></html>'''


def build_preview_html(kind, params):
    aero = calculate_aero(kind, params)
    cfg = {"part_type": kind, "name": SPECS[kind]["name"],
           "parameters": params, "performance": aero,
           "airflow": airflow_descriptor(kind, params, aero)}
    payload = json.dumps(cfg, ensure_ascii=False).replace("<", "\\u003c")
    return PREVIEW_HTML.replace("__CONFIG__", payload)


def render_controls(kind):
    spec = SPECS[kind]
    st.markdown('<div class="lab-section">01 / GEOMETRY SETTINGS</div>', unsafe_allow_html=True)
    st.subheader(spec["ko"])
    st.caption(spec["description"])
    for field, (label, low, high, default, step, unit) in spec["fields"].items():
        key = widget_key(kind, field)
        if key not in st.session_state:
            st.session_state[key] = st.session_state[NS]["drafts"][kind][field]
        st.slider(f"{label} ({unit})", low, high, step=step, key=key,
                  on_change=sync_draft, args=(kind, field))
    st.button("현재 파츠 기본값 복원", key=f"{NS}:reset", on_click=reset_draft,
              args=(kind,), use_container_width=True)
    if kind == "front_wing":
        st.caption("곡률은 앞뒤 단면의 휘어짐입니다. 폭 방향의 완만한 후퇴 형상은 고정입니다.")
    elif kind == "diffuser":
        st.caption("램프 상승각은 입구–출구 평균 각도입니다. 곡면 램프의 끝단 접선각과는 다릅니다.")


def render_performance(kind, params):
    current = calculate_aero(kind, params)
    baseline = calculate_aero(kind, defaults(kind))
    columns = st.columns(3)
    with columns[0]:
        st.metric("예상 다운포스 / 100", f"{current['downforce']:.1f}",
                  f"{current['downforce'] - baseline['downforce']:+.1f}")
    with columns[1]:
        st.metric("예상 항력 / 100", f"{current['drag']:.1f}",
                  f"{current['drag'] - baseline['drag']:+.1f}", delta_color="inverse")
    with columns[2]:
        st.metric("공기역학 효율 · 지표비", f"{current['efficiency']:.2f}",
                  f"{current['efficiency'] - baseline['efficiency']:+.2f}")
    st.caption("변화량은 해당 파츠의 기본값 대비입니다. 효율 = 다운포스 지표 ÷ 항력 지표. 실제 양항비가 아닙니다.")
    if current["separation_risk"] > 0:
        st.warning("큰 각도에 따른 게임용 손실 페널티가 적용 중입니다. 각도를 더 높여도 다운포스가 계속 증가하지 않을 수 있습니다.")
    with st.expander("예상치의 의미와 모델 한계"):
        st.write("같은 설정값을 3D 형상과 성능 계산에 함께 사용합니다. 치수·각도 등에 따른 경향을 임의의 수식으로 비교하며, 결과는 0~100으로 제한합니다. 포화 구간에서는 형상이 변해도 점수가 같을 수 있습니다.")
        st.write("실제 압력·힘(N)·항력계수·속도·랩타임을 계산하지 않습니다. 파츠 간 상호작용과 플로어 효과는 미반영이며 서로 다른 종류의 파츠 점수를 합산하면 안 됩니다.")
        st.write("공기 흐름은 확장용 데이터만 준비되어 있습니다. 현재 입자 애니메이션이나 유체 해석은 제공하지 않습니다.")


def render_storage(kind, params):
    st.markdown('<div class="lab-section">03 / CUSTOM PART LIBRARY</div>', unsafe_allow_html=True)
    with st.form(f"{NS}:save_form", clear_on_submit=False):
        name = st.text_input("파츠 이름", max_chars=60, placeholder="예: Monaco Front V1")
        submitted = st.form_submit_button("SAVE CUSTOM PART · 새 파츠 저장", use_container_width=True)
    if submitted:
        if not name.strip():
            st.warning("저장할 파츠 이름을 입력해 주세요.")
        elif len(st.session_state[NS]["saved"]) >= 100:
            st.warning("이 세션에는 최대 100개까지 저장할 수 있습니다. 현재 설정은 JSON으로 내려받을 수 있습니다.")
        else:
            record = make_record(kind, params, name)
            st.session_state[NS]["saved"][record["id"]] = record
            st.success(f"‘{record['name']}’ 저장 완료 · 같은 이름도 별도 버전으로 저장합니다.")
    preview_record = make_record(kind, params, name.strip() or SPECS[kind]["name"] + " Draft")
    st.download_button("현재 설정 JSON 내려받기", data=json.dumps(preview_record, ensure_ascii=False, indent=2),
                       file_name=f"{kind}_custom.json", mime="application/json", use_container_width=True)
    saved = st.session_state[NS]["saved"]
    if saved:
        ids = list(reversed(saved))
        st.selectbox("저장된 파츠", ids, key=f"{NS}:saved_choice",
                     format_func=lambda ident: f"{saved[ident]['name']} · {SPECS[saved[ident]['part_type']]['name']} · {ident[:6]}")
        st.button("선택한 파츠 불러오기", key=f"{NS}:load", on_click=load_saved, use_container_width=True)
        selected = saved.get(st.session_state.get(f"{NS}:saved_choice"))
        if selected:
            with st.expander("선택한 저장본 데이터 확인"):
                st.json(selected)
    else:
        st.caption("아직 저장된 파츠가 없습니다.")
    st.caption("저장/불러오기는 현재 Streamlit 세션 범위입니다. 연결 종료·서버 재시작 등으로 초기화될 수 있습니다. JSON은 백업용이며 이 버전에는 JSON 가져오기 기능이 없습니다.")
    st.info("저장은 제작 라이브러리에만 반영됩니다. 기존 차량·레이싱·AI 상담에는 아직 적용되지 않습니다.")


def main():
    st.set_page_config(page_title="CUSTOM PARTS LAB | F1", page_icon="🏎️", layout="wide", initial_sidebar_state="collapsed")
    initialize_state()
    st.markdown(STYLE, unsafe_allow_html=True)
    st.markdown('<div class="lab-head"><div class="lab-brand">F1 <b>RACING SIMULATOR</b> · PARTS LAB</div><div class="lab-tag">DESIGN / INSPECT / SAVE</div></div>', unsafe_allow_html=True)
    if st.button("🔧 차량 설계 화면으로 돌아가기", key=f"{NS}:garage", use_container_width=True):
        st.session_state["app_view"] = "garage"
        try:
            st.switch_page("main.py")
        except st.errors.StreamlitAPIException:
            st.warning("main.py로 이동하지 못했습니다. 저장소 파일명과 페이지 등록 상태를 확인해 주세요.")
    st.caption("GARAGE → PARTS LAB · 기존 차량 설정을 유지한 채 제작할 수 있습니다.")
    st.markdown('<div class="lab-note">나만의 공기역학 파츠를 설계하세요. 치수와 각도를 바꾸면 3D 형상과 예상 지표가 함께 바뀝니다.<br><b>게임 내 근사 예상치이며 실제 CFD 또는 물리적으로 검증된 설계 도구가 아닙니다.</b></div>', unsafe_allow_html=True)
    # 불러오기 콜백은 아래 위젯이 만들어지기 전에 실행됩니다.
    kind = st.selectbox("제작할 파츠", list(SPECS), key=f"{NS}:kind",
                        format_func=lambda key: SPECS[key]["name"] + " · " + SPECS[key]["ko"])
    notice = st.session_state[NS].pop("notice", "")
    if notice:
        st.success(notice)
    left, right = st.columns([1, 2.35], gap="large")
    with left:
        render_controls(kind)
    params = deepcopy(st.session_state[NS]["drafts"][kind])
    with right:
        st.markdown('<div class="lab-section">02 / LIVE PART PREVIEW</div>', unsafe_allow_html=True)
        st.markdown('<div class="lab-preview"><span>PARAMETRIC 3D</span><span>CARBON / F1 RED</span></div>', unsafe_allow_html=True)
        components.html(build_preview_html(kind, params), height=470, scrolling=False)
        render_performance(kind, params)
    render_storage(kind, params)


if __name__ == "__main__":
    main()
