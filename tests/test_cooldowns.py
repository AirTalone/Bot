from bot.services.cooldowns import CLAIM_PAID, ORDER_CREATE, CooldownGate


def test_cooldown_blocks_until_elapsed() -> None:
    gate = CooldownGate()
    assert gate.check(ORDER_CREATE, 1, 30) is None
    gate.hit(ORDER_CREATE, 1)
    hit = gate.check(ORDER_CREATE, 1, 30)
    assert hit is not None
    assert hit.retry_after_seconds >= 1
    assert gate.check(CLAIM_PAID, 1, 30) is None
    assert gate.check(ORDER_CREATE, 2, 30) is None


def test_cooldown_disabled_when_zero() -> None:
    gate = CooldownGate()
    gate.hit(ORDER_CREATE, 1)
    assert gate.check(ORDER_CREATE, 1, 0) is None
