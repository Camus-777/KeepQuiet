from __future__ import annotations
from datetime import datetime, timezone
import time
import numpy as np

from .audio import Bridge
from .devices import candidates, fingerprint, Route
from .storage import data_dir, write_json


def stable(stats, block_ms):
    counters = ("host_xruns", "input_drops", "output_underruns", "output_drops",
                "callback_contentions", "deadline_misses")
    return (stats["processed_blocks"] >= 20 and
            all(stats[k] == 0 for k in counters) and
            stats["dsp_p99_ms"] < block_ms * .8 and
            stats["callback_p99_ms"] < block_ms * 2.5)


def _route_rank(result):
    return (bool(result['route'].get('exclusive', False)),
            result['route'].get('block_ms') == 8,
            result['route'].get('rate') != 48000,
            result['stats']['estimated_local_ms'])


def select_best(results: list[dict]) -> dict | None:
    eligible = [r for r in results if r.get('stable')]
    if eligible:
        return min(
            eligible,
            key=_route_rank,
        )
    return None



def cache_path(input_id, output_id, *, battle_mode=False):
    suffix = '-battle' if battle_mode else ''
    return data_dir() / "benchmarks" / (fingerprint(input_id, output_id) + suffix + ".json")


def run_benchmark(
    input_id: int,
    output_id: int,
    models: dict,
    voiceprint=None,
    *,
    seconds: float = 2.0,
    emit=lambda *_: None,
    cancelled=lambda: False,
    battle_mode=False,
    gate_config=None,
    output_gain_db=0.0,
):
    if voiceprint is None:
        voiceprint = np.full(192, 1 / np.sqrt(192), dtype=np.float32)
    routes = candidates(input_id, output_id)
    results = []

    def measure(route: Route, duration: float) -> dict:
        with Bridge(route, models, voiceprint, probe=True, battle_mode=battle_mode,
                    gate_config=gate_config, output_gain_db=output_gain_db) as bridge:
            end = time.perf_counter() + 0.5
            while time.perf_counter() < end:
                if cancelled():
                    raise InterruptedError('测速已取消。')
                bridge.tick()
                if bridge.host_xruns + bridge.input_drops > 0:
                    break
            bridge.reset_metrics()
            end = time.perf_counter() + duration
            while time.perf_counter() < end:
                if cancelled():
                    raise InterruptedError('测速已取消。')
                bridge.tick()
                blocks = len(bridge.processing)
                faults = bridge.host_xruns + bridge.input_drops + bridge.ring.underflows + bridge.ring.drops
                if blocks >= 20 and faults >= 3:
                    break
                if blocks >= 20 and blocks % 10 == 0 and bridge.stats()['dsp_p95_ms'] > route.block_ms * 1.1:
                    break
            stats = bridge.stats()
        return {
            'route': route.to_dict(),
            'stats': stats,
            'stable': stable(stats, route.block_ms),
        }

    passed_48k_shared = 0
    for i, route in enumerate(routes):
        if cancelled():
            raise InterruptedError('测速已取消。')
        if route.rate == 16000 and passed_48k_shared >= 2:
            continue
        emit(
            'progress',
            {
                'fraction': i / (len(routes) + 1),
                'stage': 'benchmark',
                'message': f'正在实测 {i + 1}/{len(routes)}：{route.label}',
            },
        )
        try:
            result = measure(route, seconds)
        except InterruptedError:
            raise
        except Exception as error:
            result = {'route': route.to_dict(), 'stable': False, 'error': str(error)}
        results.append(result)
        if result.get('stable') and route.rate == 48000 and not route.exclusive:
            passed_48k_shared += 1

    ranked = sorted(
        [r for r in results if r.get('stable')],
        key=_route_rank,
    )
    selected = None
    for candidate in ranked[:2]:
        emit('progress', {'fraction': 0.95, 'stage': 'benchmark', 'message': '正在复验最低延迟方案…'})
        try:
            confirmation = measure(Route(**candidate['route']), max(3.0, seconds))
            candidate['confirmation'] = confirmation
            if confirmation['stable']:
                selected = confirmation
                break
        except InterruptedError:
            raise
        except Exception as error:
            candidate['confirmation_error'] = str(error)

    report = {
        'schema': 2,
        'fingerprint': fingerprint(input_id, output_id),
        'created_at': datetime.now(timezone.utc).isoformat(),
        'measurement': 'local_estimate_not_end_to_end_loopback',
        'probe_output': 'silence',
        'selected': selected,
        'results': results,
    }
    report['battle_mode'] = bool(battle_mode)
    write_json(cache_path(input_id, output_id, battle_mode=battle_mode), report)
    if selected:
        (data_dir() / 'route-invalidated.json').unlink(missing_ok=True)
    emit('benchmark', report)
    if not selected:
        raise RuntimeError('没有找到满足稳定性要求的路线。请关闭其他占用麦克风的软件，检查设备后重新测速。')
    return Route(**selected['route']), report

