"""One bounded hourly discovery/research/notification cycle for systemd."""
import json
import scanner, bridge, notify

def main():
    result=scanner.scan(scanner.STATE,pages=5,quote_limit=10)
    try:
        research=bridge.enrich(scanner.STATE,limit=2)
    except Exception as exc:
        research={'status':'UNAVAILABLE','error':type(exc).__name__,'reports':[],'live_execution':False}
    try:
        notifications=notify.dispatch(scanner.STATE,result,research)
    except Exception:
        notifications={'status':'UNAVAILABLE','sent':0,'failed':1}
    scanner.write_json(scanner.STATE,'cycle_latest.json',
        {'run_id':result['run_id'],'feeds':result['feeds'],
         'candidate_count':result['candidate_count'],'research':research,
         'telegram':notifications,'live_execution':False,'paid_provider_requests':0})
    print(json.dumps({'run_id':result['run_id'],'feeds':result['feeds'],
                      'candidate_count':result['candidate_count'],
                      'research_packets':research.get('new_research_packets',0),
                      'telegram':notifications,'live_execution':False,'paid_provider_requests':0}))
if __name__=='__main__':main()
