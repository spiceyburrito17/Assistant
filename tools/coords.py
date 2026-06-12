import time
import ctypes
from ctypes import wintypes  # <-- this is the bit that was missing

user32 = ctypes.windll.user32

def get_pos():
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y

print("Move mouse to TOP-LEFT of log area, wait 2s...")
time.sleep(2)
x1, y1 = get_pos()
print("top-left:", x1, y1)

print("Move mouse to BOTTOM-RIGHT of log area, wait 2s...")
time.sleep(2)
x2, y2 = get_pos()
print("bottom-right:", x2, y2)

print("width:", x2 - x1, "height:", y2 - y1)