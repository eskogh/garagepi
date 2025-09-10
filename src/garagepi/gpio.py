try:
    import RPi.GPIO as GPIO
    ON_PI = True
except Exception:
    ON_PI = False
    class _Shim:
        BCM="BCM"; OUT="OUT"; IN="IN"; PUD_DOWN="PUD_DOWN"; BOTH="BOTH"; HIGH=1; LOW=0
        def __init__(self): self._pins={}
        def setmode(self,*a): pass
        def setup(self,p,m,pull_up_down=None): self._pins.setdefault(p,0)
        def input(self,p): return self._pins.get(p,0)
        def output(self,p,v): self._pins[p]=v
        def add_event_detect(self,*a,**k): pass
        def remove_event_detect(self,*a,**k): pass
        def cleanup(self): pass
    GPIO = _Shim()

def setup_default(trigger: int, s_open: int, s_closed: int):
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(trigger, GPIO.OUT)
    GPIO.setup(s_open, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    GPIO.setup(s_closed, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    return GPIO, ON_PI
