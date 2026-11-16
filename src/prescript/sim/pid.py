"""Discrete PID with derivative on measurement and integrator-clamping anti-windup.

Reverse-acting for cooling: a supply temperature above setpoint opens the valve. `output_raw` is
the command before it is clamped to the stroke; the scoreboard reads it to see whether the loop
still has authority (a command pinned at a stroke end has none).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Pid:
    kp: float  # stroke per K
    ti_s: float  # integral time
    td_s: float = 0.0  # derivative time (0 = PI)
    out_min: float = 0.0
    out_max: float = 1.0
    integral: float = 0.0
    output_raw: float = 0.0
    _last_pv: float | None = field(default=None, repr=False)

    def reset(self, output: float, pv: float) -> None:
        """Start bumpless at `output` with the process at `pv` (and at setpoint)."""
        self.integral = output
        self.output_raw = output
        self._last_pv = pv

    def update(self, setpoint: float, pv: float, dt_s: float) -> float:
        error = pv - setpoint  # reverse-acting
        d_pv = 0.0 if self._last_pv is None else (pv - self._last_pv) / dt_s
        self._last_pv = pv
        p = self.kp * error
        d = self.kp * self.td_s * d_pv
        integral = self.integral + self.kp * dt_s / self.ti_s * error
        # Anti-windup: the integral may not grow past the point where it alone would hold the
        # output beyond a stroke end. It is never pulled back, so a large transient error does
        # not unwind what it has learned.
        if error > 0:
            integral = min(integral, max(self.integral, self.out_max - p - d))
        elif error < 0:
            integral = max(integral, min(self.integral, self.out_min - p - d))
        self.integral = integral
        self.output_raw = p + integral + d
        return min(max(self.output_raw, self.out_min), self.out_max)
