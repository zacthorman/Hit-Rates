import json,glob,collections,sys,os
os.chdir(sys.argv[1])
ev={}
for f in glob.glob('team_*_events_last_*.json')+glob.glob('unique-tournament_*_events_last_*.json'):
    try: d=json.load(open(f))
    except Exception: continue
    for e in d.get('events') or []:
        if (e.get('status') or {}).get('type')!='finished': continue
        if ((e.get('homeTeam') or {}).get('sport') or {}).get('slug')!='football': continue
        if e.get('homeScore',{}).get('current') is None: continue
        ev[e['id']]=e
print('events',len(ev))
tc=collections.Counter((e['tournament'].get('uniqueTournament') or {}).get('name','?') for e in ev.values())
for k,v in tc.most_common(45): print(v,k)
teams=set()
for e in ev.values(): teams.add(e['homeTeam']['id']); teams.add(e['awayTeam']['id'])
print('teams',len(teams))
ts=sorted(e['startTimestamp'] for e in ev.values()); import time
print(time.strftime('%Y-%m-%d',time.gmtime(ts[0])), time.strftime('%Y-%m-%d',time.gmtime(ts[-1])))
