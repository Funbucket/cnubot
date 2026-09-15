"""Bounded shared product data; selection and exposure remain per request."""
import asyncio
import copy
from time import monotonic
from collections import OrderedDict


class AsyncCache:
    def __init__(self, ttl=300, max_age=600, capacity=2048):
        self.ttl, self.max_age, self.capacity = ttl, max_age, capacity
        self.values = OrderedDict()
        self.pending = {}

    async def get(self, key, factory):
        now = monotonic()
        saved = self.values.get(key)
        if saved and now - saved[0] < self.ttl:
            self.values.move_to_end(key)
            return copy.deepcopy(saved[1])
        loop_key = (asyncio.get_running_loop(), key)
        task = self.pending.get(loop_key)
        if task is None:
            async def refresh():
                try:
                    value = await factory()
                    self.values[key] = (monotonic(), copy.deepcopy(value))
                    self.values.move_to_end(key)
                    while len(self.values) > self.capacity:
                        self.values.popitem(last=False)
                    return value
                finally:
                    self.pending.pop(loop_key, None)
            task = asyncio.create_task(refresh())
            # Consume errors even if every waiting request disconnects.
            task.add_done_callback(lambda t: None if t.cancelled() else t.exception())
            self.pending[loop_key] = task
        try:
            return copy.deepcopy(await asyncio.shield(task))
        except Exception:
            if saved and monotonic() - saved[0] < self.max_age:
                return copy.deepcopy(saved[1])
            raise


details = AsyncCache()
links = AsyncCache(ttl=3600, max_age=3600)


async def detail(item_id):
    from app.services import toss_sharelink
    factory = toss_sharelink.detail
    return await details.get((factory, item_id),
                             lambda: asyncio.wait_for(factory(item_id), timeout=2))


async def link(item_id):
    from app.services import toss_sharelink
    factory = toss_sharelink.issue_link
    return await links.get((factory, item_id),
                           lambda: asyncio.wait_for(factory(item_id), timeout=2))
