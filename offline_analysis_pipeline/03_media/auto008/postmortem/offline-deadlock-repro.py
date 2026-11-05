from pathlib import Path
from a008 import runner
from tests.test_runner import make_ctx,make_integration
ctx=make_ctx()
runner.process_one=lambda integ,ctx,log: {"post_id":"p1","status":"success","chunked":False,"calls":[{"tag":"post","http_status":200,"api_attempts":1,"elapsed_s":0.001,"usage":{"total_tokens":1},"finish_reason":"stop","raw_response":"mock"}]}
runner.run_batch([make_integration()],ctx,Path(__import__('sys').argv[1]),resume=False,log=lambda *a:None)
