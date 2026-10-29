"""One native CPU worker at a time, with owned cancellation events."""
from concurrent.futures import ThreadPoolExecutor
import threading


class CpuJobQueue:
    def __init__(self):
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='cpu-response')
        self.events={};self.futures={};self.lock=threading.Lock()

    def submit(self,run_id,target):
        with self.lock:
            event=threading.Event();self.events[run_id]=event
            self.futures[run_id]=self.pool.submit(target,event)

    def cancel(self,run_id):
        with self.lock:
            if run_id in self.events:self.events[run_id].set()
            if run_id in self.futures:self.futures[run_id].cancel()

    def close(self):
        with self.lock:
            for event in self.events.values():event.set()
        self.pool.shutdown(wait=True,cancel_futures=True)
