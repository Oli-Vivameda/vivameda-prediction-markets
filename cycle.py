"""One bounded discovery/research cycle for systemd."""
import json
import scanner, bridge

def main():
    result=scanner.scan(scanner.STATE,pages=5,quote_limit=10)
    try:
        research=bridge.enrich(scanner.STATE,limit=2)
    except Exception as exc:
        research={'status':'UNAVAILABLE','error':type(exc).__name__,'live_execution':False}
    print(json.dumps({'run_id':result['run_id'],'feeds':result['feeds'],
                      'candidate_count':result['candidate_count'],'research':research,
                      'live_execution':False,'paid_provider_requests':0}))
if __name__=='__main__':main()
