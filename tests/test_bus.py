"""Tests for BUS subscribe/unsubscribe lifecycle (F1)."""
import asyncio

import pytest

from aegis.nexus.bus import BUS, Bus


@pytest.fixture(autouse=True)
def fresh_bus():
    bus = Bus()
    # swap global singleton so subscribers don't pollute across tests
    import aegis.nexus.bus as bus_mod
    orig = bus_mod.BUS
    bus_mod.BUS = bus
    yield bus
    bus_mod.BUS = orig


@pytest.mark.asyncio
async def test_subscribe_and_unsubscribe_removes_queue():
    b = Bus()
    q = b.subscribe("test.topic")
    assert "test.topic" in b._subs
    assert q in b._subs["test.topic"]

    b.unsubscribe("test.topic", q)
    assert "test.topic" not in b._subs


@pytest.mark.asyncio
async def test_unsubscribe_unknown_topic_no_error():
    b = Bus()
    q = asyncio.Queue()
    b.unsubscribe("no-such-topic", q)  # must not raise


@pytest.mark.asyncio
async def test_unsubscribe_unknown_queue_no_error():
    b = Bus()
    b.subscribe("topic")
    orphan = asyncio.Queue()
    b.unsubscribe("topic", orphan)  # must not raise


@pytest.mark.asyncio
async def test_unsubscribed_queue_no_longer_receives():
    b = Bus()
    q = b.subscribe("test.topic")
    b.unsubscribe("test.topic", q)

    await b.publish("test.topic", {"hello": "world"})
    with pytest.raises(asyncio.QueueEmpty):
        q.get_nowait()


@pytest.mark.asyncio
async def test_subscriber_count_baseline_after_cycles():
    b = Bus()
    topic = "action.speak"
    N = 100

    queues = []
    for _ in range(N):
        q = b.subscribe(topic)
        queues.append(q)

    assert len(b._subs[topic]) == N

    for q in queues:
        b.unsubscribe(topic, q)

    assert topic not in b._subs


@pytest.mark.asyncio
async def test_multiple_subscribers_same_topic():
    b = Bus()
    q1 = b.subscribe("topic")
    q2 = b.subscribe("topic")
    b.unsubscribe("topic", q1)
    assert "topic" in b._subs
    assert q2 in b._subs["topic"]
    b.unsubscribe("topic", q2)
    assert "topic" not in b._subs
