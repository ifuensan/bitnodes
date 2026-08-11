"""Onion dials must land on the same Tor daemon every time.

Tor keeps a hidden service's descriptor and its introduction/rendezvous
circuits in the daemon that built them. Spreading one onion's dials across
the pool throws that state away pool-size times over and makes
MaxCircuitDirtiness nearly inert, since a revisit only meets the warm circuit
1/N of the time.
"""

import os
import subprocess
import sys

from utils import select_proxy

POOL = [
    ("127.0.0.1", 9050),
    ("127.0.0.1", 9051),
    ("127.0.0.1", 9052),
    ("127.0.0.1", 9053),
]

ONION = "2gzyxa5ihm7nsggfxnu52rck2vv4rvmdlkiu3zzui5du4xyclen53wid.onion"


def test_same_address_always_gets_the_same_proxy():
    chosen = {select_proxy(ONION, POOL) for _ in range(50)}
    assert len(chosen) == 1


def test_choice_does_not_depend_on_pool_ordering():
    # crawl and ping build the list from the same conf, but a set is not
    # ordered: the selection must not depend on the order it arrives in.
    assert select_proxy(ONION, POOL) == select_proxy(ONION, list(reversed(POOL)))
    assert select_proxy(ONION, POOL) == select_proxy(ONION, set(POOL))


def test_choice_survives_a_new_process():
    """A different interpreter (so a different PYTHONHASHSEED) must agree.

    This is the bug that bare hash() would have: str hashing is salted per
    process, so crawl and ping would disagree on the same onion and every
    restart would reshuffle the whole assignment.
    """
    code = (
        "import sys; sys.path.insert(0, %r);"
        "from utils import select_proxy;"
        "print(select_proxy(%r, [('127.0.0.1', p) for p in (9050, 9051, 9052, 9053)]))"
        % (os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ONION)
    )
    env = dict(os.environ, PYTHONHASHSEED="12345")
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
    ).stdout.strip()
    assert out == str(select_proxy(ONION, POOL))


def test_distinct_addresses_spread_across_the_pool():
    addresses = [f"{i:052x}.onion" for i in range(4000)]
    counts = {}
    for address in addresses:
        proxy = select_proxy(address, POOL)
        counts[proxy] = counts.get(proxy, 0) + 1
    assert set(counts) == set(POOL)
    # Even to well within the margin that matters for load balance.
    assert max(counts.values()) - min(counts.values()) < len(addresses) * 0.1


def test_affinity_off_falls_back_to_random():
    chosen = {select_proxy(ONION, POOL, affinity=False) for _ in range(200)}
    assert len(chosen) > 1


def test_empty_pool_returns_none():
    assert select_proxy(ONION, []) is None
