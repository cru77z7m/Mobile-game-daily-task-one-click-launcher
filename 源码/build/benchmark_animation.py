"""Measure actual native frame cost without starting tasks or writing config."""
import copy,json,sys,time,statistics,ctypes
from pathlib import Path
root=Path(__file__).resolve().parents[2]
source=Path(sys.argv[1]) if len(sys.argv)>1 else root/'源码'
sys.path.insert(0,str(source))
import daily_launcher as a
cfg=copy.deepcopy(a.DEFAULT_CONFIG)
cfg.update(json.loads((root/'config.json').read_text(encoding='utf-8-sig')))
a.load_config=lambda:copy.deepcopy(cfg)
a.save_config=lambda _:None
a.save_state=lambda:None
a.App._discover_instances=lambda _:None
a.App._tick_update=lambda _:None
a.LOG_PATH=str(root/'design/benchmark.log')
a.STATE.update(last_run_version=a.APP_VERSION)
ui=a.App();ui.no_auto=ui.no_mutex=True;ui.page='main'
hwnd=ui.create();dc=a.user32.GetDC(hwnd)
try:
 ui.paint(dc)
 ui.page='settings'
 ui.paint(dc)
 old,_,direction=ui._transition
 times=[]
 for i in range(65):
  ui._transition=(old,time.monotonic()-.12,direction)
  before=time.perf_counter()
  ui.paint(dc)
  elapsed=(time.perf_counter()-before)*1000
  if i>=5:times.append(elapsed)
 print(json.dumps({'version':a.APP_VERSION,'dpi':ui.dpi,'samples':len(times),
                   'median_ms':round(statistics.median(times),3),
                   'p95_ms':round(sorted(times)[round(len(times)*.95)-1],3)},ensure_ascii=False))
finally:
 a.user32.ReleaseDC(hwnd,dc);a.user32.DestroyWindow(hwnd)
