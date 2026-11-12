"""Local-first Personal Companion API with approval-first AI proposals."""
from __future__ import annotations
import json, os, mimetypes
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = ROOT / "ui"
TAXONOMY_PATH = ROOT / "data" / "taxonomy.fa.json"
MAX_BODY = 256_000
ROUTES = {
 "system1_local": ("ICARUS_SYSTEM1_LOCAL_URL","ICARUS_SYSTEM1_LOCAL_MODEL",None,"http://127.0.0.1:11434/v1","qwen2.5:3b"),
 "system1_api": ("ICARUS_SYSTEM1_API_URL","ICARUS_SYSTEM1_API_MODEL","ICARUS_SYSTEM1_API_KEY",None,None),
 "system2_local": ("ICARUS_SYSTEM2_LOCAL_URL","ICARUS_SYSTEM2_LOCAL_MODEL",None,"http://127.0.0.1:11434/v1","qwen2.5:7b"),
 "system2_api": ("ICARUS_SYSTEM2_API_URL","ICARUS_SYSTEM2_API_MODEL","ICARUS_SYSTEM2_API_KEY",None,None),
}
def send_json(h,status,data):
 raw=json.dumps(data,ensure_ascii=False).encode()
 h.send_response(status); h.send_header("Content-Type","application/json; charset=utf-8")
 h.send_header("Content-Length",str(len(raw))); h.send_header("Cache-Control","no-store")
 h.end_headers(); h.wfile.write(raw)
def read_json(h):
 n=int(h.headers.get("Content-Length","0"))
 if n<2 or n>MAX_BODY: raise ValueError("اندازهٔ درخواست نامعتبر است.")
 return json.loads(h.rfile.read(n).decode())
def provider(route):
 if route not in ROUTES: raise ValueError("مسیر مدل نامعتبر است.")
 ue,me,ke,du,dm=ROUTES[route]; base=os.environ.get(ue,du); model=os.environ.get(me,dm)
 if not base or not model: raise ValueError("URL یا نام مدل این مسیر تنظیم نشده است.")
 key=os.environ.get(ke) if ke else None
 if ke and not key: raise ValueError("کلید API در متغیر محیطی "+ke+" تنظیم نشده است.")
 return base.rstrip("/")+"/chat/completions",model,key
def ask(route,system,payload):
 endpoint,model,key=provider(route)
 body=json.dumps({"model":model,"temperature":0.2,"response_format":{"type":"json_object"},"messages":[{"role":"system","content":system},{"role":"user","content":json.dumps(payload,ensure_ascii=False)}]}).encode()
 headers={"Content-Type":"application/json"}
 if key: headers["Authorization"]="Bearer "+key
 try:
  with urlopen(Request(endpoint,data=body,headers=headers,method="POST"),timeout=90) as response: data=json.loads(response.read().decode())
 except HTTPError as exc: raise RuntimeError("سرویس مدل خطای "+str(exc.code)+" داد: "+exc.read(800).decode("utf-8","replace")) from exc
 except (URLError,TimeoutError) as exc: raise RuntimeError("اتصال به مدل برقرار نشد: "+str(exc)) from exc
 try: return json.loads(data["choices"][0]["message"]["content"]),model
 except (KeyError,IndexError,TypeError,json.JSONDecodeError) as exc: raise RuntimeError("مدل خروجی JSON معتبر برنگرداند.") from exc
def taxonomy():
 with TAXONOMY_PATH.open(encoding="utf-8") as f: return json.load(f)
def classify(p):
 item=p.get("item")
 if not isinstance(item,str) or not item.strip() or len(item)>4000: raise ValueError("متن مورد باید بین ۱ تا ۴۰۰۰ نویسه باشد.")
 route=p.get("route","system1_local"); cats=taxonomy()["categories"]
 system=("Return JSON only: category_id, subcategory_id, confidence (0..1), rationale, alternatives. "
 "Choose only IDs in supplied taxonomy. Never execute, edit or schedule anything. If uncertain confidence <0.55.")
 result,model=ask(route,system,{"item":item,"context":p.get("context",""),"taxonomy":cats})
 valid={c["id"]:{s["id"] for s in c["children"]} for c in cats}
 cid=result.get("category_id"); sid=result.get("subcategory_id"); confidence=result.get("confidence",0)
 if cid not in valid or sid not in valid[cid]: raise RuntimeError("مدل شناسه‌ای خارج از taxonomy پیشنهاد کرد.")
 if not isinstance(confidence,(int,float)) or not 0<=confidence<=1: raise RuntimeError("درجهٔ اطمینان نامعتبر است.")
 return {"proposal":result,"model":model,"route":route,"requires_user_approval":True,"applied":False}
def calendar_plan(p):
 route=p.get("route","system2_local"); tasks=p.get("tasks"); windows=p.get("available_windows"); tz=p.get("timezone")
 if not isinstance(tasks,list) or not tasks or len(tasks)>200: raise ValueError("فهرست ۱ تا ۲۰۰ کار لازم است.")
 if not isinstance(windows,list) or not windows or len(windows)>30: raise ValueError("حداقل یک بازهٔ زمانی آزاد لازم است.")
 if not isinstance(tz,str) or not tz.strip(): raise ValueError("منطقهٔ زمانی لازم است.")
 parsed_windows=[]
 for window in windows:
  try:
   ws=datetime.fromisoformat(window["start"].replace("Z","+00:00")); we=datetime.fromisoformat(window["end"].replace("Z","+00:00"))
  except (KeyError,TypeError,ValueError,AttributeError) as exc: raise ValueError("بازه‌های آزاد باید ISO-8601 و دارای offset باشند.") from exc
  if ws.tzinfo is None or we.tzinfo is None or we<=ws: raise ValueError("بازهٔ آزاد معتبر نیست.")
  parsed_windows.append((ws,we))
 system=("Return JSON only: {events:[{title,task_id,start,end,category,reason}],conflicts:[],notes:[]}. "
 "Use ONLY supplied availability windows and timezone. Never invent free time or move fixed events. "
 "Every event must fit wholly inside one availability window and events must not overlap. "
 "Use ISO-8601 timestamps with explicit UTC offsets. If duration_minutes is absent, estimate conservatively "
 "and explicitly label that estimate in reason. Do not claim events saved; this is a proposal only. "
 "Tasks that do not fit must be listed in conflicts.")
 result,model=ask(route,system,{"tasks":tasks,"available_windows":windows,"timezone":tz,"date_range":p.get("date_range"),"constraints":p.get("constraints",[])})
 events=result.get("events")
 if not isinstance(events,list) or len(events)>300: raise RuntimeError("فهرست رویدادها نامعتبر است.")
 known={str(t.get("id")) for t in tasks if isinstance(t,dict) and t.get("id") is not None}
 parsed_events=[]
 for event in events:
  if not isinstance(event,dict) or not isinstance(event.get("title"),str) or not event["title"].strip() or str(event.get("task_id")) not in known: raise RuntimeError("رویداد نامعتبر یا بدون کار متناظر است.")
  try:
   start=datetime.fromisoformat(event["start"].replace("Z","+00:00")); end=datetime.fromisoformat(event["end"].replace("Z","+00:00"))
  except (KeyError,TypeError,ValueError,AttributeError) as exc: raise RuntimeError("زمان باید ISO-8601 معتبر باشد.") from exc
  if start.tzinfo is None or end.tzinfo is None or end<=start: raise RuntimeError("زمان رویداد باید offset معتبر داشته باشد.")
  if not any(start>=ws and end<=we for ws,we in parsed_windows): raise RuntimeError("مدل رویدادی خارج از زمان آزاد تعیین‌شده پیشنهاد کرده است.")
  parsed_events.append((start,end))
 parsed_events.sort(key=lambda pair:pair[0])
 for previous,current in zip(parsed_events,parsed_events[1:]):
  if current[0]<previous[1]: raise RuntimeError("پیشنهاد مدل شامل رویدادهای هم‌پوشان است.")
 return {"proposal":result,"model":model,"route":route,"requires_user_approval":True,"applied":False}

class Handler(BaseHTTPRequestHandler):
 def log_message(self,fmt,*args): print("%s - %s"%(self.address_string(),fmt%args))
 def do_GET(self):
  if self.path=="/api/health": return send_json(self,200,{"ok":True,"service":"icarus-personal-companion","ai_mode":"approval-first"})
  if self.path=="/api/taxonomy": return send_json(self,200,taxonomy())
  rel=self.path.split("?",1)[0].lstrip("/") or "index.html"; target=(UI_ROOT/rel).resolve()
  if UI_ROOT.resolve() not in target.parents and target!=UI_ROOT.resolve(): return send_json(self,403,{"error":"مسیر غیرمجاز است."})
  if not target.is_file(): return send_json(self,404,{"error":"فایل پیدا نشد."})
  raw=target.read_bytes(); self.send_response(200); self.send_header("Content-Type",mimetypes.guess_type(target.name)[0] or "application/octet-stream"); self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw)
 def do_POST(self):
  try:
   p=read_json(self)
   if self.path=="/api/ai/classify": result=classify(p)
   elif self.path=="/api/ai/calendar": result=calendar_plan(p)
   else: return send_json(self,404,{"error":"مسیر API پیدا نشد."})
   return send_json(self,200,result)
  except (ValueError,json.JSONDecodeError) as exc: return send_json(self,400,{"error":str(exc)})
  except RuntimeError as exc: return send_json(self,502,{"error":str(exc)})
def main():
 host=os.environ.get("ICARUS_COMPANION_HOST","127.0.0.1"); port=int(os.environ.get("ICARUS_COMPANION_PORT","4173"))
 server=ThreadingHTTPServer((host,port),Handler)
 print("ICARUS Personal Companion: http://%s:%s"%(host,port))
 print("AI proposals require explicit user approval; legacy agents remain quarantined.")
 server.serve_forever()
if __name__=="__main__": main()
