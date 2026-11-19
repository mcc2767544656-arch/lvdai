import json, sys, time, urllib.request
API='http://127.0.0.1:9873/api/control'
def post(lin, ang):
    body=json.dumps({"linear":lin,"angular":ang}).encode()
    req=urllib.request.Request(API, data=body, headers={'Content-Type':'application/json'})
    try:
        urllib.request.urlopen(req, timeout=0.3).read()
        return True
    except Exception:
        return False

levels=[float(x) for x in sys.argv[1].split(',')]
hold=float(sys.argv[2]) if len(sys.argv)>2 else 3.0
rest=float(sys.argv[3]) if len(sys.argv)>3 else 2.0

def drive(ang, dur):
    t0=time.time()
    while time.time()-t0<dur:
        post(0.0, ang); time.sleep(0.08)

print(f"levels={levels} hold={hold}s rest={rest}s", flush=True)
for lv in levels:
    for sign in (+1,-1):
        a=lv*sign
        print(f"  -> ang={a:+.2f}", flush=True)
        drive(a, hold)
        print(f"     stop", flush=True)
        drive(0.0, rest)
print("done", flush=True)
