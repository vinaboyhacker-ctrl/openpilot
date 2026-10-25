"""
CarrotMan navigation bridge for sunnypilot.

Ported from CarrotPilot (ajouatom/openpilot, selfdrive/carrot). Receives navigation data
(speed cameras, section enforcement, speed bumps, road speed limits, turn-by-turn) from the
CarrotMan Android app (TMAP / Kakao Navi) over the local network and turns it into a
target speed that the sunnypilot longitudinal planner can follow.
"""
